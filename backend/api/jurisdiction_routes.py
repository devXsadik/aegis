"""Jurisdictions (areas) and police officer profiles.

Reading areas is open to operational roles (the map and pickers need them). Changing areas or
officer profiles is admin-only. An officer may set their own duty status and position."""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.auth import admin_only, get_current_user, operator_or_admin, supervisor_or_admin
from backend.auth.guards import viewer_dep
from backend.db.database import get_db
from backend.models.camera import Camera
from backend.models.jurisdiction import (
    DUTY_STATUSES, LEVELS, Jurisdiction, OfficerJurisdiction, OfficerProfile,
)
from backend.models.user import User
from backend.services import geo
from backend.services import jurisdiction as jsvc
from backend.services.audit import log_audit
from clock import utcnow

router = APIRouter(tags=["jurisdictions"])

MAX_PHOTO = 2 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}


class JurisdictionIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name_en: str = Field(min_length=1, max_length=100)
    name_bn: Optional[str] = Field(default=None, max_length=100)
    level: str = "thana"
    parent_id: Optional[int] = None
    geojson: Optional[dict] = None


class JurisdictionPatch(BaseModel):
    name_en: Optional[str] = Field(default=None, max_length=100)
    name_bn: Optional[str] = Field(default=None, max_length=100)
    parent_id: Optional[int] = None
    geojson: Optional[dict] = None


def _jout(j: Jurisdiction, with_geo: bool = True, counts=None) -> dict:
    out = {"id": j.id, "code": j.code, "name_en": j.name_en, "name_bn": j.name_bn, "level": j.level,
           "parent_id": j.parent_id}
    if with_geo:
        out["geojson"] = geo.parse(j.geojson)
        c = geo.centroid(j.geojson)
        out["center"] = {"lat": c[0], "lng": c[1]} if c else None
    if counts is not None:
        out["officers"] = counts.get(j.id, 0)
    return out


def _check_geo(gj):
    if gj is not None and not geo.valid_polygon(gj):
        raise HTTPException(400, "geojson must be a Polygon or MultiPolygon in [lng, lat] order")


def _check_parent(db: Session, parent_id: Optional[int], self_id: Optional[int] = None):
    if parent_id is None:
        return
    by_id = {j.id: j for j in db.query(Jurisdiction).all()}
    if parent_id not in by_id:
        raise HTTPException(400, "parent_id not found")
    if self_id is not None and self_id in jsvc.ancestors(parent_id, by_id):
        raise HTTPException(400, "An area cannot sit inside itself")


