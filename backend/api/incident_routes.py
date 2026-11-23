"""Incident Management API — tickets with a status state machine, jurisdiction-checked officer
assignment, typed timeline, filters, and live updates on /ws/incidents.

Every rule here is enforced server-side; the dashboard only mirrors it."""

import json
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import asc, desc, or_, case
from sqlalchemy.orm import Session, joinedload

from backend.db.database import get_db
from backend.models.user import User
from backend.models.incident import ASSIGNMENT_STATES, Incident, IncidentAssignment, IncidentNote
from backend.models.alert import Alert
from backend.models.capture import AlertCapture
from backend.models.jurisdiction import OfficerProfile
from backend.auth.auth import operator_or_admin, ROLES_COMMAND
from backend.services.incident_service import create_incident_from_alert, add_event, _next_ticket_id
from backend.services import incident_status as fsm
from backend.services import jurisdiction as jsvc
from backend.services.audit import log_audit
from backend.utils.websocket import manager
from clock import utcnow

router = APIRouter(prefix="/incidents", tags=["incidents"])

VALID_PRIORITY = {"critical", "high", "medium", "low"}
VALID_SOURCE = {"face_match", "vehicle_match", "manual", "alert"}
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ——— Schemas ———

class NoteOut(BaseModel):
    id: int
    author_name: Optional[str]
    body: str
    created_at: datetime

    class Config:
        from_attributes = True


class EventOut(BaseModel):
    id: int
    event_type: str
    message: str
    actor: Optional[str]
    actor_id: Optional[int] = None
    camera_id: Optional[str] = None
    payload: Optional[Any] = None
    created_at: datetime

    @field_validator("payload", mode="before")
    @classmethod
    def _json(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return None
        return v

    class Config:
        from_attributes = True


class AssignmentOut(BaseModel):
    user_id: int
    name: str
    rank: Optional[str] = None
    badge_no: Optional[str] = None
    has_photo: bool = False
    state: str
    out_of_area: bool = False
    assigned_at: Optional[datetime] = None


class IncidentOut(BaseModel):
    id: int
    ticket_id: str
    title: str
    description: Optional[str]
    incident_type: str
    source: Optional[str] = "alert"
    priority: str
    severity: Optional[str] = None
    status: str
    camera_id: Optional[str]
    camera_location: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    jurisdiction_id: Optional[int] = None
    alert_id: Optional[int]
    evidence_id: Optional[int]
    person_name: Optional[str]
    plate_number: Optional[str]
    watchlist_person_id: Optional[int] = None
    watchlist_vehicle_id: Optional[int] = None
    assigned_to: Optional[int]
    assigned_name: Optional[str]
    created_by_name: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    resolved_at: Optional[datetime]
    closed_at: Optional[datetime] = None
    snapshot: Optional[dict] = None
    trail: List[dict] = []
    assignments: List[AssignmentOut] = []
    notes: List[NoteOut] = []
    events: List[EventOut] = []


class IncidentPage(BaseModel):
    items: List[IncidentOut]
    total: int


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    incident_type: str = "MANUAL"
    priority: str = "medium"
    camera_id: Optional[str] = None
    camera_location: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    alert_id: Optional[int] = None
    evidence_id: Optional[int] = None
    person_name: Optional[str] = None
    plate_number: Optional[str] = None


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=2000)   # required for closed / false_alarm / re-open
    assigned_to: Optional[int] = None                           # case owner (any operational user)
    assigned_name: Optional[str] = None


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class AssignBody(BaseModel):
    user_ids: List[int] = Field(min_length=1, max_length=20)
    include_neighbours: bool = False
    reason: Optional[str] = Field(default=None, max_length=500)


class OfficerStateBody(BaseModel):
    state: str
    note: Optional[str] = Field(default=None, max_length=500)


# ——— Helpers ———

def _is_command(user: User) -> bool:
    return user.role in ROLES_COMMAND


