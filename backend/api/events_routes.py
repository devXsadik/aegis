from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.auth.auth import operator_or_admin
from backend.models.user import User
from backend.utils.websocket import manager
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter(prefix="/events", tags=["events"])


class LiveEvent(BaseModel):
    event_type: str
    severity: str = "info"
    camera_location: Optional[str] = None
    camera_id: Optional[str] = None
    track_id: Optional[int] = None
    person_name: Optional[str] = None
    message: Optional[str] = None


@router.post("/live")
async def push_live_event(
    event: LiveEvent,
    user: User = Depends(operator_or_admin),
):
    payload = {
        "alert_type": event.event_type,
        "severity": event.severity,
        "camera_location": event.camera_location,
        "camera_id": event.camera_id,
        "track_id": event.track_id,
        "person_name": event.person_name,
        "message": event.message,
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "camera_location": event.camera_location,
            "criminal_name": event.person_name,
            "track_id": event.track_id,
        },
    }
    await manager.broadcast(payload, "alerts")
    return {"status": "broadcast", "event_type": event.event_type}
