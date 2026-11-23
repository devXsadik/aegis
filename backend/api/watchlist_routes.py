"""Watchlists with governance: people (criminal entries of known_persons) and vehicles.

Every add / edit / approve / reject / revoke / remove / view / list is audit-logged.
Activation needs a second person (supervisor/admin, not the requester). Expired entries stop
alerting on their own (matching checks the dates)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.auth.auth import admin_only, get_current_user, operator_or_admin, supervisor_or_admin
from backend.auth.guards import viewer_dep
from backend.db.database import get_db
from backend.models.known_person import KnownPerson
from backend.models.user import User
from backend.models.watchlist import VehicleCatalog, WatchlistVehicle, WatchlistVehiclePhoto
from backend.services import watchlist_gov as gov
from backend.services.audit import log_audit
from backend.services.vehicle_catalog import codes
from backend.utils.at_rest import seal, unseal
from core.analysis import bd_plate

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

REQUEST_ROLES = ("operator", "investigator", "supervisor", "admin")
MAX_PHOTO = 5 * 1024 * 1024


def _can_request(user: User):
    if user.role not in REQUEST_ROLES:
        raise HTTPException(403, "Your role cannot request watchlist entries")


def _gov_err(e: gov.GovernanceError):
    raise HTTPException(e.code, str(e))


def _names(db: Session, ids) -> dict:
    ids = {i for i in ids if i}
    return {u.id: u.username for u in db.query(User).filter(User.id.in_(ids))} if ids else {}


def _gov_out(e, names: dict) -> dict:
    return {
        "case_no": e.case_no, "offence": e.offence, "risk_level": e.risk_level,
        "issuing_authority": e.issuing_authority, "legal_basis": e.legal_basis,
        "status": e.wl_status, "effective_status": gov.effective_status(e), "alerting": gov.is_active(e),
        "requested_by": names.get(e.requested_by), "requested_by_id": e.requested_by, "requested_at": e.requested_at,
        "approved_by": names.get(e.approved_by), "approved_at": e.approved_at,
        "starts_at": e.starts_at, "expires_at": e.expires_at, "decision_note": e.decision_note,
        "needs_review": bool(e.needs_review),
    }


# ——— Plate helper ———

class PlateText(BaseModel):
    text: str = Field(max_length=80)


@router.post("/plates/normalize")
def normalize_plate(body: PlateText, user: User = Depends(operator_or_admin)):
    """Live preview for the plate entry box: canonical form, Bangla rendering, what is missing."""
    p = bd_plate.parse(body.text)
    if not p:
        return {"ok": False, "canonical": None, "bangla": None, "complete": False,
                "hint": "Needs the 2-digit series and 4-digit number, e.g. ঢাকা মেট্রো-গ ১২-৩৪৫৬"}
    missing = [n for n, v in (("city", p.city), ("class letter", p.cls)) if not v]
    return {"ok": True, "canonical": p.canonical, "bangla": p.bangla(), "complete": p.complete,
            "parts": {"city": p.city, "metro": p.metro, "class": p.cls, "series": p.series, "number": p.number},
            "hint": f"Missing {' and '.join(missing)}" if missing else None}


# ——— Catalog ———

class CatalogIn(BaseModel):
    kind: str = Field(pattern="^(type|color|make|model)$")
    code: str = Field(min_length=1, max_length=40, pattern="^[a-z0-9_]+$")
    name_en: str = Field(min_length=1, max_length=60)
    name_bn: Optional[str] = Field(default=None, max_length=60)
    parent_code: Optional[str] = Field(default=None, max_length=40)


class CatalogPatch(BaseModel):
    name_en: Optional[str] = Field(default=None, max_length=60)
    name_bn: Optional[str] = Field(default=None, max_length=60)
    active: Optional[bool] = None


def catalog_reader(user: User = Depends(get_current_user)) -> User:
    """The managed lists are not personal data: operational roles and ML engineers (labelling) read them."""
    from backend.auth.auth import ROLES_OPS
    if user.role not in ROLES_OPS and user.role != "ml_engineer":
        raise HTTPException(403, "Not allowed")
    return user


@router.get("/catalog")
def catalog(kind: Optional[str] = None, include_inactive: bool = False, db: Session = Depends(get_db),
            user: User = Depends(catalog_reader)):
    q = db.query(VehicleCatalog)
    if kind:
        q = q.filter(VehicleCatalog.kind == kind)
    if not include_inactive:
        q = q.filter(VehicleCatalog.active == True)  # noqa: E712
    return [{"id": c.id, "kind": c.kind, "code": c.code, "name_en": c.name_en, "name_bn": c.name_bn,
             "parent_code": c.parent_code, "active": c.active}
            for c in q.order_by(VehicleCatalog.kind, VehicleCatalog.sort, VehicleCatalog.name_en)]


@router.post("/catalog", status_code=201)
def add_catalog(body: CatalogIn, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_only)):
    if db.query(VehicleCatalog).filter_by(kind=body.kind, code=body.code).first():
        raise HTTPException(409, "Code already exists for this list")
    if body.kind == "model" and body.parent_code and body.parent_code not in codes(db, "make"):
        raise HTTPException(400, "parent_code must be an existing make")
    c = VehicleCatalog(**body.model_dump(), sort=500)
    db.add(c)
    log_audit(db, user, "CATALOG_ADD", "vehicle_catalog", f"{body.kind}:{body.code}", body.name_en, request)
    db.commit()
    return {"id": c.id}


@router.patch("/catalog/{cid}")
def edit_catalog(cid: int, body: CatalogPatch, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(admin_only)):
    c = db.get(VehicleCatalog, cid)
    if not c:
        raise HTTPException(404, "Not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    log_audit(db, user, "CATALOG_EDIT", "vehicle_catalog", f"{c.kind}:{c.code}", json.dumps(body.model_dump(exclude_unset=True)), request)
    db.commit()
    return {"ok": True}


# ——— People ———

class PersonRequest(BaseModel):
    case_no: str = Field(min_length=1, max_length=60)
    legal_basis: str = Field(min_length=1, max_length=2000)
    issuing_authority: str = Field(min_length=1, max_length=120)
    starts_at: datetime
    expires_at: datetime
    offence: Optional[str] = Field(default=None, max_length=120)
    risk_level: Optional[str] = None
    aliases: Optional[List[str]] = None


class PersonMeta(BaseModel):
    offence: Optional[str] = Field(default=None, max_length=120)
    risk_level: Optional[str] = None
    aliases: Optional[List[str]] = None


class Decision(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


def _person(db: Session, pid: str) -> KnownPerson:
    p = db.query(KnownPerson).filter(KnownPerson.person_id == pid).first()
    if not p:
        raise HTTPException(404, "Person not found")
    return p


def _person_out(db: Session, p: KnownPerson, names: dict) -> dict:
    return {"person_id": p.person_id, "name": p.name, "category": p.category, "criminal_status": p.criminal_status,
            "aliases": json.loads(p.aliases) if p.aliases else [], "notes": p.notes,
            "photos": len(p.images or []), **_gov_out(p, names)}


@router.get("/persons")
def list_persons(request: Request, status: Optional[str] = None, q: Optional[str] = Query(default=None, max_length=100),
                 db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if gov.sweep(db):
        db.commit()
    query = db.query(KnownPerson).filter(KnownPerson.category == "criminal")
    if status:
        query = query.filter(KnownPerson.wl_status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(KnownPerson.name.ilike(like), KnownPerson.person_id.ilike(like),
                                 KnownPerson.case_no.ilike(like), KnownPerson.aliases.ilike(like)))
    rows = query.order_by(KnownPerson.id.desc()).limit(500).all()
    names = _names(db, [r.requested_by for r in rows] + [r.approved_by for r in rows])
    log_audit(db, user, "WATCHLIST_LIST", "watchlist_person", "", json.dumps({"status": status, "q": q}), request)
    db.commit()
    return [_person_out(db, p, names) for p in rows]


@router.get("/persons/{pid}")
def view_person(pid: str, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    p = _person(db, pid)
    log_audit(db, user, "WATCHLIST_VIEW", "watchlist_person", pid, "", request)
    db.commit()
    return _person_out(db, p, _names(db, [p.requested_by, p.approved_by]))


@router.put("/persons/{pid}/request")
def request_person(pid: str, body: PersonRequest, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(operator_or_admin)):
    _can_request(user)
    p = _person(db, pid)
    if p.category != "criminal":
        raise HTTPException(400, "Only a person in the criminal category can be put on the watchlist")
    try:
        gov.validate_risk(body.risk_level)
        fields = body.model_dump(exclude={"aliases"})
        gov.submit(p, user, fields)
    except gov.GovernanceError as e:
        _gov_err(e)
    if body.aliases is not None:
        p.aliases = json.dumps([a.strip() for a in body.aliases if a.strip()], ensure_ascii=False)
    log_audit(db, user, "WATCHLIST_REQUEST", "watchlist_person", pid,
              json.dumps({"case_no": body.case_no, "expires_at": body.expires_at.isoformat()}), request)
    db.commit()
    return _person_out(db, p, _names(db, [p.requested_by]))


@router.patch("/persons/{pid}")
def edit_person_meta(pid: str, body: PersonMeta, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(operator_or_admin)):
    _can_request(user)
    p = _person(db, pid)
    ch = body.model_dump(exclude_unset=True)
    try:
        gov.validate_risk(ch.get("risk_level"))
    except gov.GovernanceError as e:
        _gov_err(e)
    if "aliases" in ch:
        p.aliases = json.dumps([a.strip() for a in (body.aliases or []) if a.strip()], ensure_ascii=False)
    for k in ("offence", "risk_level"):
        if k in ch:
            setattr(p, k, ch[k])
    log_audit(db, user, "WATCHLIST_EDIT", "watchlist_person", pid, json.dumps(ch, ensure_ascii=False), request)
    db.commit()
    return _person_out(db, p, _names(db, [p.requested_by, p.approved_by]))


def _decide(db, entry, user, action, note, request, kind, ref):
    try:
        if action == "approve":
            gov.approve(entry, user, note)
        else:
            gov.decide_against(entry, user, action, note)
    except gov.GovernanceError as e:
        _gov_err(e)
    log_audit(db, user, f"WATCHLIST_{action.upper()}", f"watchlist_{kind}", ref, note or "", request)
    db.commit()


@router.post("/persons/{pid}/{action}")
def decide_person(pid: str, action: str, body: Decision, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(supervisor_or_admin)):
    if action not in ("approve", "reject", "revoke"):
        raise HTTPException(404, "Unknown action")
    p = _person(db, pid)
    _decide(db, p, user, action, body.note, request, "person", pid)
    return _person_out(db, p, _names(db, [p.requested_by, p.approved_by]))


# ——— Vehicles ———

class VehicleIn(BaseModel):
    plate: Optional[str] = Field(default=None, max_length=60)
    vehicle_type: Optional[str] = Field(default=None, max_length=30)
    color_primary: Optional[str] = Field(default=None, max_length=20)
    color_secondary: Optional[str] = Field(default=None, max_length=20)
    make_model: Optional[str] = Field(default=None, max_length=60)
    marks: Optional[str] = Field(default=None, max_length=2000)
    notes: Optional[str] = Field(default=None, max_length=2000)
    linked_person_id: Optional[str] = None          # known_persons.person_id
    risk_level: str = "medium"
    case_no: str = Field(min_length=1, max_length=60)
    offence: Optional[str] = Field(default=None, max_length=120)
    issuing_authority: str = Field(min_length=1, max_length=120)
    legal_basis: str = Field(min_length=1, max_length=2000)
    starts_at: datetime
    expires_at: datetime


class VehiclePatch(BaseModel):
    plate: Optional[str] = Field(default=None, max_length=60)
    vehicle_type: Optional[str] = None
    color_primary: Optional[str] = None
    color_secondary: Optional[str] = None
    make_model: Optional[str] = None
    marks: Optional[str] = None
    notes: Optional[str] = None
    linked_person_id: Optional[str] = None
    risk_level: Optional[str] = None
    case_no: Optional[str] = None
    offence: Optional[str] = None
    issuing_authority: Optional[str] = None
    legal_basis: Optional[str] = None
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


def _vehicle(db: Session, ref: str) -> WatchlistVehicle:
    v = db.query(WatchlistVehicle).filter(WatchlistVehicle.ref == ref).first()
    if not v:
        raise HTTPException(404, "Vehicle not found")
    return v


def _check_vehicle_fields(db: Session, d: dict, current: Optional[WatchlistVehicle] = None):
    get = lambda k: d[k] if k in d else (getattr(current, k, None) if current else None)  # noqa: E731
    plate = d["plate"] if "plate" in d else (current.plate_raw if current else None)
    if plate:
        if not bd_plate.parse(plate):
            raise HTTPException(400, "Plate not understood: give at least the 2-digit series and 4-digit number")
    if not plate and not (get("vehicle_type") and get("color_primary")):
        raise HTTPException(400, "Give a plate number, or at least the vehicle type and colour")
    for field, kind in (("vehicle_type", "type"), ("color_primary", "color"), ("color_secondary", "color"),
                        ("make_model", "model")):
        val = d.get(field)
        if val and val not in codes(db, kind):
            raise HTTPException(400, f"{field} '{val}' is not in the managed list")
    if d.get("risk_level"):
        try:
            gov.validate_risk(d["risk_level"])
        except gov.GovernanceError as e:
            _gov_err(e)


def _linked(db: Session, pid: Optional[str]) -> Optional[int]:
    if not pid:
        return None
    p = db.query(KnownPerson).filter(KnownPerson.person_id == pid).first()
    if not p:
        raise HTTPException(400, "linked_person_id not found")
    return p.id


def _vehicle_out(db: Session, v: WatchlistVehicle, names: dict) -> dict:
    p = bd_plate.parse(v.plate_raw) if v.plate_raw else None
    linked = db.get(KnownPerson, v.linked_person_id) if v.linked_person_id else None
    return {"ref": v.ref, "plate": v.plate_raw, "plate_canonical": v.plate_canonical,
            "plate_bangla": p.bangla() if p else None, "vehicle_type": v.vehicle_type,
            "color_primary": v.color_primary, "color_secondary": v.color_secondary, "make_model": v.make_model,
            "marks": v.marks, "notes": v.notes,
            "linked_person": {"person_id": linked.person_id, "name": linked.name} if linked else None,
            "photos": [{"id": ph.id, "url": f"/api/v1/watchlist/vehicle-photos/{ph.id}"} for ph in v.photos],
            "created_at": v.created_at, **_gov_out(v, names)}


@router.get("/vehicles")
def list_vehicles(request: Request, status: Optional[str] = None, q: Optional[str] = Query(default=None, max_length=100),
                  db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if gov.sweep(db):
        db.commit()
    query = db.query(WatchlistVehicle)
    if status:
        query = query.filter(WatchlistVehicle.wl_status == status)
    if q:
        canon = bd_plate.canonical(q)
        like = f"%{q}%"
        conds = [WatchlistVehicle.plate_raw.ilike(like), WatchlistVehicle.case_no.ilike(like),
                 WatchlistVehicle.ref.ilike(like), WatchlistVehicle.marks.ilike(like)]
        if canon:
            conds.append(WatchlistVehicle.plate_canonical == canon)
        query = query.filter(or_(*conds))
    rows = query.order_by(WatchlistVehicle.id.desc()).limit(500).all()
    names = _names(db, [r.requested_by for r in rows] + [r.approved_by for r in rows])
    log_audit(db, user, "WATCHLIST_LIST", "watchlist_vehicle", "", json.dumps({"status": status, "q": q}, ensure_ascii=False), request)
    db.commit()
    return [_vehicle_out(db, v, names) for v in rows]


@router.get("/vehicles/{ref}")
def view_vehicle(ref: str, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    v = _vehicle(db, ref)
    log_audit(db, user, "WATCHLIST_VIEW", "watchlist_vehicle", ref, "", request)
    db.commit()
    return _vehicle_out(db, v, _names(db, [v.requested_by, v.approved_by]))


@router.post("/vehicles", status_code=201)
def add_vehicle(body: VehicleIn, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    _can_request(user)
    d = body.model_dump()
    _check_vehicle_fields(db, d)
    v = WatchlistVehicle(
        ref=f"V-{uuid.uuid4().hex[:8].upper()}", plate_raw=(body.plate or "").strip() or None,
        plate_canonical=bd_plate.canonical(body.plate) if body.plate else None,
        vehicle_type=body.vehicle_type, color_primary=body.color_primary, color_secondary=body.color_secondary,
        make_model=body.make_model, marks=body.marks, notes=body.notes,
        linked_person_id=_linked(db, body.linked_person_id), risk_level=body.risk_level,
        case_no=body.case_no, issuing_authority=body.issuing_authority, legal_basis=body.legal_basis,
        starts_at=body.starts_at, expires_at=body.expires_at, wl_status="pending")
    try:
        gov.submit(v, user, {k: d[k] for k in gov.LEGAL_FIELDS} | {"offence": body.offence})
    except gov.GovernanceError as e:
        _gov_err(e)
    db.add(v)
    db.flush()
    log_audit(db, user, "WATCHLIST_ADD", "watchlist_vehicle", v.ref,
              json.dumps({"plate": v.plate_canonical, "type": v.vehicle_type, "color": v.color_primary,
                          "case_no": v.case_no}, ensure_ascii=False), request)
    db.commit()
    return _vehicle_out(db, v, _names(db, [v.requested_by]))


@router.patch("/vehicles/{ref}")
def edit_vehicle(ref: str, body: VehiclePatch, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(operator_or_admin)):
    _can_request(user)
    v = _vehicle(db, ref)
    ch = body.model_dump(exclude_unset=True)
    _check_vehicle_fields(db, ch, v)
    legal = {k: ch[k] for k in gov.LEGAL_FIELDS if k in ch}
    # The plate is what alerts: changing it is a legal change too.
    plate_changed = "plate" in ch and (ch["plate"] or None) != v.plate_raw
    if legal or plate_changed:
        try:
            gov.submit(v, user, legal)
        except gov.GovernanceError as e:
            _gov_err(e)
    if "plate" in ch:
        v.plate_raw = (ch["plate"] or "").strip() or None
        v.plate_canonical = bd_plate.canonical(v.plate_raw) if v.plate_raw else None
    if "linked_person_id" in ch:
        v.linked_person_id = _linked(db, ch["linked_person_id"])
    for k in ("vehicle_type", "color_primary", "color_secondary", "make_model", "marks", "notes", "risk_level", "offence"):
        if k in ch:
            setattr(v, k, ch[k])
    log_audit(db, user, "WATCHLIST_EDIT", "watchlist_vehicle", ref,
              json.dumps({k: str(x) for k, x in ch.items()}, ensure_ascii=False) + (" (re-approval needed)" if legal or plate_changed else ""),
              request)
    db.commit()
    return _vehicle_out(db, v, _names(db, [v.requested_by, v.approved_by]))


@router.post("/vehicles/{ref}/photos", status_code=201)
async def add_vehicle_photo(ref: str, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                            user: User = Depends(operator_or_admin)):
    _can_request(user)
    v = _vehicle(db, ref)
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(415, "Photo must be JPEG, PNG or WebP")
    data = await file.read()
    if len(data) > MAX_PHOTO:
        raise HTTPException(413, "Photo larger than 5 MB")
    blob, enc = seal(data)
    from backend.services.matching.vehicle import embed_photo
    ph = WatchlistVehiclePhoto(vehicle_id=v.id, image=blob, encrypted=enc, content_type=file.content_type,
                               sha256=hashlib.sha256(data).hexdigest(), embedding=embed_photo(data))
    db.add(ph)
    db.flush()
    log_audit(db, user, "WATCHLIST_PHOTO_ADD", "watchlist_vehicle", ref, ph.sha256, request)
    db.commit()
    return {"id": ph.id}


@router.get("/vehicle-photos/{photo_id}")
def vehicle_photo(photo_id: int, db: Session = Depends(get_db), viewer: User = Depends(viewer_dep)):
    ph = db.get(WatchlistVehiclePhoto, photo_id)
    if not ph:
        raise HTTPException(404, "Photo not found")
    return Response(content=unseal(ph.image, ph.encrypted), media_type=ph.content_type,
                    headers={"Cache-Control": "private, no-store"})


@router.post("/vehicles/{ref}/{action}")
def decide_vehicle(ref: str, action: str, body: Decision, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(supervisor_or_admin)):
    if action not in ("approve", "reject", "revoke"):
        raise HTTPException(404, "Unknown action")
    v = _vehicle(db, ref)
    _decide(db, v, user, action, body.note, request, "vehicle", ref)
    return _vehicle_out(db, v, _names(db, [v.requested_by, v.approved_by]))


@router.delete("/vehicles/{ref}")
def remove_vehicle(ref: str, request: Request, note: Optional[str] = None, db: Session = Depends(get_db),
                   user: User = Depends(admin_only)):
    """Only entries that never alerted (pending / rejected) may be removed; others are revoked."""
    v = _vehicle(db, ref)
    if v.wl_status not in ("pending", "rejected"):
        raise HTTPException(409, "Revoke an approved entry instead of deleting it (the record must stay)")
    log_audit(db, user, "WATCHLIST_REMOVE", "watchlist_vehicle", ref, note or "", request)
    db.delete(v)
    db.commit()
    return {"deleted": ref}


# ——— Approval queue ———

@router.get("/approvals")
def approvals(db: Session = Depends(get_db), user: User = Depends(supervisor_or_admin)):
    persons = db.query(KnownPerson).filter(KnownPerson.wl_status == "pending").all()
    vehicles = db.query(WatchlistVehicle).filter(WatchlistVehicle.wl_status == "pending").all()
    review = (db.query(KnownPerson).filter(KnownPerson.needs_review == True).count()  # noqa: E712
              + db.query(WatchlistVehicle).filter(WatchlistVehicle.needs_review == True).count())  # noqa: E712
    names = _names(db, [e.requested_by for e in persons + vehicles])
    return {
        "persons": [_person_out(db, p, names) | {"can_approve": p.requested_by != user.id} for p in persons],
        "vehicles": [_vehicle_out(db, v, names) | {"can_approve": v.requested_by != user.id} for v in vehicles],
        "legacy_needing_review": review,
    }
