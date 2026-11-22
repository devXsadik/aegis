"""System status and pipeline heartbeat tracking."""

import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from sqlalchemy.orm import Session

from backend.auth.auth import admin_only, operator_or_admin
from backend.db.database import get_db
from backend.services.audit import log_audit
from backend.models.user import User
from backend.utils.websocket import manager
from backend.utils.events import build_event_payload

from backend.auth.guards import verify_internal_key
from clock import utcnow

router = APIRouter(prefix="/system", tags=["system"])

_INSECURE_KEYS = {"", "pipeline-internal-key-change-me"}
_live_analytics: dict = {}
_pipeline_status: dict = {
    "online": False,
    "last_heartbeat": None,
    "cameras": {},
    "version": "5.0.0",
}


class HeartbeatPayload(BaseModel):
    camera_id: str
    camera_location: Optional[str] = None
    fps: Optional[float] = None
    threat_score: Optional[int] = None
    frame_number: Optional[int] = None
    analytics: Optional[dict] = None
    flags: Optional[list] = None        # red alerts in view now: [{type, label, origin}]
    infer_ms: Optional[int] = None      # last AI pass on this camera
    ai_age_s: Optional[float] = None    # seconds since the last finished AI pass


@router.get("/backups")
def backups(admin: User = Depends(admin_only)):
    from backend.services.backup import backup_dir, list_backups
    return {"folder": str(backup_dir()), "backups": list_backups(),
            "maintenance_hour": int(os.getenv("MAINTENANCE_HOUR", "3")),
            "keep": int(os.getenv("BACKUP_KEEP", "7"))}


@router.post("/backups")
async def backup_now(request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    """Back up now (the same as the nightly job's backup step)."""
    import asyncio
    from backend.services.backup import run_backup
    try:
        info = await asyncio.to_thread(run_backup)
    except Exception as e:
        raise HTTPException(500, f"Backup failed: {e}")
    log_audit(db, admin, "BACKUP", "system", info["name"], f"{info['bytes']} bytes", request)
    db.commit()
    return info


@router.get("/status")
def get_system_status(user: User = Depends(operator_or_admin)):
    from backend.services.ha import redis_health, camera_offline_sla

    cameras = {}
    offline = 0
    for cam_id, meta in _pipeline_status.get("cameras", {}).items():
        sla = camera_offline_sla(meta.get("last_seen"))
        if sla == "offline":
            # Paused, unplugged or crashed: counted, but no longer listed as a reporting camera.
            offline += 1
            continue
        cameras[cam_id] = {**meta, "sla": sla}

    from backend.services.model_health import model_status

    return {
        **_pipeline_status,
        "models": model_status(),
        "cameras": cameras,
        "offline_cameras": offline,
        "redis": redis_health(),
        "websocket_connections": {
            "alerts": manager.get_connection_count("alerts"),
            "status": manager.get_connection_count("status"),
        },
    }


@router.post("/heartbeat")
async def pipeline_heartbeat(
    body: HeartbeatPayload,
    x_internal_key: Optional[str] = Header(default=None, alias="X-Internal-Key"),
):
    verify_internal_key(x_internal_key)
    now = utcnow().isoformat()
    _pipeline_status["online"] = True
    _pipeline_status["last_heartbeat"] = now
    _pipeline_status["cameras"][body.camera_id] = {
        "camera_location": body.camera_location,
        "fps": body.fps,
        "threat_score": body.threat_score,
        "frame_number": body.frame_number,
        "flags": (body.flags or [])[:8],
        "infer_ms": body.infer_ms,
        "ai_age_s": body.ai_age_s,
        "last_seen": now,
    }

    payload = build_event_payload(
        event_type="PIPELINE_HEARTBEAT",
        severity="info",
        camera_id=body.camera_id,
        camera_location=body.camera_location,
        message=f"FPS: {body.fps:.1f}" if body.fps else "Pipeline active",
    )
    payload["fps"] = body.fps
    payload["threat_score"] = body.threat_score
    payload["flags"] = _pipeline_status["cameras"][body.camera_id]["flags"]   # dashboard updates the tile without polling
    payload["infer_ms"] = body.infer_ms
    payload["ai_age_s"] = body.ai_age_s
    if body.analytics:
        update_live_analytics(body.camera_id, body.analytics)
    await manager.broadcast(payload, "status")
    return {"status": "ok", "camera_id": body.camera_id}






def get_live_analytics() -> dict:
    return _live_analytics


def update_live_analytics(camera_id: str, data: dict) -> None:
    _live_analytics[camera_id] = {**data, "camera_id": camera_id, "updated_at": utcnow().isoformat()}
