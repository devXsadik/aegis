"""Live video streaming — pipeline pushes annotated JPEG frames, dashboard pulls MJPEG.

The CV pipeline POSTs frames (internal key auth). Browsers consume them as an
MJPEG stream or single snapshot. Since <img> tags cannot send Authorization
headers, viewer endpoints accept the JWT as a query parameter.
"""

import asyncio
import os
import threading
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from backend.auth.guards import verify_internal_key, verify_viewer_token

router = APIRouter(prefix="/stream", tags=["stream"])

FRAME_STALE_SECONDS = 15.0
_frames: dict = {}  # camera_id -> (jpeg_bytes, monotonic_ts)
_lock = threading.Lock()


def _verify_internal_key(key: Optional[str]) -> None:
    verify_internal_key(key)


def _verify_viewer_token(token: Optional[str]) -> None:
    verify_viewer_token(token)


@router.post("/frame/{camera_id}")
async def push_frame(
    camera_id: str,
    request: Request,
    x_internal_key: Optional[str] = Header(default=None, alias="X-Internal-Key"),
):
    """Pipeline pushes the latest annotated JPEG frame for a camera."""
    _verify_internal_key(x_internal_key)
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty frame")
    with _lock:
        _frames[camera_id] = (body, time.monotonic())
    return {"status": "ok", "camera_id": camera_id, "bytes": len(body)}


@router.get("/cameras")
def streaming_cameras(token: Optional[str] = Query(default=None)):
    """Camera ids that pushed a frame recently (i.e. have live video)."""
    _verify_viewer_token(token)
    now = time.monotonic()
    with _lock:
        return {
            "cameras": [
                cam for cam, (_, ts) in _frames.items()
                if now - ts < FRAME_STALE_SECONDS
            ]
        }


def _frame_with_digital_ptz(camera_id: str, jpeg_bytes: bytes) -> bytes:
    """Apply digital PTZ crop/zoom to a JPEG buffer when zoom/pan active."""
    try:
        from backend.services.ptz import get_state, apply_digital_crop
        st = get_state(camera_id)
        if st.mode != "digital" or (st.zoom <= 1.01 and abs(st.pan) < 0.01 and abs(st.tilt) < 0.01):
            return jpeg_bytes
        import cv2
        import numpy as np
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return jpeg_bytes
        out = apply_digital_crop(img, camera_id)
        ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else jpeg_bytes
    except Exception:
        return jpeg_bytes


@router.get("/{camera_id}/snapshot")
def snapshot(camera_id: str, token: Optional[str] = Query(default=None)):
    _verify_viewer_token(token)
    with _lock:
        entry = _frames.get(camera_id)
    if not entry or time.monotonic() - entry[1] > FRAME_STALE_SECONDS:
        raise HTTPException(status_code=404, detail="No live frame for this camera")
    data = _frame_with_digital_ptz(camera_id, entry[0])
    return Response(content=data, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@router.get("/{camera_id}/live")
async def live_mjpeg(camera_id: str, token: Optional[str] = Query(default=None)):
    """MJPEG stream (multipart/x-mixed-replace) of the latest pipeline frames."""
    _verify_viewer_token(token)

    async def generate():
        last_ts = 0.0
        misses = 0
        while True:
            with _lock:
                entry = _frames.get(camera_id)
            if entry and entry[1] != last_ts:
                raw, last_ts = entry
                frame = _frame_with_digital_ptz(camera_id, raw)
                misses = 0
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame)}\r\n\r\n".encode()
                    + frame + b"\r\n"
                )
            else:
                misses += 1
                if misses > 300:  # ~30s without a new frame → end stream
                    break
            await asyncio.sleep(0.1)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )

