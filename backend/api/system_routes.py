"""System status and pipeline heartbeat tracking."""

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from backend.utils.websocket import manager
from backend.utils.events import build_event_payload

router = APIRouter(prefix="/system", tags=["system"])

_INSECURE_KEYS = {"", "pipeline-internal-key-change-me"}
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


def _verify_internal_key(key: Optional[str]) -> None:
    expected = os.getenv("INTERNAL_API_KEY", "pipeline-internal-key-change-me")
    if not key or key != expected:
        raise HTTPException(status_code=401, detail="Invalid internal API key")


@router.get("/status")
def get_system_status():
    return {
        **_pipeline_status,
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
    _verify_internal_key(x_internal_key)
    now = datetime.utcnow().isoformat()
    _pipeline_status["online"] = True
    _pipeline_status["last_heartbeat"] = now
    _pipeline_status["cameras"][body.camera_id] = {
        "camera_location": body.camera_location,
        "fps": body.fps,
        "threat_score": body.threat_score,
        "frame_number": body.frame_number,
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
    await manager.broadcast(payload, "status")
    return {"status": "ok", "camera_id": body.camera_id}

