"""Event ingestion from AI cameras / gateways / the simulator.

    POST /api/v1/ingest/{vendor}/{camera_id}      body: the vendor's event JSON
        X-Camera-Token: <per-camera token>  (from POST /cameras/{id}/ingest-token, admin)
     or X-Internal-Key: <INTERNAL_API_KEY>  (our pipeline, the simulator)

The adapter turns it into NormalizedEvent(s); the event router stores and matches them inline,
or queues them on the bus (INGEST_ASYNC=true) for scripts/worker.py."""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend.db.database import get_db
from backend.models.camera import Camera
from backend.services import event_router
from core.ingest.adapters import ADAPTERS, normalize
from core.ingest.events import EventError

router = APIRouter(prefix="/ingest", tags=["ingest"])

MAX_BODY = 4 * 1024 * 1024


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _authorized(cam: Camera, camera_token: Optional[str], internal_key: Optional[str]) -> bool:
    import os
    expected = os.getenv("INTERNAL_API_KEY", "")
    if internal_key and expected and hmac.compare_digest(internal_key.encode(), expected.encode()):
        return True
    if camera_token and cam.ingest_token_hash:
        return hmac.compare_digest(token_hash(camera_token), cam.ingest_token_hash)
    return False


@router.get("/vendors")
def vendors():
    return {"vendors": sorted(ADAPTERS)}


@router.post("/{vendor}/{camera_id}")
async def ingest(vendor: str, camera_id: str, request: Request, db: Session = Depends(get_db),
                 x_camera_token: Optional[str] = Header(default=None, alias="X-Camera-Token"),
                 x_internal_key: Optional[str] = Header(default=None, alias="X-Internal-Key")):
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(413, "Event too large: send full frames to storage and pass full_frame_ref")
    try:
        import json
        payload = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(400, "Body must be JSON")

    def work():
        cam = db.query(Camera).filter(Camera.camera_id == camera_id).first()
        # Same answer for unknown camera and wrong token: don't reveal which camera ids exist.
        if not cam or not _authorized(cam, x_camera_token, x_internal_key):
            raise HTTPException(401, "Unknown camera or bad token")
        if not cam.active:
            raise HTTPException(409, "Camera is paused")
        try:
            events = normalize(vendor, payload, camera_id)
        except EventError as e:
            raise HTTPException(422, str(e))
        return event_router.submit(db, events)

    results = await run_in_threadpool(work)
    return {"accepted": len(results), "results": results}