def _scope(db: Session, q, user: User):
    """Police see incidents in their areas, on their cameras, or assigned to them. District users
    (scope_jurisdiction_id) see their district's incidents and those assigned to them. Others: all."""
    if user.role != "police":
        from backend.services import scope
        areas = scope.area_ids(db, user)
        if areas is None:
            return q
        mine = db.query(IncidentAssignment.incident_id).filter(IncidentAssignment.user_id == user.id)
        return q.filter(or_(Incident.jurisdiction_id.in_(sorted(areas)), Incident.assigned_to == user.id,
                            Incident.id.in_(mine)))
    areas = jsvc.officer_area_ids(db, user.id)
    cams = jsvc.officer_camera_ids(db, user.id)
    mine = db.query(IncidentAssignment.incident_id).filter(IncidentAssignment.user_id == user.id)
    conds = [Incident.assigned_to == user.id, Incident.id.in_(mine)]
    if areas:
        conds.append(Incident.jurisdiction_id.in_(sorted(areas)))
    if cams:
        conds.append(Incident.camera_id.in_(sorted(cams)))
    return q.filter(or_(*conds))


def _load(db: Session, incident_id: int, user: User) -> Incident:
    q = db.query(Incident).options(joinedload(Incident.notes), joinedload(Incident.events),
                                   joinedload(Incident.assignments)).filter(Incident.id == incident_id)
    inc = _scope(db, q, user).first()
    if not inc:
        raise HTTPException(404, "Incident not found")
    return inc


def _snapshots(db: Session, incs: List[Incident]) -> dict:
    alert_ids = [i.alert_id for i in incs if i.alert_id and not i.evidence_id]
    caps = {}
    if alert_ids:
        for cid, aid in (db.query(AlertCapture.id, AlertCapture.alert_id)
                         .filter(AlertCapture.alert_id.in_(alert_ids)).order_by(AlertCapture.id)):
            caps.setdefault(aid, cid)
    out = {}
    for i in incs:
        if i.evidence_id:
            out[i.id] = {"kind": "evidence", "id": i.evidence_id, "url": f"/api/v1/evidence/{i.evidence_id}/image"}
        elif i.alert_id in caps:
            out[i.id] = {"kind": "capture", "id": caps[i.alert_id], "url": f"/api/v1/captures/{caps[i.alert_id]}/image"}
    return out


def _serialize(db: Session, incs: List[Incident], full: bool = True) -> List[dict]:
    snaps = _snapshots(db, incs)
    uids = {a.user_id for i in incs for a in i.assignments}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(uids))} if uids else {}
    profs = {p.user_id: p for p in db.query(OfficerProfile).filter(OfficerProfile.user_id.in_(uids))} if uids else {}
    out = []
    for i in incs:
        d = IncidentOut.model_validate({
            **{c.name: getattr(i, c.name) for c in Incident.__table__.columns},
            "status": fsm.normalize(i.status), "severity": i.priority, "snapshot": snaps.get(i.id),
            "assignments": [{
                "user_id": a.user_id,
                "name": (profs[a.user_id].full_name if a.user_id in profs and profs[a.user_id].full_name
                         else users[a.user_id].username if a.user_id in users else str(a.user_id)),
                "rank": profs[a.user_id].rank if a.user_id in profs else None,
                "badge_no": profs[a.user_id].badge_no if a.user_id in profs else None,
                "has_photo": bool(a.user_id in profs and profs[a.user_id].photo),
                "state": a.state, "out_of_area": bool(a.out_of_area), "assigned_at": a.assigned_at,
            } for a in i.assignments],
            "notes": [NoteOut.model_validate(n) for n in i.notes] if full else [],
            "trail": _trail(db, i.id) if full else [],
            "events": [EventOut.model_validate(e) for e in i.events] if full else [],
        })
        out.append(d.model_dump(mode="json"))
    return out


def _trail(db: Session, incident_id: int) -> List[dict]:
    from backend.services.tracking import trail
    return trail(db, incident_id)


def _push(background: BackgroundTasks, inc: Incident, change: str, user: Optional[User] = None):
    background.add_task(manager.broadcast, {
        "event_type": "INCIDENT_UPDATED", "incident_id": inc.id, "ticket_id": inc.ticket_id,
        "status": fsm.normalize(inc.status), "change": change, "by": user.username if user else "SYSTEM",
        "timestamp": utcnow().isoformat(),
    }, "incidents")


# ——— Routes ———

@router.get("/statuses")
def statuses(user: User = Depends(operator_or_admin)):
    """The status machine (labels, colours, allowed transitions, which need a note)."""
    return fsm.spec()


