from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.models.vehicle import LicensePlate, VehicleDetection
from backend.auth.auth import admin_only, operator_or_admin
from backend.auth.guards import verify_internal_key
from backend.models.user import User
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


class LicensePlateCreate(BaseModel):
    plate_number: str
    reason: Optional[str] = None


class LicensePlateResponse(BaseModel):
    id: int
    plate_number: str
    watchlisted: bool
    reason: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class VehicleDetectionIngest(BaseModel):
    camera_location: str = Field(..., min_length=1)
    track_id: int
    vehicle_type: str = "vehicle"
    license_plate: Optional[str] = None
    plate_confidence: Optional[float] = None
    is_suspicious: bool = False
    evidence_id: Optional[int] = None


@router.get("/plates", response_model=List[LicensePlateResponse])
def list_plates(
    skip: int = 0,
    limit: int = 100,
    watchlisted_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    query = db.query(LicensePlate)
    if watchlisted_only:
        query = query.filter(LicensePlate.watchlisted == True)
    return query.offset(skip).limit(limit).all()


@router.post("/plates", status_code=410)
def add_watchlisted_plate(plate: LicensePlateCreate, admin: User = Depends(admin_only)):
    """Retired: a plate alone, with no case number, approval or expiry, may no longer alert."""
    raise HTTPException(status_code=410, detail="Use POST /api/v1/watchlist/vehicles: watchlist entries need a "
                                                "case number, legal basis, second-person approval and an expiry date")


@router.delete("/plates/{plate_number}", status_code=410)
def remove_watchlisted_plate(plate_number: str, admin: User = Depends(admin_only)):
    raise HTTPException(status_code=410, detail="Use POST /api/v1/watchlist/vehicles/{ref}/revoke")


@router.get("/detections")
def list_vehicle_detections(
    skip: int = 0,
    limit: int = 100,
    suspicious_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    query = db.query(VehicleDetection)
    if suspicious_only:
        query = query.filter(VehicleDetection.is_suspicious == True)
    return query.order_by(VehicleDetection.timestamp.desc()).offset(skip).limit(limit).all()


@router.post("/detections/ingest")
def ingest_vehicle_detection(
    body: VehicleDetectionIngest,
    db: Session = Depends(get_db),
    x_internal_key: Optional[str] = Header(None),
):
    """Pipeline → DB: record a confirmed plate / vehicle sighting for the Vehicles page."""
    verify_internal_key(x_internal_key)
    plate = (body.license_plate or "").strip().upper() or None
    conf = None
    if body.plate_confidence is not None:
        conf = f"{float(body.plate_confidence):.3f}"
    row = VehicleDetection(
        camera_location=body.camera_location,
        track_id=int(body.track_id),
        vehicle_type=(body.vehicle_type or "vehicle")[:20],
        license_plate=plate[:20] if plate else None,
        plate_confidence=conf,
        is_suspicious=bool(body.is_suspicious or (plate and _is_watchlisted(db, plate))),
        evidence_id=body.evidence_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"status": "ok", "id": row.id}


def _is_watchlisted(db: Session, plate: str) -> bool:
    return db.query(LicensePlate.id).filter(
        LicensePlate.plate_number == plate, LicensePlate.watchlisted == True  # noqa: E712
    ).first() is not None
