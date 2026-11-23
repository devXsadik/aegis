"""Camera registry extras: credentials (sealed, write-only), per-camera ingest tokens, the
stream source for the pipeline, CSV bulk import, and the health dashboard."""

from __future__ import annotations

import csv
import io
import json
import secrets
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.auth import admin_only, operator_or_admin
from backend.auth.guards import verify_internal_key
from backend.db.database import get_db
from backend.models.camera import Camera
from backend.models.jurisdiction import Jurisdiction
from backend.models.user import User
from backend.api.ingest_routes import token_hash
from backend.services.audit import log_audit
from backend.utils.at_rest import seal, unseal
from clock import utcnow

router = APIRouter(prefix="/cameras", tags=["camera-registry"])

PROTOCOLS = ("rtsp", "onvif", "vendor", "webhook", "device", "file")
CAPABILITIES = ("face", "anpr", "vehicle_attr", "ptz")
ONLINE_SECONDS = 60
CSV_COLUMNS = ["camera_id", "name", "lat", "lng", "heading", "fov", "protocol", "vendor", "stream_url", "address",
               "road_name", "thana_code", "capabilities", "ir_mode", "sample_fps", "username", "password"]


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


def _cam(db: Session, camera_id: str) -> Camera:
    cam = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    return cam


def _seal_creds(cam: Camera, username: str, password: str) -> None:
    cam.credentials, cam.credentials_encrypted = seal(json.dumps({"username": username, "password": password}).encode())


@router.put("/{camera_id}/credentials")
def set_credentials(camera_id: str, body: Credentials, request: Request, db: Session = Depends(get_db),
                    admin: User = Depends(admin_only)):
    cam = _cam(db, camera_id)
    _seal_creds(cam, body.username, body.password)
    log_audit(db, admin, "CAMERA_CREDENTIALS", "camera", camera_id, "set (value not logged)", request)
    db.commit()
    return {"camera_id": camera_id, "has_credentials": True}


