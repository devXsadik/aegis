"""Detections: crops for alert cards, and Vehicle Search (spec 7.6).

Search is limited to the retention window (nothing older exists) and every search is
audit-logged with its reason / case number."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.auth.auth import operator_or_admin, supervisor_or_admin
from backend.auth.guards import viewer_dep
from backend.db.database import get_db
from backend.models.camera import Camera
from backend.models.detection import Detection
from backend.models.user import User
from backend.services.audit import log_audit
from backend.services.matching.common import load_json_config, save_json_config
from backend.utils.at_rest import unseal
from clock import utcnow

router = APIRouter(tags=["detections"])
SEARCH_ROLES = ("operator", "investigator", "supervisor", "admin")


@router.get("/detections/{det_id}/crop")
def detection_crop(det_id: int, request: Request, db: Session = Depends(get_db), viewer: User = Depends(viewer_dep)):
    d = db.get(Detection, det_id)
    if not d or not d.crop:
        raise HTTPException(404, "No image")
    log_audit(db, viewer, "DETECTION_VIEW", "detection", str(det_id), "", request)
    db.commit()
    return Response(content=unseal(d.crop, d.crop_encrypted), media_type="image/jpeg",
                    headers={"Cache-Control": "private, no-store"})


def _out(d: Detection, cams: dict) -> dict:
    cam = cams.get(d.camera_id)
    return {"id": d.id, "camera_id": d.camera_id, "camera_name": cam.name if cam else d.camera_id,
            "lat": cam.lat if cam else None, "lng": cam.lng if cam else None, "ts": d.ts.isoformat() if d.ts else None,
            "plate": d.plate_raw, "plate_canonical": d.plate_canonical, "plate_confidence": d.plate_confidence,
            "vehicle_type": d.vehicle_type, "color": d.color, "make_model": d.make_model,
            "confidences": json.loads(d.attr_conf) if d.attr_conf else {}, "color_reliable": d.color_reliable,
            "direction": d.direction, "matched": d.matched, "match_ref": d.match_ref, "incident_id": d.incident_id,
            "crop_url": f"/api/v1/detections/{d.id}/crop" if d.crop else None}


def _search(db: Session, *, plate, types, colors, models, cameras, jurisdiction_id, date_from, date_to, limit, skip):
    q = db.query(Detection).filter(Detection.kind == "vehicle")
    floor = utcnow() - timedelta(days=int(__import__("os").getenv("DETECTION_RETENTION_DAYS", "30")))
    q = q.filter(Detection.ts >= max(date_from or floor, floor))
    if date_to:
        q = q.filter(Detection.ts <= date_to)
    if plate:
        from core.analysis.bd_plate import canonical
        canon = canonical(plate)
        digits = "".join(ch for ch in plate.translate(str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")) if ch.isdigit())
        conds = [Detection.plate_raw.ilike(f"%{plate}%")]
        if canon:
            conds.append(Detection.plate_canonical == canon)
        if len(digits) >= 2:                       # partial: "3456" or "12-34"
            conds.append(Detection.plate_canonical.like(f"%{digits[:2]}%{digits[2:]}%" if len(digits) > 2 else f"%{digits}%"))
        q = q.filter(or_(*conds))
    if types:
        q = q.filter(Detection.vehicle_type.in_(types))
    if colors:
        q = q.filter(or_(Detection.color.in_(colors), Detection.color_secondary.in_(colors)))
    if models:
        q = q.filter(or_(*[Detection.make_model.ilike(f"%{m.replace('_', ' ').split(' ')[-1]}%") for m in models]))
    cam_ids = set(cameras or [])
    if jurisdiction_id:
        from backend.services.jurisdiction import _all, ancestors, locate
        by_id = _all(db)
        inside = {j for j in by_id if jurisdiction_id in ancestors(j, by_id)}
        for c in db.query(Camera):
            jid = c.jurisdiction_id or (locate(db, c.lat, c.lng, by_id).id if locate(db, c.lat, c.lng, by_id) else None)
            if jid in inside:
                cam_ids.add(c.camera_id)
        if not cam_ids:
            return 0, []
    if cam_ids:
        q = q.filter(Detection.camera_id.in_(sorted(cam_ids)))
    total = q.count()
    return total, q.order_by(Detection.ts.desc()).offset(skip).limit(limit).all()


@router.get("/vehicle-search")
def vehicle_search(
    request: Request,
    reason: str = Query(min_length=5, max_length=300, description="Why: case / FIR / GD number and purpose"),
    plate: Optional[str] = Query(default=None, max_length=60),
    vehicle_type: List[str] = Query(default=[]),
    color: List[str] = Query(default=[]),
    make_model: List[str] = Query(default=[]),
    camera_id: List[str] = Query(default=[]),
    jurisdiction_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=60, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), user: User = Depends(operator_or_admin),
):
    if user.role not in SEARCH_ROLES:
        raise HTTPException(403, "Your role cannot search detections")
    if not any([plate, vehicle_type, color, make_model, camera_id, jurisdiction_id]):
        raise HTTPException(400, "Give at least one search criterion")
    total, rows = _search(db, plate=plate, types=vehicle_type, colors=color, models=make_model, cameras=camera_id,
                          jurisdiction_id=jurisdiction_id, date_from=date_from, date_to=date_to, limit=limit, skip=skip)
    log_audit(db, user, "VEHICLE_SEARCH", "detection", "", json.dumps({
        "reason": reason, "plate": plate, "type": vehicle_type, "color": color, "model": make_model,
        "cameras": camera_id, "area": jurisdiction_id, "from": str(date_from) if date_from else None,
        "to": str(date_to) if date_to else None, "results": total}, ensure_ascii=False), request)
    db.commit()
    cams = {c.camera_id: c for c in db.query(Camera)}
    return {"total": total, "items": [_out(d, cams) for d in rows]}


@router.post("/vehicle-search/photo")
async def search_by_photo(
    request: Request, file: UploadFile = File(...), reason: str = Form(min_length=5, max_length=300),
    hours: int = Form(default=72, ge=1, le=24 * 30), db: Session = Depends(get_db), user: User = Depends(operator_or_admin),
):
    """Re-ID: recent vehicles that look like the uploaded photo, most similar first."""
    if user.role not in SEARCH_ROLES:
        raise HTTPException(403, "Your role cannot search detections")
    import cv2
    import numpy as np
    from core.analysis import vehicle_attrs
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "Photo larger than 8 MB")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Not an image")
    vec, model = vehicle_attrs.reid_embedding(img)
    since = utcnow() - timedelta(hours=hours)
    scored = []
    for d in (db.query(Detection).filter(Detection.kind == "vehicle", Detection.ts >= since,
                                         Detection.embedding.isnot(None)).limit(20000)):
        e = np.frombuffer(d.embedding, dtype=np.float32)
        c = vehicle_attrs.cosine(vec, e)
        if c is not None:
            scored.append((c, d))
    scored.sort(key=lambda x: -x[0])
    log_audit(db, user, "VEHICLE_SEARCH_PHOTO", "detection", "", json.dumps(
        {"reason": reason, "hours": hours, "model": model, "candidates": len(scored)}, ensure_ascii=False), request)
    db.commit()
    cams = {c.camera_id: c for c in db.query(Camera)}
    return {"model": model, "items": [{**_out(d, cams), "similarity": round(c, 3)} for c, d in scored[:60]]}


# ——— Matching configuration (Settings → Vehicle classes & models) ———

@router.get("/vehicle-match/config")
def get_match_config(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    from core.analysis.vehicle_match import DEFAULTS, merge_config
    return {"config": merge_config(load_json_config(db, "vehicle_match")), "defaults": DEFAULTS}


@router.put("/vehicle-match/config")
def put_match_config(body: dict, request: Request, db: Session = Depends(get_db), user: User = Depends(supervisor_or_admin)):
    from core.analysis.vehicle_match import merge_config
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    try:
        cfg = merge_config(body)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid values")
    if not all(0 <= v <= 1 for v in cfg["weights"].values()) or not 0 <= cfg["reid_threshold"] <= 1:
        raise HTTPException(400, "Weights and thresholds must be between 0 and 1")
    save_json_config(db, "vehicle_match", cfg, user.id)
    log_audit(db, user, "VEHICLE_MATCH_CONFIG", "config", "vehicle_match", json.dumps(cfg), request)
    db.commit()
    return {"config": cfg}
