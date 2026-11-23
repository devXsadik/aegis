"""WebSocket endpoints for real-time alerts and system status."""

import logging
import os
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from backend.auth.auth import request_token
from backend.auth.guards import verify_viewer_token
from backend.utils.websocket import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websockets"])


def _origin_allowed(websocket: WebSocket) -> bool:
    """Browsers send cookies on a WebSocket handshake from any page, so check who opened it:
    the dashboard's own host, or an origin listed in CORS_ORIGINS. No Origin = not a browser."""
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    if urlsplit(origin).netloc == websocket.headers.get("host"):
        return True
    allowed = {o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")}
    return origin.rstrip("/") in allowed


def _authorized(websocket: WebSocket) -> bool:
    if not _origin_allowed(websocket):
        logger.warning("WebSocket refused: origin %s", websocket.headers.get("origin"))
        return False
    try:
        verify_viewer_token(request_token(websocket))
        return True
    except HTTPException:
        return False


async def _serve(websocket: WebSocket, channel: str) -> None:
    # The token check reads the database: run it off the event loop. A blocking pool wait here
    # used to stall the loop, so finished requests could not hand their connections back (deadlock).
    if not await run_in_threadpool(_authorized, websocket):
        await websocket.close(code=1008)
        return
    await manager.connect(websocket, channel)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel)


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await _serve(websocket, "alerts")


@router.websocket("/ws/incidents")
async def websocket_incidents(websocket: WebSocket):
    await _serve(websocket, "incidents")


@router.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    """Personal channel: only this user's notifications."""
    if not _origin_allowed(websocket):
        await websocket.close(code=1008)
        return
    try:
        user = await run_in_threadpool(verify_viewer_token, request_token(websocket))
    except HTTPException:
        await websocket.close(code=1008)
        return
    channel = f"user:{user.id}"
    await manager.connect(websocket, channel)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel)


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    await _serve(websocket, "status")
