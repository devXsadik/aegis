import os
from fastapi import APIRouter, Depends, Header, HTTPException
from backend.auth.auth import operator_or_admin
from backend.models.user import User
from backend.utils.events import broadcast_live_event
from pydantic import BaseModel
from typing import Optional

from backend.auth.guards import verify_internal_key

router = APIRouter(prefix="/events", tags=["events"])


class LiveEvent(BaseModel):
    event_type: str
    severity: str = "info"
    camera_location: Optional[str] = None
    camera_id: Optional[str] = None
    track_id: Optional[int] = None
    person_name: Optional[str] = None
    message: Optional[str] = None


def _verify_internal_key(key: Optional[str]) -> None:
    verify_internal_key(key)


@router.post("/live")
async def push_live_event(
    event: LiveEvent,
    user: User = Depends(operator_or_admin),
):
    payload = await broadcast_live_event(
        event_type=event.event_type,
        severity=event.severity,
        camera_location=event.camera_location,
        camera_id=event.camera_id,
        track_id=event.track_id,
        person_name=event.person_name,
        message=event.message,
    )
    return {"status": "broadcast", "event_type": event.event_type, "payload": payload}


@router.post("/internal")
async def push_internal_event(
    event: LiveEvent,
    x_internal_key: Optional[str] = Header(default=None, alias="X-Internal-Key"),
):
    """Pipeline-to-backend event push (no JWT; uses shared internal key)."""
    _verify_internal_key(x_internal_key)
    payload = await broadcast_live_event(
        event_type=event.event_type,
        severity=event.severity,
        camera_location=event.camera_location,
        camera_id=event.camera_id,
        track_id=event.track_id,
        person_name=event.person_name,
        message=event.message,
    )
    return {"status": "broadcast", "event_type": event.event_type}
