"""Lookouts (BOLO). Manual ones come from Vehicle Search ("Start lookout" on an area or a set of
cameras, for a few hours); automatic ones from cross-camera tracking (Phase 9). While a lookout
is active its cameras get higher processing priority and attribute-only matches may alert."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.auth import operator_or_admin
from backend.db.database import get_db
from backend.models.bolo import Bolo, BoloCamera
from backend.models.camera import Camera
from backend.models.user import User
from backend.models.watchlist import WatchlistVehicle
from backend.services.audit import log_audit
from clock import utcnow

router = APIRouter(prefix="/lookouts", tags=["lookouts"])
LOOKOUT_ROLES = ("operator", "investigator", "supervisor", "admin")
BOOST_PRIORITY, BOOST_FPS = 5, 10.0


class LookoutIn(BaseModel):
    kind: str = Field(default="vehicle", pattern="^(vehicle|person)$")
    target_ref: Optional[str] = Field(default=None, max_length=40)
    plate: Optional[str] = Field(default=None, max_length=60)
    vehicle_type: Optional[str] = None
    color_primary: Optional[str] = None
    color_secondary: Optional[str] = None
    make_model: Optional[str] = None
    camera_ids: List[str] = Field(default_factory=list, max_length=500)
    jurisdiction_id: Optional[int] = None
    hours: float = Field(default=4, gt=0, le=72)
    reason: str = Field(min_length=5, max_length=500)
    case_no: Optional[str] = Field(default=None, max_length=60)
    incident_id: Optional[int] = None


def bolo_out(b: Bolo) -> dict:
    return {"ref": b.ref, "kind": b.kind, "target_ref": b.target_ref, "payload": json.loads(b.payload or "{}"),
            "origin": b.origin, "origin_camera": b.origin_camera, "direction": b.direction, "ring": b.ring,
            "status": b.status, "reason": b.reason, "case_no": b.case_no, "incident_id": b.incident_id,
            "window_start": b.window_start, "window_end": b.window_end, "found_camera": b.found_camera,
            "found_at": b.found_at,
            "cameras": [{"camera_id": c.camera_id, "rank": c.rank, "ring": c.ring, "eta_from_s": c.eta_from_s,
                         "eta_to_s": c.eta_to_s, "distance_m": c.distance_m} for c in sorted(b.cameras, key=lambda c: c.rank)]}


def boost(db: Session, camera_ids, on: bool) -> None:
    """Lookout cameras: more frames analysed and first in the queue; back to normal when no lookout needs them."""
    for cam in db.query(Camera).filter(Camera.camera_id.in_(list(camera_ids))):
        if on:
            cam.priority = max(cam.priority or 0, BOOST_PRIORITY)
        else:
            still = (db.query(BoloCamera).join(Bolo).filter(BoloCamera.camera_id == cam.camera_id,
                                                           Bolo.status == "active").count())
            if not still:
                cam.priority = 0


@router.get("")
def list_lookouts(status: Optional[str] = "active", db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    q = db.query(Bolo)
    if status:
        q = q.filter(Bolo.status == status)
    now = utcnow()
    out = []
    for b in q.order_by(Bolo.id.desc()).limit(200):
        if b.status == "active" and b.window_end.replace(tzinfo=None) < now:
            b.status = "expired"
            boost(db, [c.camera_id for c in b.cameras], False)
        out.append(bolo_out(b))
    db.commit()
    return [o for o in out if not status or o["status"] == status]


@router.post("", status_code=201)
def create_lookout(body: LookoutIn, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if user.role not in LOOKOUT_ROLES:
        raise HTTPException(403, "Your role cannot start a lookout")
    cams = set(body.camera_ids)
    if body.jurisdiction_id:
        from backend.services.jurisdiction import _all, ancestors, locate
        by_id = _all(db)
        inside = {j for j in by_id if body.jurisdiction_id in ancestors(j, by_id)}
        for c in db.query(Camera):
            jid = c.jurisdiction_id
            if jid is None:
                found = locate(db, c.lat, c.lng, by_id)
                jid = found.id if found else None
            if jid in inside:
                cams.add(c.camera_id)
    known = {c for (c,) in db.query(Camera.camera_id).filter(Camera.camera_id.in_(list(cams)))} if cams else set()
    if not known:
        raise HTTPException(400, "Choose an area or cameras: the lookout needs at least one camera")
    payload = {k: v for k, v in body.model_dump(include={"plate", "vehicle_type", "color_primary", "color_secondary",
                                                          "make_model"}).items() if v}
    if body.target_ref:
        if body.kind == "vehicle" and not db.query(WatchlistVehicle).filter(WatchlistVehicle.ref == body.target_ref).first():
            raise HTTPException(400, "target_ref is not a watchlist vehicle")
    elif not (payload.get("plate") or (payload.get("vehicle_type") and payload.get("color_primary"))):
        raise HTTPException(400, "Describe the target: a plate, or at least type and colour")
    now = utcnow()
    b = Bolo(ref=f"B-{uuid.uuid4().hex[:8].upper()}", kind=body.kind, target_ref=body.target_ref,
             payload=json.dumps(payload, ensure_ascii=False), origin="manual", reason=body.reason, case_no=body.case_no,
             incident_id=body.incident_id, created_by=user.id, window_start=now, window_end=now + timedelta(hours=body.hours),
             status="active")
    for i, cid in enumerate(sorted(known)):
        b.cameras.append(BoloCamera(camera_id=cid, rank=i, ring=1))
    db.add(b)
    boost(db, known, True)
    db.flush()
    log_audit(db, user, "LOOKOUT_START", "bolo", b.ref, json.dumps({"reason": body.reason, "cameras": len(known),
                                                                     "hours": body.hours, **payload}, ensure_ascii=False), request)
    db.commit()
    return bolo_out(b)


@router.post("/{ref}/cancel")
def cancel_lookout(ref: str, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if user.role not in LOOKOUT_ROLES:
        raise HTTPException(403, "Your role cannot cancel a lookout")
    b = db.query(Bolo).filter(Bolo.ref == ref).first()
    if not b:
        raise HTTPException(404, "Lookout not found")
    if b.status != "active":
        raise HTTPException(409, f"Lookout is {b.status}")
    b.status = "cancelled"
    db.flush()
    boost(db, [c.camera_id for c in b.cameras], False)
    log_audit(db, user, "LOOKOUT_CANCEL", "bolo", ref, "", request)
    db.commit()
    return bolo_out(b)
