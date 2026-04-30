from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.models.evidence import Evidence
from backend.auth.auth import verify_token, operator_or_admin
from backend.models.user import User
from backend.utils.websocket import manager
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter(prefix="/cameras", tags=["cameras"])


class CameraCreate(BaseModel):
    camera_id: str
    name: str
    source: str
    location: str
    zone: str = "default"
    enabled: bool = True
    conf_threshold: float = 0.5
    weapon_conf_threshold: float = 0.4


class CameraResponse(BaseModel):
    camera_id: str
    name: str
    source: str
    location: str
    zone: str
    enabled: bool
    status: str = "stopped"

    class Config:
        orm_mode = True


# In-memory camera registry (in production, use Redis/DB)
camera_registry = {}


@router.get("/", response_model=list[CameraResponse])
def list_cameras(user: User = Depends(operator_or_admin)):
    return [
        CameraResponse(
            camera_id=cam.camera_id,
            name=cam.name,
            source=cam.source,
            location=cam.location,
            zone=cam.zone,
            enabled=cam.enabled,
            status="running" if cam.camera_id in manager.active_connections.get("video", set()) else "stopped"
        )
        for cam in camera_registry.values()
    ]


@router.post("/", response_model=CameraResponse)
def add_camera(camera: CameraCreate, user: User = Depends(operator_or_admin)):
    camera_registry[camera.camera_id] = camera
    return CameraResponse(**camera.dict(), status="stopped")


@router.delete("/{camera_id}")
def remove_camera(camera_id: str, user: User = Depends(operator_or_admin)):
    if camera_id in camera_registry:
        del camera_registry[camera_id]
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Camera not found")


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await manager.connect(websocket, "alerts")
    try:
        while True:
            # Keep connection alive, wait for messages
            data = await websocket.receive_text()
            # Echo back for heartbeat
            await websocket.send_text(f"heartbeat: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "alerts")


@router.websocket("/ws/video/{camera_id}")
async def websocket_video(websocket: WebSocket, camera_id: str):
    await manager.connect(websocket, "video")
    try:
        while True:
            # Video frames would be sent here by the main loop
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, "video")


async def broadcast_alert(alert_data: dict):
    """Broadcast alert to all connected clients"""
    await manager.broadcast(alert_data, "alerts")
