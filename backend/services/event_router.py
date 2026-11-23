"""Where every normalized event goes: store it (with a retention date), then hand it to the
matchers (vehicle watchlist, face watchlist, lookouts). One process: handled inline. With
INGEST_ASYNC=true and a Redis bus: published to the `detections` stream for `scripts/worker.py`.

Handlers are registered by the matching modules: `register("vehicle", fn)`; each gets
(db, NormalizedEvent, Detection) and returns a list of result dicts (alerts raised, matches)."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Callable, Dict, List

from sqlalchemy.orm import Session

from backend.models.camera import Camera
from backend.models.detection import Detection
from backend.utils.at_rest import seal
from clock import utcnow
from core.ingest.events import NormalizedEvent

logger = logging.getLogger("HumanAnalysis")

_HANDLERS: Dict[str, List[Callable]] = {"face": [], "vehicle": [], "person": []}
_HEARTBEAT_EVERY = timedelta(seconds=30)


def register(kind: str, fn: Callable) -> None:
    if fn not in _HANDLERS[kind]:
        _HANDLERS[kind].append(fn)


def unregister(kind: str, fn: Callable) -> None:
    if fn in _HANDLERS[kind]:
        _HANDLERS[kind].remove(fn)


def retention_days() -> int:
    try:
        return max(1, int(os.getenv("DETECTION_RETENTION_DAYS", "30")))
    except ValueError:
        return 30


def _crop_bytes(b64: str):
    if not b64:
        return None
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    try:
        return base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        return None


def store(db: Session, ev: NormalizedEvent) -> Detection:
    from core.analysis.bd_plate import canonical
    existing = db.query(Detection).filter(Detection.event_id == ev.event_id).first()
    if existing:                     # a camera re-sending the same event
        return existing
    crop = _crop_bytes(ev.crop_image) if ev.type != "face" else None   # face crops: kept only if matched
    blob, enc = seal(crop) if crop else (None, False)
    ts = datetime.fromisoformat(ev.timestamp)
    det = Detection(
        event_id=ev.event_id, camera_id=ev.camera_id, ts=ts, kind=ev.type, source=ev.source,
        track_id=str(ev.track_id) if ev.track_id is not None else None,
        bbox=json.dumps(ev.bbox) if ev.bbox else None, crop=blob, crop_encrypted=enc,
        full_frame_ref=ev.full_frame_ref, plate_raw=ev.plate_text,
        plate_canonical=canonical(ev.plate_text) if ev.plate_text else None, plate_confidence=ev.plate_confidence,
        vehicle_type=ev.vehicle_type, color=ev.color, color_secondary=ev.color_secondary, make_model=ev.make_model,
        attr_conf=json.dumps(ev.attribute_confidences) if ev.attribute_confidences else None,
        color_reliable=not bool(ev.is_night), direction=ev.direction,
        embedding=base64.b64decode(ev.embedding) if ev.embedding and ev.type == "vehicle" else None,
        embedding_model=ev.embedding_model if ev.type == "vehicle" else None,
        expires_at=ts + timedelta(days=retention_days()),
    )
    db.add(det)
    db.flush()
    return det


def touch_camera(db: Session, camera_id: str) -> None:
    cam = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not cam:
        return
    now = utcnow()
    last = cam.last_heartbeat.replace(tzinfo=None) if cam.last_heartbeat and cam.last_heartbeat.tzinfo else cam.last_heartbeat
    if not last or now - last > _HEARTBEAT_EVERY:
        cam.last_heartbeat = now
        if cam.status in ("offline", "unknown"):
            cam.status = "online"


def handle(db: Session, ev: NormalizedEvent) -> dict:
    det = store(db, ev)
    results = []
    for fn in _HANDLERS.get(ev.type, []):
        try:
            results += fn(db, ev, det) or []
        except Exception as e:     # one broken matcher must not drop the event for the others
            logger.exception("Matcher %s failed on %s: %s", getattr(fn, "__name__", fn), ev.event_id, e)
    touch_camera(db, ev.camera_id)
    return {"event_id": ev.event_id, "detection_id": det.id, "results": results}


def use_bus() -> bool:
    return os.getenv("INGEST_ASYNC", "").lower() in ("1", "true", "yes")


def submit(db: Session, events: List[NormalizedEvent]) -> List[dict]:
    if use_bus():
        from core.bus import get_bus
        bus = get_bus()
        out = []
        for ev in events:
            bus.publish("detections", ev.to_dict())
            out.append({"event_id": ev.event_id, "queued": True})
        for cid in {e.camera_id for e in events}:
            touch_camera(db, cid)
        db.commit()
        return out
    out = [handle(db, ev) for ev in events]
    db.commit()
    return out


def purge_expired(db: Session, now=None) -> int:
    """Non-matched detections past retention go; matched ones or those on an incident stay."""
    now = now or utcnow()
    n = (db.query(Detection)
         .filter(Detection.expires_at <= now, Detection.incident_id.is_(None), Detection.matched == False)  # noqa: E712
         .delete(synchronize_session=False))
    return n