@router.get("/jurisdictions")
def list_jurisdictions(geo_data: bool = True, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    counts = {}
    for lk in db.query(OfficerJurisdiction).all():
        counts[lk.jurisdiction_id] = counts.get(lk.jurisdiction_id, 0) + 1
    rows = db.query(Jurisdiction).order_by(Jurisdiction.level, Jurisdiction.name_en).all()
    return [_jout(j, geo_data, counts) for j in rows]


@router.get("/jurisdictions/locate")
def locate_point(lat: float, lng: float, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    by_id = {j.id: j for j in db.query(Jurisdiction).all()}
    found = jsvc.locate(db, lat, lng, by_id)
    if not found:
        return {"jurisdiction": None, "chain": []}
    return {"jurisdiction": _jout(found, False), "chain": [_jout(by_id[i], False) for i in jsvc.ancestors(found.id, by_id)]}


@router.post("/jurisdictions", status_code=201)
def create_jurisdiction(body: JurisdictionIn, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(admin_only)):
    if body.level not in LEVELS:
        raise HTTPException(400, f"level must be one of {', '.join(LEVELS)}")
    if db.query(Jurisdiction).filter(Jurisdiction.code == body.code).first():
        raise HTTPException(409, "An area with this code exists")
    _check_geo(body.geojson)
    _check_parent(db, body.parent_id)
    j = Jurisdiction(code=body.code, name_en=body.name_en, name_bn=body.name_bn, level=body.level,
                     parent_id=body.parent_id, geojson=json.dumps(body.geojson) if body.geojson else None)
    db.add(j)
    db.flush()
    log_audit(db, user, "JURISDICTION_CREATE", "jurisdiction", str(j.id), body.code, request)
    db.commit()
    return _jout(j)


@router.put("/jurisdictions/{jid}")
def update_jurisdiction(jid: int, body: JurisdictionPatch, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(admin_only)):
    j = db.get(Jurisdiction, jid)
    if not j:
        raise HTTPException(404, "Area not found")
    changes = body.model_dump(exclude_unset=True)
    if "geojson" in changes:
        _check_geo(body.geojson)
        j.geojson = json.dumps(body.geojson) if body.geojson else None
    if "parent_id" in changes:
        _check_parent(db, body.parent_id, jid)
        j.parent_id = body.parent_id
    for k in ("name_en", "name_bn"):
        if k in changes:
            setattr(j, k, changes[k])
    log_audit(db, user, "JURISDICTION_UPDATE", "jurisdiction", str(jid), ",".join(sorted(changes)), request)
    db.commit()
    return _jout(j)


@router.delete("/jurisdictions/{jid}")
def delete_jurisdiction(jid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(admin_only)):
    j = db.get(Jurisdiction, jid)
    if not j:
        raise HTTPException(404, "Area not found")
    if db.query(Jurisdiction).filter(Jurisdiction.parent_id == jid).count():
        raise HTTPException(409, "Remove or move the areas inside it first")
    db.query(OfficerJurisdiction).filter(OfficerJurisdiction.jurisdiction_id == jid).delete()
    db.query(Camera).filter(Camera.jurisdiction_id == jid).update({Camera.jurisdiction_id: None})
    log_audit(db, user, "JURISDICTION_DELETE", "jurisdiction", str(jid), j.code, request)
    db.delete(j)
    db.commit()
    return {"deleted": jid}


# ——— Officers ———

class OfficerPatch(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=100)
    rank: Optional[str] = Field(default=None, max_length=40)
    badge_no: Optional[str] = Field(default=None, max_length=30)
    phone: Optional[str] = Field(default=None, max_length=30)
    station_id: Optional[int] = None
    duty_status: Optional[str] = None
    jurisdiction_ids: Optional[List[int]] = None


class DutyBody(BaseModel):
    duty_status: str
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)


def _profile(db: Session, user_id: int) -> OfficerProfile:
    prof = db.get(OfficerProfile, user_id)
    if not prof:
        prof = OfficerProfile(user_id=user_id, duty_status="off_duty")
        db.add(prof)
        db.flush()
    return prof


def _officer_out(db: Session, u: User) -> dict:
    prof = db.get(OfficerProfile, u.id)
    areas = (db.query(Jurisdiction).join(OfficerJurisdiction, OfficerJurisdiction.jurisdiction_id == Jurisdiction.id)
             .filter(OfficerJurisdiction.user_id == u.id).all())
    card = jsvc.officer_card(u, prof, areas, active=jsvc.active_counts(db, [u.id]).get(u.id, 0))
    card["station_id"] = prof.station_id if prof else None
    card["last_seen_at"] = prof.last_seen_at.isoformat() if prof and prof.last_seen_at else None
    return card


@router.get("/officers")
def list_officers(db: Session = Depends(get_db), user: User = Depends(supervisor_or_admin)):
    users = (db.query(User).filter(User.role.in_(jsvc.OFFICER_ROLES)).order_by(User.username).all())
    return [_officer_out(db, u) for u in users]


@router.get("/officers/me")
def my_officer_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role not in jsvc.OFFICER_ROLES:
        raise HTTPException(404, "No officer profile for this account")
    return _officer_out(db, user)


@router.put("/officers/me/duty")
def set_my_duty(body: DutyBody, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role not in jsvc.OFFICER_ROLES:
        raise HTTPException(403, "Only officers have a duty status")
    if body.duty_status not in DUTY_STATUSES:
        raise HTTPException(400, f"duty_status must be one of {', '.join(DUTY_STATUSES)}")
    prof = _profile(db, user.id)
    prof.duty_status = body.duty_status
    if body.lat is not None and body.lng is not None:
        prof.last_lat, prof.last_lng, prof.last_seen_at = body.lat, body.lng, utcnow()
    log_audit(db, user, "DUTY_STATUS", "officer", str(user.id), body.duty_status, request)
    db.commit()
    return _officer_out(db, user)


@router.put("/officers/{user_id}")
def update_officer(user_id: int, body: OfficerPatch, request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(admin_only)):
    u = db.get(User, user_id)
    if not u or u.role not in jsvc.OFFICER_ROLES:
        raise HTTPException(404, "Officer not found")
    changes = body.model_dump(exclude_unset=True)
    prof = _profile(db, user_id)
    if "duty_status" in changes and body.duty_status not in DUTY_STATUSES:
        raise HTTPException(400, f"duty_status must be one of {', '.join(DUTY_STATUSES)}")
    if body.badge_no:
        clash = db.query(OfficerProfile).filter(OfficerProfile.badge_no == body.badge_no,
                                                OfficerProfile.user_id != user_id).first()
        if clash:
            raise HTTPException(409, "Badge number already used by another officer")
    ids = set(body.jurisdiction_ids or [])
    if "station_id" in changes and body.station_id is not None:
        ids_check = {body.station_id}
    else:
        ids_check = set()
    known = {j.id for j in db.query(Jurisdiction.id).filter(Jurisdiction.id.in_(ids | ids_check))} if (ids | ids_check) else set()
    if (ids | ids_check) - known:
        raise HTTPException(400, "Unknown jurisdiction id")
    for k in ("full_name", "rank", "badge_no", "station_id", "duty_status"):
        if k in changes:
            setattr(prof, k, changes[k] or (None if k != "duty_status" else "off_duty"))
    if "phone" in changes:
        u.phone = body.phone or None
    if body.jurisdiction_ids is not None:
        db.query(OfficerJurisdiction).filter(OfficerJurisdiction.user_id == user_id).delete()
        for jid in sorted(ids):
            db.add(OfficerJurisdiction(user_id=user_id, jurisdiction_id=jid))
    log_audit(db, admin, "OFFICER_UPDATE", "officer", str(user_id), ",".join(sorted(changes)), request)
    db.commit()
    return _officer_out(db, u)


@router.post("/officers/{user_id}/photo")
async def upload_officer_photo(user_id: int, request: Request, file: UploadFile = File(...),
                               db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    u = db.get(User, user_id)
    if not u or u.role not in jsvc.OFFICER_ROLES:
        raise HTTPException(404, "Officer not found")
    if file.content_type not in PHOTO_TYPES:
        raise HTTPException(415, "Photo must be JPEG, PNG or WebP")
    data = await file.read()
    if len(data) > MAX_PHOTO:
        raise HTTPException(413, "Photo larger than 2 MB")
    prof = _profile(db, user_id)
    prof.photo, prof.photo_type = data, file.content_type
    log_audit(db, admin, "OFFICER_PHOTO", "officer", str(user_id), f"{len(data)} bytes", request)
    db.commit()
    return {"ok": True}


@router.get("/officers/{user_id}/photo")
def officer_photo(user_id: int, db: Session = Depends(get_db), viewer: User = Depends(viewer_dep)):
    prof = db.get(OfficerProfile, user_id)
    if not prof or not prof.photo:
        raise HTTPException(404, "No photo")
    return Response(content=prof.photo, media_type=prof.photo_type or "image/jpeg",
                    headers={"Cache-Control": "private, max-age=600"})


class CameraArea(BaseModel):
    jurisdiction_id: Optional[int] = None


@router.put("/cameras/{camera_id}/jurisdiction")
def set_camera_jurisdiction(camera_id: str, body: CameraArea, request: Request, db: Session = Depends(get_db),
                            admin: User = Depends(admin_only)):
    cam = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    if body.jurisdiction_id is not None and not db.get(Jurisdiction, body.jurisdiction_id):
        raise HTTPException(400, "Unknown jurisdiction id")
    cam.jurisdiction_id = body.jurisdiction_id
    log_audit(db, admin, "CAMERA_JURISDICTION", "camera", camera_id, str(body.jurisdiction_id), request)
    db.commit()
    return {"camera_id": camera_id, "jurisdiction_id": cam.jurisdiction_id}
