"""Data for the operations map: every camera (with status) and recent alerts placed on it."""
import json
from datetime import timedelta
from typing import List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.auth import admin_only, operator_or_admin
from backend.db.database import get_db
from backend.models.alert import Alert
from backend.models.camera import Camera
from backend.models.floor_plan import FloorPlan
from backend.services.audit import log_audit
from backend.models.user import User
from clock import utcnow

router = APIRouter(prefix="/map", tags=["map"])

HIDDEN_TYPES = {"PIPELINE_HEARTBEAT"}


class CameraMapResponse(BaseModel):
    camera_id: str
    name: str
    location: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    active: bool
    heading: Optional[float] = None
    fov: Optional[float] = None
    range_m: Optional[float] = None

    class Config:
        from_attributes = True


class MapEvent(BaseModel):
    alert_id: int
    event_type: str
    lat: Optional[float]
    lng: Optional[float]
    camera_id: Optional[str]
    camera_name: Optional[str]
    severity: str
    timestamp: str
    description: str
    person_name: Optional[str] = None
    acknowledged: bool = False


@router.get("/cameras", response_model=List[CameraMapResponse])
def get_camera_positions(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """Every camera, including switched-off ones and ones without GPS, so the map can flag them."""
    return db.query(Camera).order_by(Camera.camera_id).all()


@router.get("/events", response_model=List[MapEvent])
def get_map_events(
    hours: int = Query(24, ge=1, le=168),
    types: Optional[str] = Query(None, description="Comma-separated alert types"),
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    """Recent alerts with the position they were raised at (GPS stored with the alert, else the camera's)."""
    cutoff = utcnow() - timedelta(hours=hours)
    q = db.query(Alert).filter(Alert.timestamp >= cutoff, Alert.alert_type.notin_(HIDDEN_TYPES),
                               Alert.review_status != "rejected")
    if types:
        q = q.filter(Alert.alert_type.in_([t.strip() for t in types.split(",") if t.strip()]))
    cameras = {c.camera_id: c for c in db.query(Camera).all()}
    out = []
    for a in q.order_by(Alert.timestamp.desc()).limit(limit).all():
        cam = cameras.get(a.camera_id)
        lat = lng = None
        if a.details:
            try:
                geo = json.loads(a.details)
                lat, lng = geo.get("lat"), geo.get("lng")
            except (ValueError, TypeError, AttributeError):     # details not a JSON object
                pass
        if lat is None and cam is not None:
            lat, lng = cam.lat, cam.lng
        out.append(MapEvent(
            alert_id=a.id, event_type=a.alert_type, lat=lat, lng=lng,
            camera_id=a.camera_id, camera_name=cam.name if cam else a.camera_location,
            severity=a.severity, timestamp=a.timestamp.isoformat() if a.timestamp else "",
            description=(a.message or a.alert_type).split(" | ")[0].split(" — GPS")[0],
            person_name=a.person_name, acknowledged=bool(a.acknowledged),
        ))
    return out


# --- Floor plans ------------------------------------------------------------------------------
PLAN_MAX_BYTES = 10 * 1024 * 1024
PLAN_MAX_SIDE = 4000          # bigger plans are scaled down: the map never needs more


def _plan_out(p: FloorPlan) -> dict:
    return {"id": p.id, "name": p.name, "width": p.width, "height": p.height, "opacity": p.opacity,
            "bounds": [[p.south, p.west], [p.north, p.east]],
            "version": int(p.updated_at.timestamp()) if p.updated_at else 0}


def _check_bounds(south: float, west: float, north: float, east: float) -> None:
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise HTTPException(400, "Bounds must be south < north and west < east, within lat/lng range")
    if north - south > 0.2 or east - west > 0.2:
        raise HTTPException(400, "A floor plan covers a building or a site, not more than about 20 km")


class PlanPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    bounds: Optional[List[List[float]]] = None      # [[south, west], [north, east]]
    opacity: Optional[float] = Field(default=None, ge=0.1, le=1.0)


@router.get("/floorplans")
def list_floor_plans(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    return [_plan_out(p) for p in db.query(FloorPlan).order_by(FloorPlan.name).all()]


@router.get("/floorplans/{plan_id}/image")
def floor_plan_image(plan_id: int, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    p = db.query(FloorPlan).filter(FloorPlan.id == plan_id).first()
    if not p:
        raise HTTPException(404, "Floor plan not found")
    return Response(p.image, media_type=p.content_type, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/floorplans")
async def add_floor_plan(request: Request, name: str = Form(..., min_length=1, max_length=100),
                         south: float = Form(...), west: float = Form(...), north: float = Form(...),
                         east: float = Form(...), file: UploadFile = File(...),
                         db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    _check_bounds(south, west, north, east)
    raw = await file.read(PLAN_MAX_BYTES + 1)
    if len(raw) > PLAN_MAX_BYTES:
        raise HTTPException(413, "Floor plan image is over 10 MB")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise HTTPException(400, "Not an image (use PNG or JPEG)")
    h, w = img.shape[:2]
    if max(h, w) > PLAN_MAX_SIDE:
        f = PLAN_MAX_SIDE / max(h, w)
        img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    # Re-encoded: drops whatever else the upload carried (metadata, scripts in SVG-like tricks).
    png = file.content_type == "image/png" or (img.ndim == 3 and img.shape[2] == 4)
    ok, buf = cv2.imencode(".png" if png else ".jpg", img, [] if png else [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise HTTPException(400, "Could not read the image")
    p = FloorPlan(name=name.strip(), image=buf.tobytes(), content_type="image/png" if png else "image/jpeg",
                  width=w, height=h, south=south, west=west, north=north, east=east)
    db.add(p)
    db.flush()
    log_audit(db, admin, "FLOORPLAN_ADD", "floor_plan", str(p.id), p.name, request)
    db.commit()
    db.refresh(p)
    return _plan_out(p)


@router.put("/floorplans/{plan_id}")
def update_floor_plan(plan_id: int, body: PlanPatch, request: Request, db: Session = Depends(get_db),
                      admin: User = Depends(admin_only)):
    p = db.query(FloorPlan).filter(FloorPlan.id == plan_id).first()
    if not p:
        raise HTTPException(404, "Floor plan not found")
    if body.bounds is not None:
        try:
            (south, west), (north, east) = body.bounds
        except (TypeError, ValueError):
            raise HTTPException(400, "bounds must be [[south, west], [north, east]]")
        _check_bounds(south, west, north, east)
        p.south, p.west, p.north, p.east = south, west, north, east
    if body.name is not None:
        p.name = body.name.strip()
    if body.opacity is not None:
        p.opacity = body.opacity
    log_audit(db, admin, "FLOORPLAN_UPDATE", "floor_plan", str(p.id), p.name, request)
    db.commit()
    db.refresh(p)
    return _plan_out(p)


@router.delete("/floorplans/{plan_id}")
def delete_floor_plan(plan_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    p = db.query(FloorPlan).filter(FloorPlan.id == plan_id).first()
    if not p:
        raise HTTPException(404, "Floor plan not found")
    log_audit(db, admin, "FLOORPLAN_DELETE", "floor_plan", str(p.id), p.name, request)
    db.delete(p)
    db.commit()
    return {"deleted": plan_id}
