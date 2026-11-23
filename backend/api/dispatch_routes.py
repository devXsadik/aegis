"""Dispatch ↔ field: a message thread per incident (with photos from the field) and the duty roster.

Messages: anyone who can see the incident and is operational may write. A message from the command
centre wakes the assigned officers' phones; one from an officer goes to the dashboards and the case
owner. Every message is also an incident timeline event (MESSAGE), so it is in the case record.
Roster: supervisors and admins plan shifts; officers on shift now come first in the officer picker.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from backend.auth.auth import ROLES_COMMAND, get_current_user, operator_or_admin
from backend.db.database import get_db
from backend.models.dispatch import IncidentMessage, OfficerShift
from backend.models.incident import IncidentAssignment
from backend.models.jurisdiction import Jurisdiction, OfficerJurisdiction, OfficerProfile
from backend.models.user import User
from backend.services.audit import log_audit
from backend.services.incident_service import add_event
from backend.utils.websocket import manager
from clock import utcnow

router = APIRouter(tags=["dispatch"])
WRITE_ROLES = {"admin", "supervisor", "operator", "police", "investigator"}
FIELD_ROLES = {"police"}


class MessageIn(BaseModel):
    body: str = Field(default="", max_length=2000)
    evidence_ref: Optional[str] = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _something(self):
        if not self.body.strip() and not self.evidence_ref:
            raise ValueError("Write a message or attach a photo")
        return self


def _msg(m: IncidentMessage) -> dict:
    return {"id": m.id, "incident_id": m.incident_id, "author_id": m.author_id, "author_name": m.author_name,
            "author_role": m.author_role, "from_field": m.author_role in FIELD_ROLES, "body": m.body,
            "evidence_ref": m.evidence_ref, "created_at": m.created_at.isoformat() if m.created_at else utcnow().isoformat()}


def _incident(db: Session, incident_id: int, user: User):
    from backend.api.incident_routes import _load          # same visibility rules as the incident itself
    return _load(db, incident_id, user)


@router.get("/incidents/{incident_id}/messages")
def list_messages(incident_id: int, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    _incident(db, incident_id, user)
    rows = (db.query(IncidentMessage).filter(IncidentMessage.incident_id == incident_id)
            .order_by(IncidentMessage.created_at, IncidentMessage.id).all())
    return [_msg(m) for m in rows]


@router.post("/incidents/{incident_id}/messages", status_code=201)
def post_message(incident_id: int, body: MessageIn, request: Request, background: BackgroundTasks,
                 db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if user.role not in WRITE_ROLES:
        raise HTTPException(403, "Your role cannot send messages")
    inc = _incident(db, incident_id, user)
    if body.evidence_ref:
        from backend.models.case_evidence import EvidenceItem
        item = db.query(EvidenceItem).filter(EvidenceItem.ref == body.evidence_ref).first()
        if not item or item.incident_id != inc.id:
            raise HTTPException(400, "That photo is not part of this incident's evidence")
    prof = db.get(OfficerProfile, user.id)
    name = prof.full_name if prof and prof.full_name else user.username
    m = IncidentMessage(incident_id=inc.id, author_id=user.id, author_name=name, author_role=user.role,
                        body=body.body.strip(), evidence_ref=body.evidence_ref)
    db.add(m)
    db.flush()
    preview = (body.body.strip() or "Photo")[:140]
    add_event(db, inc, "MESSAGE", f"{name}: {preview}", user.username, actor_id=user.id,
              payload={"message_id": m.id, "evidence_ref": body.evidence_ref})
    from backend.services import notify
    if user.role in FIELD_ROLES:
        # From the field: the case owner gets a notification; every dashboard sees it live.
        if inc.assigned_to and inc.assigned_to != user.id:
            notify.notify(db, [inc.assigned_to], kind="message", priority="low", incident_id=inc.id,
                          title=f"{inc.ticket_id}: message from {name}", body=preview)
    else:
        officers = [a.user_id for a in db.query(IncidentAssignment).filter(IncidentAssignment.incident_id == inc.id)
                    if a.user_id != user.id]
        notify.notify(db, officers, kind="message", priority="low", incident_id=inc.id,
                      title=f"{inc.ticket_id}: message from dispatch", body=preview)
        notify.wake(officers)
    db.commit()
    db.refresh(m)
    out = _msg(m)
    # Ids only: everyone on the incidents channel gets this; the text is fetched through the API,
    # which applies the incident's visibility rules.
    background.add_task(manager.broadcast, {"event_type": "INCIDENT_MESSAGE", "incident_id": inc.id,
                                            "ticket_id": inc.ticket_id, "message_id": m.id,
                                            "from_field": out["from_field"], "timestamp": utcnow().isoformat()}, "incidents")
    return out


# ——— roster ———

class ShiftIn(BaseModel):
    user_id: int
    starts_at: datetime
    ends_at: datetime
    jurisdiction_id: Optional[int] = None
    assignment: Optional[str] = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _order(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("The shift must end after it starts")
        if self.ends_at - self.starts_at > timedelta(hours=24):
            raise ValueError("A shift is at most 24 hours")
        return self


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _shift(s: OfficerShift, names: dict, areas: dict) -> dict:
    now = datetime.now(timezone.utc)
    st, en = _utc(s.starts_at), _utc(s.ends_at)
    return {"id": s.id, "user_id": s.user_id, "officer": names.get(s.user_id), "starts_at": st.isoformat(),
            "ends_at": en.isoformat(), "jurisdiction_id": s.jurisdiction_id, "area": areas.get(s.jurisdiction_id),
            "assignment": s.assignment, "now": st <= now < en}


def _roster_reader(user: User = Depends(get_current_user)) -> User:
    if user.role not in {"admin", "supervisor", "operator", "police"}:
        raise HTTPException(403, "Roster is for the command centre and officers")
    return user


def _command(user: User = Depends(get_current_user)) -> User:
    if user.role not in ROLES_COMMAND:
        raise HTTPException(403, "Supervisor or admin access required")
    return user


def on_shift_now(db: Session, user_ids) -> set:
    now = utcnow()
    ids = list(user_ids)
    if not ids:
        return set()
    return {u for (u,) in db.query(OfficerShift.user_id).filter(
        OfficerShift.user_id.in_(ids), OfficerShift.starts_at <= now, OfficerShift.ends_at > now)}


@router.get("/roster")
def roster(start: Optional[datetime] = None, days: int = Query(7, ge=1, le=31), jurisdiction_id: Optional[int] = None,
           db: Session = Depends(get_db), user: User = Depends(_roster_reader)):
    from backend.services import scope
    start = _utc(start) if start else utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    q = db.query(OfficerShift).filter(OfficerShift.ends_at > start, OfficerShift.starts_at < end)
    if user.role == "police":
        q = q.filter(OfficerShift.user_id == user.id)            # officers see their own shifts
    else:
        areas = scope.narrow(db, user, {jurisdiction_id} if jurisdiction_id else None)
        if areas is not None:
            q = q.filter(OfficerShift.jurisdiction_id.in_(sorted(areas)))
    rows = q.order_by(OfficerShift.starts_at).all()
    uids = {s.user_id for s in rows}
    profs = {p.user_id: p for p in db.query(OfficerProfile).filter(OfficerProfile.user_id.in_(uids))} if uids else {}
    names = {u.id: (profs[u.id].full_name if u.id in profs and profs[u.id].full_name else u.username)
             for u in db.query(User).filter(User.id.in_(uids))} if uids else {}
    areas = {j.id: j.name_en for j in db.query(Jurisdiction.id, Jurisdiction.name_en)}
    return {"start": start.isoformat(), "days": days, "shifts": [_shift(s, names, areas) for s in rows]}


@router.post("/roster", status_code=201)
def add_shift(body: ShiftIn, request: Request, db: Session = Depends(get_db), user: User = Depends(_command)):
    from backend.services import scope
    from backend.services.jurisdiction import OFFICER_ROLES
    officer = db.get(User, body.user_id)
    if not officer or officer.role not in OFFICER_ROLES or not officer.is_active:
        raise HTTPException(400, "Pick an active field officer or supervisor")
    area = body.jurisdiction_id
    if area is None:                                       # default: the officer's first area
        link = db.query(OfficerJurisdiction).filter(OfficerJurisdiction.user_id == officer.id).first()
        area = link.jurisdiction_id if link else None
    if area is not None and not db.get(Jurisdiction, area):
        raise HTTPException(400, "Unknown area")
    if not scope.within(db, user, area):
        raise HTTPException(403, "That area is outside your district")
    st, en = _utc(body.starts_at), _utc(body.ends_at)
    clash = db.query(OfficerShift).filter(OfficerShift.user_id == officer.id, OfficerShift.starts_at < en,
                                          OfficerShift.ends_at > st).first()
    if clash:
        raise HTTPException(409, "This officer already has a shift at that time")
    s = OfficerShift(user_id=officer.id, starts_at=st, ends_at=en, jurisdiction_id=area,
                     assignment=(body.assignment or "").strip() or None, created_by=user.id)
    db.add(s)
    db.flush()
    log_audit(db, user, "ROSTER_ADD", "officer_shift", str(s.id), f"{officer.username} {st:%Y-%m-%d %H:%M}–{en:%H:%M}", request)
    db.commit()
    return {"id": s.id}


@router.delete("/roster/{shift_id}")
def remove_shift(shift_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(_command)):
    from backend.services import scope
    s = db.get(OfficerShift, shift_id)
    if not s or not scope.within(db, user, s.jurisdiction_id):
        raise HTTPException(404, "Shift not found")
    log_audit(db, user, "ROSTER_REMOVE", "officer_shift", str(s.id), f"user {s.user_id}", request)
    db.delete(s)
    db.commit()
    return {"ok": True}


def shift_officers(db: Session) -> List[dict]:
    """Field officers / supervisors a roster can be made for (id, name), for the roster form."""
    from backend.services.jurisdiction import OFFICER_ROLES
    users = db.query(User).filter(User.is_active == True, User.role.in_(OFFICER_ROLES)).order_by(User.username).all()  # noqa: E712
    profs = {p.user_id: p for p in db.query(OfficerProfile)}
    return [{"id": u.id, "name": profs[u.id].full_name if u.id in profs and profs[u.id].full_name else u.username,
             "rank": profs[u.id].rank if u.id in profs else None} for u in users]


@router.get("/roster/officers")
def roster_officers(db: Session = Depends(get_db), user: User = Depends(_command)):
    from backend.services import scope
    officers = shift_officers(db)
    areas = scope.area_ids(db, user)
    if areas is None:
        return officers
    links = {}
    for lk in db.query(OfficerJurisdiction):
        links.setdefault(lk.user_id, set()).add(lk.jurisdiction_id)
    return [o for o in officers if links.get(o["id"], set()) & areas]