@router.get("/", response_model=None)
def list_incidents(
    status: Optional[str] = Query(default=None, description="comma-separated"),
    priority: Optional[str] = Query(default=None, description="severity, comma-separated"),
    source: Optional[str] = None,
    incident_type: Optional[str] = None,
    camera_id: Optional[str] = None,
    jurisdiction_id: Optional[int] = None,
    officer_id: Optional[int] = None,
    q: Optional[str] = Query(default=None, max_length=100),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort: str = Query(default="-created_at", pattern="^-?(created_at|updated_at|severity|status|ticket_id)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    envelope: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    query = _scope(db, db.query(Incident), user)
    if status:
        wanted = {fsm.normalize(s.strip()) for s in status.split(",") if s.strip()}
        legacy = {k for k, v in fsm.LEGACY.items() if v in wanted}
        query = query.filter(Incident.status.in_(sorted(wanted | legacy)))
    if priority:
        query = query.filter(Incident.priority.in_([p.strip() for p in priority.split(",")]))
    if source:
        query = query.filter(Incident.source.in_([s.strip() for s in source.split(",")]))
    if incident_type:
        query = query.filter(Incident.incident_type == incident_type)
    if camera_id:
        query = query.filter(Incident.camera_id == camera_id)
    if jurisdiction_id:
        by_id = jsvc._all(db)
        inside = [j for j in by_id if jurisdiction_id in jsvc.ancestors(j, by_id)]
        query = query.filter(Incident.jurisdiction_id.in_(inside or [jurisdiction_id]))
    if officer_id:
        query = query.filter(or_(Incident.assigned_to == officer_id, Incident.id.in_(
            db.query(IncidentAssignment.incident_id).filter(IncidentAssignment.user_id == officer_id))))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Incident.ticket_id.ilike(like), Incident.title.ilike(like),
                                 Incident.camera_location.ilike(like), Incident.person_name.ilike(like),
                                 Incident.plate_number.ilike(like)))
    if date_from:
        query = query.filter(Incident.created_at >= date_from)
    if date_to:
        query = query.filter(Incident.created_at <= date_to)

    total = query.count()
    field = sort.lstrip("-")
    direction = desc if sort.startswith("-") else asc
    if field == "severity":
        col = case(SEVERITY_RANK, value=Incident.priority, else_=9)
        # "-severity" = most severe first, i.e. ascending rank
        order = asc(col) if sort.startswith("-") else desc(col)
    else:
        order = direction(getattr(Incident, field))
    rows = (query.options(joinedload(Incident.assignments)).order_by(order, desc(Incident.id))
            .offset(skip).limit(limit).all())
    items = _serialize(db, rows, full=False)
    if envelope:
        return {"items": items, "total": total}
    return items


