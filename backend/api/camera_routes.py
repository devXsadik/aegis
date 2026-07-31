from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import urllib.parse
import requests
import logging
from backend.db.database import get_db
from backend.models.camera import Camera
from backend.models.user import User
from backend.auth.auth import operator_or_admin, admin_only

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cameras", tags=["cameras"])

@router.get("/resolve-ip")
def resolve_ip(url: str = Query(..., description="IP or URL of the camera"), user: User = Depends(operator_or_admin)):
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname or url
        # Remove any port if hostname somehow includes it (urlparse usually handles it)
        if ":" in hostname:
            hostname = hostname.split(":")[0]
            
        resp = requests.get(f"http://ip-api.com/json/{hostname}", timeout=5)
        data = resp.json()
        
        if data.get("status") == "success":
            location = f"{data.get('city', '')}, {data.get('country', '')}".strip(", ")
            return {
                "ip": data.get("query"),
                "location": location,
                "lat": data.get("lat"),
                "lng": data.get("lon")
            }
        else:
            return {
                "ip": hostname,
                "location": "",
                "lat": None,
                "lng": None,
                "error": data.get("message", "Unknown error")
            }
    except Exception as e:
        logger.error(f"Failed to resolve IP {url}: {e}")
        return {
            "ip": url,
            "location": "",
            "lat": None,
            "lng": None,
            "error": str(e)
        }


class CameraCreate(BaseModel):
    camera_id: str
    name: str
    location: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    rtsp_url: Optional[str] = None
    active: Optional[bool] = True


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


import yaml
from pathlib import Path

def sync_camera_to_yaml(cam: Camera):
    yaml_path = Path("config/cameras.yaml")
    if not yaml_path.exists():
        return
    try:
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f) or {"cameras": []}
            
        cameras = data.get("cameras", [])
        found = False
        for c in cameras:
            if c.get("id") == cam.camera_id:
                c["name"] = cam.name
                c["source"] = cam.rtsp_url
                c["location"] = cam.location
                c["lat"] = cam.lat
                c["lng"] = cam.lng
                c["enabled"] = cam.active
                found = True
                break
                
        if not found and cam.active:
            cameras.append({
                "id": cam.camera_id,
                "name": cam.name,
                "source": cam.rtsp_url,
                "location": cam.location,
                "lat": cam.lat,
                "lng": cam.lng,
                "enabled": True,
                "fps_limit": 15,
                "priority": "high"
            })
            
        data["cameras"] = cameras
        with open(yaml_path, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)
    except Exception as e:
        logger.error(f"Failed to sync camera to yaml: {e}")

@router.post("/", response_model=CameraResponse)
def create_camera(cam: CameraCreate, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    existing = db.query(Camera).filter(Camera.camera_id == cam.camera_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Camera ID already exists")
    camera = Camera(**cam.model_dump())
    db.add(camera)
    db.commit()
    db.refresh(camera)
    sync_camera_to_yaml(camera)
    return camera


@router.put("/{camera_id}", response_model=CameraResponse)
def update_camera(camera_id: str, cam: CameraCreate, db: Session = Depends(get_db),
                  admin: User = Depends(admin_only)):
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    for key, val in cam.model_dump(exclude_unset=True).items():
        setattr(camera, key, val)
    db.commit()
    db.refresh(camera)
    sync_camera_to_yaml(camera)
    return camera


@router.delete("/{camera_id}")
def delete_camera(camera_id: str, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    camera.active = False
    sync_camera_to_yaml(camera)
    db.delete(camera)
    db.commit()
    return {"status": "deleted"}
