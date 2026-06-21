from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from backend.db.database import get_db
from backend.models.camera import Camera
from backend.models.user import User
from backend.auth.auth import operator_or_admin, admin_only

router = APIRouter(prefix="/cameras", tags=["cameras"])


class CameraCreate(BaseModel):
    camera_id: str
    name: str
    location: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    rtsp_url: Optional[str] = None


class CameraResponse(BaseModel):
    id: int
    camera_id: str
    name: str
    location: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    active: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=List[CameraResponse])
def list_cameras(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    return db.query(Camera).all()


@router.post("/", response_model=CameraResponse)
def create_camera(cam: CameraCreate, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    existing = db.query(Camera).filter(Camera.camera_id == cam.camera_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Camera ID already exists")
    camera = Camera(**cam.model_dump())
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


@router.put("/{camera_id}", response_model=CameraResponse)
def update_camera(camera_id: str, cam: CameraCreate, db: Session = Depends(get_db),
                  admin: User = Depends(admin_only)):
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    for key, val in cam.model_dump().items():
        setattr(camera, key, val)
    db.commit()
    db.refresh(camera)
    return camera


@router.delete("/{camera_id}")
def delete_camera(camera_id: str, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    db.delete(camera)
    db.commit()
    return {"status": "deleted"}
