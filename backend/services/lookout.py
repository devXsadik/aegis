"""Which lookouts are active on a camera right now (used by the matchers)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.models.bolo import Bolo, BoloCamera
from clock import utcnow


def active_for_camera(db: Session, camera_id: str, at: Optional[datetime] = None, kind: Optional[str] = None) -> List[Bolo]:
    at = at or utcnow()
    q = (db.query(Bolo).join(BoloCamera, BoloCamera.bolo_id == Bolo.id)
         .filter(BoloCamera.camera_id == camera_id, Bolo.status == "active",
                 Bolo.window_start <= at, Bolo.window_end >= at))
    if kind:
        q = q.filter(Bolo.kind == kind)
    return q.distinct().all()


def covers(bolos: List[Bolo], target_ref: Optional[str]) -> Optional[Bolo]:
    """A lookout for this exact target, or a general one (no target: e.g. 'white Axio in Gulshan')."""
    for b in bolos:
        if b.target_ref and b.target_ref == target_ref:
            return b
    for b in bolos:
        if not b.target_ref:
            return b
    return None