@router.delete("/{camera_id}/credentials")
def clear_credentials(camera_id: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    cam = _cam(db, camera_id)
    cam.credentials, cam.credentials_encrypted = None, False
    log_audit(db, admin, "CAMERA_CREDENTIALS", "camera", camera_id, "cleared", request)
    db.commit()
    return {"camera_id": camera_id, "has_credentials": False}


@router.post("/{camera_id}/ingest-token")
def new_ingest_token(camera_id: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    """A new token for the camera's webhook; shown once, stored only as a hash. Replaces the old one."""
    cam = _cam(db, camera_id)
    token = secrets.token_urlsafe(32)
    cam.ingest_token_hash = token_hash(token)
    log_audit(db, admin, "CAMERA_INGEST_TOKEN", "camera", camera_id, "issued", request)
    db.commit()
    vendor = cam.vendor or "generic"
    return {"camera_id": camera_id, "token": token,
            "url": f"/api/v1/ingest/{vendor}/{camera_id}", "header": "X-Camera-Token"}


def stream_source(cam: Camera) -> Optional[str]:
    """RTSP URL with the stored credentials put in (for the pipeline only)."""
    url = cam.rtsp_url
    if not url or not cam.credentials:
        return url
    creds = json.loads(unseal(cam.credentials, cam.credentials_encrypted))
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = f"{quote(creds['username'], safe='')}:{quote(creds['password'], safe='')}@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


@router.get("/{camera_id}/stream-source")
def get_stream_source(camera_id: str, db: Session = Depends(get_db),
                      x_internal_key: Optional[str] = Header(default=None, alias="X-Internal-Key")):
    verify_internal_key(x_internal_key)
    cam = _cam(db, camera_id)
    return {"camera_id": camera_id, "source": stream_source(cam), "sample_fps": cam.sample_fps,
            "priority": cam.priority}


@router.get("/{camera_id}/detail")
def camera_detail(camera_id: str, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """One camera's registry entry (credentials never included)."""
    from backend.api.camera_routes import CameraResponse
    return CameraResponse.model_validate(_cam(db, camera_id)).model_dump(mode="json")


# ——— Health ———

def _age(ts) -> Optional[float]:
    if not ts:
        return None
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if ts.tzinfo:
        ts = ts.replace(tzinfo=None)
    return (utcnow() - ts).total_seconds()


def camera_health(cam: Camera, beat: Optional[dict]) -> dict:
    ages = [a for a in (_age(beat.get("last_seen")) if beat else None, _age(cam.last_heartbeat)) if a is not None]
    age = min(ages) if ages else None
    fps = beat.get("fps") if beat else None
    ai_age = beat.get("ai_age_s") if beat else None
    if not cam.active:
        status, reason = "disabled", "Paused"
    elif age is None:
        status, reason = "offline", "Never reported"
    elif age > ONLINE_SECONDS:
        status, reason = "offline", f"No report for {int(age // 60)} min {int(age % 60)} s"
    elif fps is not None and fps < 2:
        status, reason = "degraded", f"Low frame rate ({fps:.1f} fps)"
    elif ai_age is not None and ai_age > 10:
        status, reason = "degraded", f"Detection lagging {ai_age:.0f} s"
    else:
        status, reason = "online", None
    return {"camera_id": cam.camera_id, "name": cam.name, "status": status, "reason": reason,
            "last_seen_s": round(age) if age is not None else None, "fps": fps, "ai_age_s": ai_age,
            "infer_ms": beat.get("infer_ms") if beat else None, "protocol": cam.protocol, "vendor": cam.vendor,
            "jurisdiction_id": cam.jurisdiction_id, "lat": cam.lat, "lng": cam.lng, "heading": cam.heading,
            "capabilities": json.loads(cam.capabilities) if cam.capabilities else [], "priority": cam.priority}


@router.get("/health")
def health(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    from backend.api.system_routes import _pipeline_status
    beats = _pipeline_status.get("cameras", {})
    cams = db.query(Camera).order_by(Camera.name).all()
    rows = [camera_health(c, beats.get(c.camera_id)) for c in cams]
    changed = False
    for c, r in zip(cams, rows):          # keep the stored status in step (map colours, reports)
        if c.status != r["status"]:
            c.status, changed = r["status"], True
    if changed:
        db.commit()
    summary = {s: sum(r["status"] == s for r in rows) for s in ("online", "degraded", "offline", "disabled")}
    return {"summary": summary, "total": len(rows), "cameras": rows}


# ——— CSV import ———

def _f(v, lo=None, hi=None, name=""):
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except ValueError:
        raise ValueError(f"{name} is not a number")
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        raise ValueError(f"{name} out of range")
    return x


@router.get("/import/template")
def import_template(user: User = Depends(operator_or_admin)):
    from fastapi.responses import Response
    sample = ("cam_gulshan_1,Gulshan 1 circle,23.7806,90.4163,45,90,rtsp,hikvision,rtsp://10.0.0.5:554/Streaming/Channels/101,"
              "Gulshan Ave,Gulshan Avenue,DMP-GULSHAN,face|anpr|vehicle_attr,true,5,admin,secret\n")
    return Response(content=",".join(CSV_COLUMNS) + "\n" + sample, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="cameras_template.csv"'})


@router.post("/import")
async def import_csv(request: Request, file: UploadFile = File(...), dry_run: bool = Query(default=True),
                     db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    """Create or update cameras from CSV. dry_run=true (default) only validates and reports."""
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "CSV larger than 5 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "CSV must be UTF-8")
    reader = csv.DictReader(io.StringIO(text))
    missing = {"camera_id", "name"} - set(reader.fieldnames or [])
    if missing:
        raise HTTPException(400, f"CSV needs columns: {', '.join(sorted(missing))}")
    areas = {j.code: j.id for j in db.query(Jurisdiction)}
    existing = {c.camera_id: c for c in db.query(Camera)}
    results, seen = [], set()
    from backend.api.camera_routes import _auto_jurisdiction, sync_camera_to_yaml
    for i, row in enumerate(reader, start=2):
        row = {k: (v or "").strip() for k, v in row.items() if k}
        cid = row.get("camera_id", "")
        try:
            if not cid or len(cid) > 50 or not all(ch.isalnum() or ch in "_-." for ch in cid):
                raise ValueError("camera_id must be 1–50 letters, digits, _ - .")
            if cid in seen:
                raise ValueError("camera_id repeated in this file")
            seen.add(cid)
            if not row.get("name"):
                raise ValueError("name is required")
            protocol = (row.get("protocol") or "rtsp").lower()
            if protocol not in PROTOCOLS:
                raise ValueError(f"protocol must be one of {', '.join(PROTOCOLS)}")
            caps = [c.strip().lower() for c in row.get("capabilities", "").replace(";", "|").split("|") if c.strip()]
            bad = [c for c in caps if c not in CAPABILITIES]
            if bad:
                raise ValueError(f"unknown capabilities: {', '.join(bad)}")
            thana = row.get("thana_code")
            if thana and thana not in areas:
                raise ValueError(f"thana_code {thana} not found")
            fields = {
                "name": row["name"][:100], "lat": _f(row.get("lat"), -90, 90, "lat"), "lng": _f(row.get("lng"), -180, 180, "lng"),
                "heading": _f(row.get("heading"), 0, 359.999, "heading"), "fov": _f(row.get("fov"), 1, 360, "fov"),
                "protocol": protocol, "vendor": row.get("vendor") or None, "rtsp_url": row.get("stream_url") or None,
                "address": row.get("address") or None, "road_name": row.get("road_name") or None,
                "capabilities": json.dumps(caps), "ir_mode": row.get("ir_mode", "").lower() in ("1", "true", "yes", "y"),
                "sample_fps": _f(row.get("sample_fps"), 0.1, 60, "sample_fps"),
                "jurisdiction_id": areas.get(thana) if thana else None,
            }
            if bool(row.get("username")) != bool(row.get("password")):
                raise ValueError("give both username and password, or neither")
            action = "update" if cid in existing else "create"
            results.append({"line": i, "camera_id": cid, "action": action, "ok": True})
            if dry_run:
                continue
            cam = existing.get(cid) or Camera(camera_id=cid, active=True)
            for k, v in fields.items():
                setattr(cam, k, v)
            if row.get("username"):
                _seal_creds(cam, row["username"], row["password"])
            _auto_jurisdiction(db, cam)
            if cid not in existing:
                db.add(cam)
                existing[cid] = cam
        except ValueError as e:
            results.append({"line": i, "camera_id": cid, "ok": False, "error": str(e)})
    ok = [r for r in results if r["ok"]]
    if not dry_run:
        if any(not r["ok"] for r in results):
            db.rollback()
            raise HTTPException(422, detail={"message": "Nothing imported: fix the rows with errors first", "rows": results})
        log_audit(db, admin, "CAMERA_IMPORT", "camera", "", f"{len(ok)} rows", request)
        db.commit()
        for r in ok:
            try:
                sync_camera_to_yaml(existing[r["camera_id"]])
            except Exception:
                pass
    return {"dry_run": dry_run, "rows": results, "valid": len(ok), "invalid": len(results) - len(ok)}


class Priority(BaseModel):
    priority: int = Field(ge=0, le=10)
    sample_fps: Optional[float] = Field(default=None, gt=0, le=60)


def set_priority(db: Session, camera_ids: List[str], priority: int, sample_fps: Optional[float] = None) -> int:
    """Raise / restore processing priority (used by lookouts, Phase 9)."""
    n = 0
    for cam in db.query(Camera).filter(Camera.camera_id.in_(camera_ids)):
        cam.priority = priority
        if sample_fps is not None:
            cam.sample_fps = sample_fps
        n += 1
    return n

