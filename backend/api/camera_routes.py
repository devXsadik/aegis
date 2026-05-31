import io
import json
import os
import time
import cv2
import yaml
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.models.camera import Camera
from backend.auth.auth import verify_token, operator_or_admin, admin_only
from backend.models.user import User
from backend.utils.websocket import manager
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime

router = APIRouter(prefix="/cameras", tags=["cameras"])


class CameraCreate(BaseModel):
    camera_id: str
    name: str
    uri: str
    location: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    ptz_supported: bool = False
    username: Optional[str] = None
    password: Optional[str] = None


class CameraResponse(BaseModel):
    camera_id: str
    name: str
    uri: str
    location: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    active: bool
    ptz_supported: bool
    status: str = "stopped"

    class Config:
        from_attributes = True


# ── In-memory health cache ──
_health_cache: dict = {}
_health_cache_lock = None


def _get_health_lock():
    global _health_cache_lock
    if _health_cache_lock is None:
        import threading
        _health_cache_lock = threading.Lock()
    return _health_cache_lock


def _probe_camera(uri: str, timeout: float = 5.0) -> dict:
    """Open cv2.VideoCapture, grab one frame, return health info."""
    cap = cv2.VideoCapture(uri)
    start = time.time()
    if not cap.isOpened():
        return {"connected": False}
    ret, frame = cap.read()
    elapsed_ms = (time.time() - start) * 1000
    info = {
        "connected": ret,
        "connection_time_ms": round(elapsed_ms, 1),
    }
    if ret and frame is not None:
        h, w = frame.shape[:2]
        fps = cap.get(cv2.CAP_PROP_FPS)
        info.update({"width": w, "height": h, "fps": round(fps, 1)})
    cap.release()
    return info


# ── Endpoints ──


