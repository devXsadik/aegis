"""Shift log: notes during a shift, a summary of the shift so far, and the handover.

A shift runs from the last accepted-or-not handover (or the last 12 hours) to now. Handing
over stores the summary as it stood, with the outgoing operator's notes; the next operator
accepts it, so nothing open is lost between shifts.
"""

import json
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from backend.auth.auth import operator_or_admin
from backend.db.database import get_db
from backend.models.alert import Alert
from backend.models.camera import Camera
from backend.models.incident import Incident
from backend.models.shift import ShiftEntry
from backend.models.user import User
from backend.services.audit import log_audit
from clock import utcnow

router = APIRouter(prefix="/shift", tags=["shift"])

DEFAULT_SHIFT_HOURS = 12
CLOSED_INCIDENTS = ("resolved", "closed")


class NoteBody(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    camera_id: Optional[str] = Field(default=None, max_length=50)


class HandoverBody(BaseModel):
    notes: str = Field(default="", max_length=2000)


def _iso(dt):
    return dt.isoformat() if dt else None


def _entry(e: ShiftEntry) -> dict:
    return {
        "id": e.id, "timestamp": _iso(e.timestamp), "username": e.username, "kind": e.kind,
        "camera_id": e.camera_id, "text": e.text,
        "summary": json.loads(e.summary) if e.summary else None,
        "accepted_by": e.accepted_by, "accepted_at": _iso(e.accepted_at),
    }


def _shift_start(db: Session):
    last = db.query(ShiftEntry).filter(ShiftEntry.kind == "handover").order_by(desc(ShiftEntry.timestamp)).first()
    floor = utcnow() - timedelta(hours=DEFAULT_SHIFT_HOURS)
    if last and last.timestamp and last.timestamp.replace(tzinfo=None) > floor:
        return last.timestamp.replace(tzinfo=None)
    return floor


def _cameras_not_reporting(db: Session) -> list:
    from backend.api.system_routes import _pipeline_status
    from backend.services.ha import camera_offline_sla

    beats = _pipeline_status.get("cameras", {})
    out = []
    for cam in db.query(Camera).filter(Camera.active == True).all():  # noqa: E712
        if camera_offline_sla(beats.get(cam.camera_id, {}).get("last_seen")) != "ok":
            out.append(cam.name or cam.camera_id)
    return out


def shift_summary(db: Session) -> dict:
    since = _shift_start(db)
    in_shift = Alert.timestamp >= since
    handled = or_(Alert.acknowledged_at >= since, Alert.reviewed_at >= since)
    return {
        "since": since.isoformat(),
        "alerts_raised": db.query(Alert).filter(in_shift).count(),
        "alerts_handled": db.query(Alert).filter(handled).count(),
        "alerts_waiting": db.query(Alert).filter(Alert.review_status == "pending", Alert.dismissed == False).count(),  # noqa: E712
        "critical_waiting": db.query(Alert).filter(
            Alert.severity == "critical", Alert.acknowledged == False, Alert.dismissed == False).count(),  # noqa: E712
        "tamper_alerts": db.query(Alert).filter(in_shift, Alert.alert_type == "CAMERA_TAMPER").count(),
        "incidents_opened": db.query(Incident).filter(Incident.created_at >= since).count(),
        "incidents_open": db.query(Incident).filter(~Incident.status.in_(CLOSED_INCIDENTS)).count(),
        "cameras_not_reporting": _cameras_not_reporting(db),
        "notes": db.query(ShiftEntry).filter(ShiftEntry.kind == "note", ShiftEntry.timestamp >= since).count(),
    }


@router.get("/log")
def shift_log(hours: int = 48, limit: int = 200, db: Session = Depends(get_db),
              user: User = Depends(operator_or_admin)):
    since = utcnow() - timedelta(hours=min(max(hours, 1), 24 * 31))
    rows = (db.query(ShiftEntry).filter(ShiftEntry.timestamp >= since)
            .order_by(desc(ShiftEntry.timestamp)).limit(min(limit, 500)).all())
    return [_entry(e) for e in rows]


@router.post("/notes")
def add_note(body: NoteBody, request: Request, db: Session = Depends(get_db),
             user: User = Depends(operator_or_admin)):
    e = ShiftEntry(user_id=user.id, username=user.username, kind="note",
                   camera_id=body.camera_id or None, text=body.text.strip(), timestamp=utcnow())
    db.add(e)
    log_audit(db, user, "SHIFT_NOTE", "shift", "", body.text[:120], request)
    db.commit()
    db.refresh(e)
    return _entry(e)


@router.get("/summary")
def get_summary(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    return shift_summary(db)


@router.get("/pending")
def pending_handover(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """The newest handover nobody has accepted yet (shown on Home), or null."""
    e = (db.query(ShiftEntry).filter(ShiftEntry.kind == "handover", ShiftEntry.accepted_at.is_(None))
         .order_by(desc(ShiftEntry.timestamp)).first())
    return _entry(e) if e else None


@router.post("/handover")
def hand_over(body: HandoverBody, request: Request, db: Session = Depends(get_db),
              user: User = Depends(operator_or_admin)):
    summary = shift_summary(db)
    e = ShiftEntry(user_id=user.id, username=user.username, kind="handover", text=body.notes.strip(),
                   summary=json.dumps(summary), timestamp=utcnow())
    db.add(e)
    log_audit(db, user, "SHIFT_HANDOVER", "shift", "", f"{summary['alerts_waiting']} alerts waiting", request)
    db.commit()
    db.refresh(e)
    return _entry(e)


@router.post("/handover/{entry_id}/accept")
def accept_handover(entry_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(operator_or_admin)):
    e = db.query(ShiftEntry).filter(ShiftEntry.id == entry_id, ShiftEntry.kind == "handover").first()
    if not e:
        raise HTTPException(404, "Handover not found")
    if e.accepted_at:
        raise HTTPException(409, f"Already accepted by {e.accepted_by}")
    if e.user_id == user.id:
        raise HTTPException(400, "The next operator accepts a handover, not the one who wrote it")
    e.accepted_by, e.accepted_at = user.username, utcnow()
    log_audit(db, user, "SHIFT_ACCEPT", "shift", str(entry_id), f"from {e.username}", request)
    db.commit()
    return _entry(e)
