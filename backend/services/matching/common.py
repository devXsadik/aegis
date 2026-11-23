"""Helpers shared by the matchers."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.camera import Camera
from backend.models.config_entry import ConfigEntry


def dispatch_sync(**kw) -> dict:
    """Run the async alert dispatcher from a worker thread (API threadpool) or a plain script."""
    from backend.services.alert_dispatcher import dispatch_alert
    try:
        import anyio.from_thread
        return anyio.from_thread.run(lambda: dispatch_alert(**kw))
    except RuntimeError:                       # not inside an AnyIO worker thread
        return asyncio.run(dispatch_alert(**kw))


def camera(db: Session, camera_id: str) -> Optional[Camera]:
    return db.query(Camera).filter(Camera.camera_id == camera_id).first()


def load_json_config(db: Session, key: str) -> dict:
    row = db.query(ConfigEntry).filter(ConfigEntry.key == key).first()
    if not row or not row.value:
        return {}
    try:
        v = json.loads(row.value)
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def save_json_config(db: Session, key: str, value: dict, user_id: Optional[int]) -> None:
    row = db.query(ConfigEntry).filter(ConfigEntry.key == key).first()
    if not row:
        row = ConfigEntry(key=key)
        db.add(row)
    row.value = json.dumps(value)
    row.updated_by = user_id