@router.get("/", response_model=List[CameraResponse])
def list_cameras(
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cameras = db.query(Camera).all()
    result = []
    for cam in cameras:
        status = (
            "running"
            if cam.camera_id in manager.active_connections.get("video", set())
            else "stopped"
        )
        result.append(CameraResponse(
            camera_id=cam.camera_id, name=cam.name, uri=cam.uri,
            location=cam.location, lat=cam.lat, lng=cam.lng,
            active=cam.active, ptz_supported=cam.ptz_supported, status=status,
        ))
    return result


@router.post("/", response_model=CameraResponse)
def add_camera(
    camera: CameraCreate,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    existing = db.query(Camera).filter(Camera.camera_id == camera.camera_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Camera already exists")
    cam = Camera(
        camera_id=camera.camera_id, name=camera.name, uri=camera.uri,
        location=camera.location, lat=camera.lat, lng=camera.lng,
        ptz_supported=camera.ptz_supported,
    )
    db.add(cam)
    db.commit()
    return CameraResponse(
        camera_id=cam.camera_id, name=cam.name, uri=cam.uri,
        location=cam.location, lat=cam.lat, lng=cam.lng,
        active=cam.active, ptz_supported=cam.ptz_supported,
    )


@router.put("/{camera_id}")
def update_camera(
    camera_id: str,
    body: CameraCreate,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cam = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cam, field, value)
    db.commit()
    return {"status": "updated"}


@router.delete("/{camera_id}")
def remove_camera(
    camera_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cam = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    db.delete(cam)
    db.commit()
    return {"status": "deleted"}


# ── Health ──


@router.get("/{camera_id}/health")
def camera_health(
    camera_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cam = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    info = _probe_camera(cam.uri)
    return {"camera_id": camera_id, "uri": cam.uri, **info}


@router.get("/health")
def all_cameras_health(
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cameras = db.query(Camera).filter(Camera.active == True).all()
    results = []
    for cam in cameras:
        info = _probe_camera(cam.uri)
        results.append({"camera_id": cam.camera_id, "uri": cam.uri, **info})
    return results


# ── MJPEG Stream ──


def _mjpeg_generator(uri: str):
    """Yield MJPEG frames from a cv2 VideoCapture."""
    cap = cv2.VideoCapture(uri)
    if not cap.isOpened():
        yield b""
        return
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            ret_jpg, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret_jpg:
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(buf)).encode() + b"\r\n\r\n"
                + buf.tobytes() + b"\r\n"
            )
    finally:
        cap.release()


@router.get("/{camera_id}/mjpeg")
def mjpeg_stream(
    camera_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cam = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return StreamingResponse(
        _mjpeg_generator(cam.uri),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )


# ── Sync from config ──


@router.post("/sync-config")
def sync_cameras_from_config(
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    """Load cameras from config/config.yaml into the DB."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_path = os.path.join(base_dir, "config", "config.yaml")
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="config.yaml not found")

    cameras_cfg = cfg.get("cameras", [])
    synced = {"created": 0, "updated": 0, "skipped": 0, "total": len(cameras_cfg)}

    for cam_cfg in cameras_cfg:
        cid = cam_cfg.get("id", "")
        if not cid:
            synced["skipped"] += 1
            continue
        existing = db.query(Camera).filter(Camera.camera_id == cid).first()
        if existing:
            existing.uri = cam_cfg.get("uri", existing.uri)
            existing.location = cam_cfg.get("location", existing.location)
            existing.name = cam_cfg.get("name", existing.name)
            existing.lat = cam_cfg.get("lat", existing.lat)
            existing.lng = cam_cfg.get("lng", existing.lng)
            synced["updated"] += 1
        else:
            cam = Camera(
                camera_id=cid,
                name=cam_cfg.get("name", cid),
                uri=str(cam_cfg.get("uri", "")),
                location=cam_cfg.get("location", ""),
                lat=cam_cfg.get("lat", 0.0),
                lng=cam_cfg.get("lng", 0.0),
                ptz_supported=cam_cfg.get("ptz_supported", False),
            )
            db.add(cam)
            synced["created"] += 1

    db.commit()
    return {"status": "synced", **synced}


# ── Discover ──


@router.get("/discover")
def discover_cameras(
    subnet: str = "192.168.1.0/24",
    user: User = Depends(admin_only),
):
    """Run camera discovery on a subnet."""
    from utils.camera_discovery import discover
    results = discover(subnet=subnet)
    return {"subnet": subnet, "cameras_found": len(results), "cameras": results}


# ── PTZ ──

_ptz_controllers: dict = {}


def _get_ptz(cam) -> Any:
    from core.ptz_controller import PTZController
    cid = cam.camera_id
    if cid not in _ptz_controllers:
        ctrl = PTZController(
            camera_uri=cam.uri,
            protocol="onvif",
            username=getattr(cam, 'username', '') or '',
            password=getattr(cam, 'password', '') or '',
        )
        ctrl.connect()
        _ptz_controllers[cid] = ctrl
    return _ptz_controllers.get(cid)


@router.post("/{camera_id}/ptz")
def ptz_command(
    camera_id: str,
    command: str,
    value: float = 0.0,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cam = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not cam.ptz_supported:
        raise HTTPException(status_code=400, detail="Camera does not support PTZ")
    valid = {"pan_left", "pan_right", "tilt_up", "tilt_down", "zoom_in", "zoom_out", "stop"}
    if command not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid PTZ command. Valid: {valid}")
    ctrl = _get_ptz(cam)
    if command == "stop":
        ctrl.stop()
    elif command == "pan_left":
        ctrl.pan_left(value)
    elif command == "pan_right":
        ctrl.pan_right(value)
    elif command == "tilt_up":
        ctrl.tilt_up(value)
    elif command == "tilt_down":
        ctrl.tilt_down(value)
    elif command == "zoom_in":
        ctrl.zoom_in(value)
    elif command == "zoom_out":
        ctrl.zoom_out(value)
    return {"status": f"PTZ {command} {value}", "camera_id": camera_id}


# ── WebSocket ──


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await manager.connect(websocket, "alerts")
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"heartbeat: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "alerts")


@router.websocket("/ws/video/{camera_id}")
async def websocket_video(websocket: WebSocket, camera_id: str):
    await manager.connect(websocket, "video")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, "video")


async def broadcast_alert(alert_data: dict):
    await manager.broadcast(alert_data, "alerts")