@router.get("/stats")
def incident_stats(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    rows = _scope(db, db.query(Incident.status, Incident.priority), user).all()
    by_status, by_severity = {}, {}
    for st, pr in rows:
        st = fsm.normalize(st)
        by_status[st] = by_status.get(st, 0) + 1
        by_severity[pr] = by_severity.get(pr, 0) + 1
    open_n = sum(n for s, n in by_status.items() if s in fsm.OPEN_STATUSES)
    return {"total": len(rows), "open": open_n, "by_status": by_status, "by_severity": by_severity}


@router.get("/{incident_id}/package")
def evidence_package(incident_id: int, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(operator_or_admin)):
    """ZIP with the case, its stills (and custody chains), captures and recordings, plus a signed manifest."""
    from backend.services.evidence_package import build_package
    _load(db, incident_id, user)
    try:
        name, data = build_package(db, incident_id, user)
    except LookupError:
        raise HTTPException(404, "Incident not found")
    log_audit(db, user, "EVIDENCE_PACKAGE", "incident", str(incident_id), name, request)
    db.commit()
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/package/verify")
async def verify_evidence_package(file: UploadFile = File(...), user: User = Depends(operator_or_admin)):
    """Was this package exported by this system, and is every file in it unchanged?"""
    from backend.services.evidence_package import verify_package
    data = await file.read()
    if len(data) > 500 * 1024 * 1024:
        raise HTTPException(413, "Package too large to check here")
    return verify_package(data)


@router.get("/{incident_id}")
def get_incident(incident_id: int, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    return _serialize(db, [_load(db, incident_id, user)])[0]


@router.post("/")
def create_incident(body: IncidentCreate, background: BackgroundTasks, db: Session = Depends(get_db),
                    user: User = Depends(operator_or_admin)):
    if user.role == "viewer":
        raise HTTPException(403, "Read-only role")
    if body.alert_id:
        alert = db.query(Alert).filter(Alert.id == body.alert_id).first()
        if alert:
            inc = create_incident_from_alert(db, alert, created_by=user.id, created_by_name=user.username)
            db.commit()
            _push(background, inc, "created", user)
            return get_incident(inc.id, db, user)

    if body.priority not in VALID_PRIORITY:
        raise HTTPException(400, f"priority must be one of {VALID_PRIORITY}")

    inc = Incident(
        ticket_id=_next_ticket_id(db), title=body.title, description=body.description,
        incident_type=body.incident_type, source="manual", priority=body.priority, status="new",
        camera_id=body.camera_id, camera_location=body.camera_location, lat=body.lat, lng=body.lng,
        alert_id=body.alert_id, evidence_id=body.evidence_id, person_name=body.person_name,
        plate_number=body.plate_number, created_by=user.id, created_by_name=user.username,
    )
    db.add(inc)
    db.flush()
    inc.jurisdiction_id = jsvc.incident_jurisdiction(db, inc)
    add_event(db, inc, "CREATED", "Manual incident created", user.username, actor_id=user.id, camera_id=body.camera_id)
    db.commit()
    _push(background, inc, "created", user)
    return get_incident(inc.id, db, user)


@router.put("/{incident_id}")
def update_incident(incident_id: int, body: IncidentUpdate, request: Request, background: BackgroundTasks,
                    db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if user.role == "viewer":
        raise HTTPException(403, "Read-only role")
    inc = _load(db, incident_id, user)
    changed = []

    if body.status is not None:
        current, target = fsm.normalize(inc.status), fsm.normalize(body.status)
        try:
            fsm.check(current, target, role=user.role, note=body.note)
        except fsm.TransitionError as e:
            raise HTTPException(e.code, str(e))
        if target != current:
            msg = f"{current} → {target}" + (f": {body.note.strip()}" if body.note and body.note.strip() else "")
            add_event(db, inc, "STATUS", msg, user.username, actor_id=user.id,
                      payload={"from": current, "to": target, "note": (body.note or "").strip() or None})
            if body.note and body.note.strip():
                db.add(IncidentNote(incident_id=inc.id, author_id=user.id, author_name=user.username,
                                    body=f"[{target}] {body.note.strip()}"))
            inc.status = target
            if target == "resolved":
                inc.resolved_at = utcnow()
            if target in ("closed", "false_alarm"):
                inc.closed_at = utcnow()
            if current in fsm.DONE_STATUSES and target in fsm.OPEN_STATUSES:
                inc.closed_at = None
            log_audit(db, user, "INCIDENT_STATUS", "incident", str(inc.id), f"{current}->{target}", request)
            changed.append("status")
        elif inc.status != target:          # legacy value rewritten in place
            inc.status = target

    if body.priority is not None:
        if body.priority not in VALID_PRIORITY:
            raise HTTPException(400, f"priority must be one of {VALID_PRIORITY}")
        if body.priority != inc.priority:
            add_event(db, inc, "PRIORITY", f"{inc.priority} → {body.priority}", user.username, actor_id=user.id,
                      payload={"from": inc.priority, "to": body.priority})
            inc.priority = body.priority
            changed.append("priority")

    if body.assigned_name is not None or body.assigned_to is not None:
        name = body.assigned_name
        if body.assigned_to:
            owner = db.query(User).filter(User.id == body.assigned_to, User.is_active == True).first()  # noqa: E712
            if not owner:
                raise HTTPException(400, "Unknown user")
            name = name or owner.username
        if body.assigned_to == 0:
            name = None
        add_event(db, inc, "ASSIGNED" if name else "UNASSIGNED", f"Case owner: {name}" if name else "Case owner removed",
                  user.username, actor_id=user.id, payload={"owner_id": body.assigned_to or None})
        inc.assigned_to = body.assigned_to or None
        inc.assigned_name = name
        changed.append("owner")

    if body.title is not None:
        inc.title = body.title
    if body.description is not None:
        inc.description = body.description

    db.commit()
    if changed:
        _push(background, inc, ",".join(changed), user)
    return get_incident(incident_id, db, user)


@router.post("/{incident_id}/notes", response_model=NoteOut)
def add_note(incident_id: int, body: NoteCreate, background: BackgroundTasks, db: Session = Depends(get_db),
             user: User = Depends(operator_or_admin)):
    if user.role == "viewer":
        raise HTTPException(403, "Read-only role")
    inc = _load(db, incident_id, user)
    note = IncidentNote(incident_id=incident_id, author_id=user.id, author_name=user.username, body=body.body)
    db.add(note)
    add_event(db, inc, "NOTE", f"Note added by {user.username}", user.username, actor_id=user.id)
    db.commit()
    db.refresh(note)
    _push(background, inc, "note", user)
    return note


@router.post("/from-alert/{alert_id}")
def open_from_alert(alert_id: int, background: BackgroundTasks, db: Session = Depends(get_db),
                    user: User = Depends(operator_or_admin)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(404, "Alert not found")
    inc = create_incident_from_alert(db, alert, created_by=user.id, created_by_name=user.username)
    db.commit()
    _push(background, inc, "created", user)
    return get_incident(inc.id, db, user)


# ——— Officers (jurisdiction-checked) ———

@router.get("/{incident_id}/eligible-officers")
def eligible_officers(incident_id: int, request: Request, neighbours: bool = False, db: Session = Depends(get_db),
                      user: User = Depends(operator_or_admin)):
    """Officers whose jurisdiction covers the incident's camera, sorted by availability then
    distance. Neighbouring areas only for supervisor/admin, and every such look is audit-logged."""
    inc = _load(db, incident_id, user)
    if neighbours and not _is_command(user):
        raise HTTPException(403, "Only a supervisor or admin can include neighbouring jurisdictions")
    res = jsvc.eligible_officers(db, camera_id=inc.camera_id, lat=inc.lat, lng=inc.lng, include_neighbours=neighbours)
    if neighbours:
        log_audit(db, user, "OVERRIDE_NEIGHBOURS_VIEW", "incident", str(incident_id), res["area"]["name"] if res["area"] else "", request)
        db.commit()
    assigned = {a.user_id for a in inc.assignments}
    for o in res["officers"]:
        o["assigned"] = o["id"] in assigned
    return res


@router.post("/{incident_id}/assignments")
def assign_officers(incident_id: int, body: AssignBody, request: Request, background: BackgroundTasks,
                    db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if user.role not in ("operator", "supervisor", "admin"):
        raise HTTPException(403, "Only the command centre assigns officers")
    inc = _load(db, incident_id, user)
    if body.include_neighbours and not _is_command(user):
        raise HTTPException(403, "Only a supervisor or admin can assign outside the jurisdiction")
    res = jsvc.eligible_officers(db, camera_id=inc.camera_id, lat=inc.lat, lng=inc.lng,
                                 include_neighbours=body.include_neighbours)
    allowed = {o["id"]: o for o in res["officers"]}
    bad = [uid for uid in body.user_ids if uid not in allowed]
    if bad:
        raise HTTPException(403, f"Officer(s) {bad} do not cover this camera's jurisdiction")
    if any(allowed[uid]["out_of_area"] for uid in body.user_ids) and len((body.reason or "").strip()) < 3:
        raise HTTPException(400, "A reason is required to assign an officer from a neighbouring jurisdiction")
    have = {a.user_id for a in inc.assignments}
    added = []
    for uid in body.user_ids:
        if uid in have:
            continue
        out = allowed[uid]["out_of_area"]
        db.add(IncidentAssignment(incident_id=inc.id, user_id=uid, assigned_by=user.id, state="assigned", out_of_area=out))
        added.append(allowed[uid])
        if out:
            log_audit(db, user, "OVERRIDE_JURISDICTION", "incident", str(inc.id),
                      f"officer {uid} from neighbouring area; reason: {body.reason or '-'}", request)
            add_event(db, inc, "OVERRIDE", f"{allowed[uid]['name']} assigned from a neighbouring area"
                      + (f" — {body.reason}" if body.reason else ""), user.username, actor_id=user.id,
                      payload={"officer_id": uid, "reason": body.reason})
    if added:
        names = ", ".join(o["name"] for o in added)
        add_event(db, inc, "ASSIGNED", f"Assigned {names}", user.username, actor_id=user.id,
                  payload={"officer_ids": [o["id"] for o in added]})
        log_audit(db, user, "INCIDENT_ASSIGN", "incident", str(inc.id), names, request)
        if not inc.assigned_to:
            first = added[0]
            inc.assigned_to, inc.assigned_name = first["id"], first["name"]
        if fsm.normalize(inc.status) in ("new", "acknowledged", "verified_match"):
            add_event(db, inc, "STATUS", f"{fsm.normalize(inc.status)} → officer_dispatched", "SYSTEM",
                      payload={"from": fsm.normalize(inc.status), "to": "officer_dispatched", "auto": True})
            inc.status = "officer_dispatched"
    db.commit()
    if added:
        _push(background, inc, "assignment", user)
    return get_incident(incident_id, db, user)


@router.delete("/{incident_id}/assignments/{officer_id}")
def unassign_officer(incident_id: int, officer_id: int, request: Request, background: BackgroundTasks,
                     db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if user.role not in ("operator", "supervisor", "admin"):
        raise HTTPException(403, "Only the command centre removes officers")
    inc = _load(db, incident_id, user)
    row = next((a for a in inc.assignments if a.user_id == officer_id), None)
    if not row:
        raise HTTPException(404, "Officer not on this incident")
    u = db.get(User, officer_id)
    inc.assignments.remove(row)
    if inc.assigned_to == officer_id:
        nxt = next((a for a in inc.assignments), None)
        inc.assigned_to = nxt.user_id if nxt else None
        inc.assigned_name = db.get(User, nxt.user_id).username if nxt else None
    add_event(db, inc, "UNASSIGNED", f"Removed {u.username if u else officer_id}", user.username, actor_id=user.id,
              payload={"officer_id": officer_id})
    log_audit(db, user, "INCIDENT_UNASSIGN", "incident", str(inc.id), str(officer_id), request)
    db.commit()
    _push(background, inc, "assignment", user)
    return get_incident(incident_id, db, user)


STATE_LABEL = {"acknowledged": "acknowledged", "en_route": "is en route", "on_scene": "is on scene",
               "located": "has located the target", "unable": "is unable to respond"}


@router.put("/{incident_id}/assignments/me")
def my_assignment_state(incident_id: int, body: OfficerStateBody, request: Request, background: BackgroundTasks,
                        db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """An assigned officer reports: Acknowledge / En route / On scene / Located / Unable."""
    if body.state not in ASSIGNMENT_STATES or body.state == "assigned":
        raise HTTPException(400, f"state must be one of {', '.join(s for s in ASSIGNMENT_STATES if s != 'assigned')}")
    inc = _load(db, incident_id, user)
    row = next((a for a in inc.assignments if a.user_id == user.id), None)
    if not row:
        raise HTTPException(403, "You are not assigned to this incident")
    row.state = body.state
    text = f"{user.username} {STATE_LABEL[body.state]}" + (f" — {body.note}" if body.note else "")
    add_event(db, inc, "OFFICER_STATE", text, user.username, actor_id=user.id,
              payload={"state": body.state, "note": body.note})
    cur = fsm.normalize(inc.status)
    if body.state == "located" and "target_located" in fsm.TRANSITIONS.get(cur, []):
        add_event(db, inc, "STATUS", f"{cur} → target_located", user.username, actor_id=user.id,
                  payload={"from": cur, "to": "target_located", "auto": True})
        inc.status = "target_located"
    elif body.state in ("en_route", "on_scene") and cur in ("new", "acknowledged", "verified_match"):
        add_event(db, inc, "STATUS", f"{cur} → officer_dispatched", user.username, actor_id=user.id,
                  payload={"from": cur, "to": "officer_dispatched", "auto": True})
        inc.status = "officer_dispatched"
    log_audit(db, user, "OFFICER_STATE", "incident", str(inc.id), body.state, request)
    db.commit()
    _push(background, inc, "officer_state", user)
    return get_incident(incident_id, db, user)
