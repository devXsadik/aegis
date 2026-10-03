from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.auth.auth import operator_or_admin
from backend.models.user import User
from backend.models.camera import Camera
from backend.models.evidence import Evidence
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta

router = APIRouter(prefix="/map", tags=["map"])


class CameraMapResponse(BaseModel):
    camera_id: str
    name: str
    location: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    active: bool

    class Config:
        from_attributes = True


class MapEvent(BaseModel):
    event_type: str
    lat: float
    lng: float
    camera_id: str
    camera_name: str
    severity: str
    timestamp: str
    description: str


@router.get("/cameras", response_model=List[CameraMapResponse])
def get_camera_positions(
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    return db.query(Camera).filter(Camera.active == True).all()


@router.get("/events")
def get_map_events(
    hours: int = 24,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    cameras = {c.camera_id: c for c in db.query(Camera).all()}
    detections = (
        db.query(Evidence)
        .filter(Evidence.timestamp >= cutoff)
        .order_by(Evidence.timestamp.desc())
        .limit(200)
        .all()
    )
    events = []
    for d in detections:
        cam = cameras.get(d.camera_location) or next(
            (c for c in cameras.values() if c.location == d.camera_location), None
        )
        if not cam or not cam.lat or not cam.lng:
            continue
        severity = "high" if d.is_criminal or d.weapon_present else "medium" if d.is_suspicious else "low"
        events.append(MapEvent(
            event_type=d.category or "detection",
            lat=cam.lat, lng=cam.lng,
            camera_id=cam.camera_id, camera_name=cam.name,
            severity=severity,
            timestamp=d.timestamp.isoformat(),
            description=d.person_name or f"Track {d.track_id}",
        ))
    return events
