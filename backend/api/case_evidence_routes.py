"""Case evidence (spec 12) and evidence face folders (spec 13).

Officers upload to an incident they can see; originals are immutable (a change is a new
version); only an admin may soft-delete, with a reason; every view and download is logged in
the item's custody chain and the audit log."""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.auth.auth import admin_only, operator_or_admin
from backend.auth.guards import viewer_dep
from backend.db.database import get_db
from backend.models.case_evidence import (EvidenceFace, EvidenceItem, EvidenceItemCustody, GroupOperation,
                                          PersonGroup)
from backend.models.incident import Incident
from backend.models.known_person import KnownPerson
from backend.models.user import User
from backend.services import case_evidence as ce
from backend.services import face_grouping
from backend.services.audit import log_audit
from backend.services.incident_service import add_event
from backend.utils.at_rest import unseal
from clock import utcnow

router = APIRouter(tags=["case-evidence"])
UPLOAD_ROLES = ("police", "operator", "investigator", "supervisor", "admin")
MAX_FILES = 20


def _incident_for(db: Session, incident_id: int, user: User) -> Incident:
    from backend.api.incident_routes import _scope
    inc = _scope(db, db.query(Incident).filter(Incident.id == incident_id), user).first()
    if not inc:
        raise HTTPException(404, "Incident not found")
    return inc


def _visible(db: Session, user: User):
    from backend.api.incident_routes import _scope
    return _scope(db, db.query(Incident.id), user)


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def item_out(db: Session, i: EvidenceItem, users: Optional[dict] = None) -> dict:
    users = users or {}
    up = users.get(i.uploaded_by) if users else (db.get(User, i.uploaded_by) if i.uploaded_by else None)
    return {"ref": i.ref, "id": i.id, "incident_id": i.incident_id, "kind": i.kind, "description": i.description,
            "location": i.location, "lat": i.lat, "lng": i.lng, "captured_at": i.captured_at, "camera_id": i.camera_id,
            "original_filename": i.original_filename, "content_type": i.content_type, "size": i.size, "sha256": i.sha256,
            "version": i.version, "parent_id": i.parent_id, "source": i.source, "uploaded_at": i.uploaded_at,
            "uploaded_by": up.username if up else ("SYSTEM" if i.source == "system" else None),
            "device_info": i.device_info, "faces_status": i.faces_status, "faces_found": i.faces_found,
            "deleted": i.deleted_at is not None, "delete_reason": i.delete_reason,
            "file_url": f"/api/v1/evidence-items/{i.ref}/file", "thumb_url": f"/api/v1/evidence-items/{i.ref}/file?inline=true"
            if i.kind in ("image", "snapshot") else None}


@router.post("/evidence-items")
async def upload(request: Request, incident_id: int = Form(...), files: List[UploadFile] = File(...),
                 description: Optional[str] = Form(None), location: Optional[str] = Form(None),
                 lat: Optional[float] = Form(None), lng: Optional[float] = Form(None),
                 captured_at: Optional[datetime] = Form(None), device_info: Optional[str] = Form(None),
                 db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """One or more files for one incident; each file gets its own result (ok / error)."""
    if user.role not in UPLOAD_ROLES:
        raise HTTPException(403, "Your role cannot upload evidence")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"At most {MAX_FILES} files at once")
    inc = _incident_for(db, incident_id, user)
    device = device_info or request.headers.get("user-agent", "")[:300]
    results, done = [], []
    for f in files:
        data = await f.read()
        try:
            item = ce.create(db, incident_id=inc.id, data=data, content_type=f.content_type or "", filename=f.filename,
                             user=user, description=description, location=location, lat=lat, lng=lng,
                             captured_at=captured_at, device_info=device, ip=_ip(request))
            add_event(db, inc, "EVIDENCE", f"{user.username} added {item.kind} {item.ref} ({f.filename})", user.username,
                      actor_id=user.id, payload={"ref": item.ref, "sha256": item.sha256})
            log_audit(db, user, "EVIDENCE_UPLOAD", "evidence_item", item.ref, f"incident={inc.id} sha256={item.sha256}", request)
            db.commit()
            results.append({"filename": f.filename, "ok": True, **item_out(db, item)})
            done.append(item.id)
        except ce.EvidenceError as e:
            db.rollback()
            results.append({"filename": f.filename, "ok": False, "error": str(e), "code": e.code})
    for iid in done:
        face_grouping.schedule(iid)
    return {"incident_id": inc.id, "results": results, "uploaded": len(done)}


@router.get("/evidence-items")
def list_items(incident_id: Optional[int] = None, kind: Optional[str] = None, uploader_id: Optional[int] = None,
               group_id: Optional[int] = None, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
               include_deleted: bool = False, limit: int = Query(default=60, le=200), skip: int = 0,
               db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    q = db.query(EvidenceItem).filter(EvidenceItem.incident_id.in_(_visible(db, user)))
    if not (include_deleted and user.role == "admin"):
        q = q.filter(EvidenceItem.deleted_at.is_(None))
    if incident_id:
        q = q.filter(EvidenceItem.incident_id == incident_id)
    if kind:
        q = q.filter(EvidenceItem.kind == kind)
    if uploader_id:
        q = q.filter(EvidenceItem.uploaded_by == uploader_id)
    if group_id:
        q = q.filter(EvidenceItem.id.in_(db.query(EvidenceFace.item_id).filter(EvidenceFace.group_id == group_id)))
    if date_from:
        q = q.filter(or_(EvidenceItem.captured_at >= date_from, EvidenceItem.uploaded_at >= date_from))
    if date_to:
        q = q.filter(or_(EvidenceItem.captured_at <= date_to, EvidenceItem.uploaded_at <= date_to))
    total = q.count()
    rows = q.order_by(EvidenceItem.id.desc()).offset(skip).limit(limit).all()
    users = {u.id: u for u in db.query(User).filter(User.id.in_({r.uploaded_by for r in rows if r.uploaded_by}))}
    return {"total": total, "items": [item_out(db, r, users) for r in rows]}


def _item(db: Session, ref: str, user: User) -> EvidenceItem:
    i = db.query(EvidenceItem).filter(EvidenceItem.ref == ref).first()
    if not i or i.incident_id not in {r[0] for r in _visible(db, user)}:
        raise HTTPException(404, "Evidence not found")
    if i.deleted_at and user.role != "admin":
        raise HTTPException(404, "Evidence not found")
    return i


@router.get("/evidence-items/{ref}")
def get_item(ref: str, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    i = _item(db, ref, user)
    ce.custody(db, i, "VIEWED", user, "", _ip(request))
    log_audit(db, user, "EVIDENCE_VIEW", "evidence_item", ref, "", request)
    db.commit()
    versions = [item_out(db, v) for v in db.query(EvidenceItem).filter(or_(EvidenceItem.parent_id == i.id, EvidenceItem.id == i.parent_id))]
    faces = [{"id": f.id, "group_id": f.group_id, "frame_ts": f.frame_ts, "watch_person_id": f.watch_person_id,
              "watch_similarity": f.watch_similarity, "verify_status": f.verify_status,
              "crop_url": f"/api/v1/evidence-faces/{f.id}/crop"} for f in db.query(EvidenceFace).filter(EvidenceFace.item_id == i.id)]
    custody = [{"action": c.action, "actor": c.actor, "at": c.at, "details": c.details, "record_hash": c.record_hash}
               for c in db.query(EvidenceItemCustody).filter(EvidenceItemCustody.item_id == i.id).order_by(EvidenceItemCustody.id)]
    return {**item_out(db, i), "versions": versions, "faces": faces, "custody": custody}


@router.get("/evidence-items/{ref}/file")
def download(ref: str, request: Request, inline: bool = False, db: Session = Depends(get_db), viewer: User = Depends(viewer_dep)):
    i = _item(db, ref, viewer)
    try:
        data = ce.read(i)
    except ce.EvidenceError as e:
        raise HTTPException(e.code, str(e))
    ce.custody(db, i, "VIEWED" if inline else "DOWNLOADED", viewer, "", _ip(request))
    log_audit(db, viewer, "EVIDENCE_VIEW" if inline else "EVIDENCE_DOWNLOAD", "evidence_item", ref, "", request)
    db.commit()
    name = (i.original_filename or f"{i.ref}").replace('"', "")
    disp = "inline" if inline else f'attachment; filename="{name}"'
    return Response(content=data, media_type=i.content_type, headers={"Content-Disposition": disp, "Cache-Control": "private, no-store",
                                                                      "X-Evidence-SHA256": i.sha256})


@router.post("/evidence-items/{ref}/versions")
async def new_version(ref: str, request: Request, file: UploadFile = File(...), note: str = Form(..., min_length=3),
                      db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """An edited copy (e.g. redacted, enhanced) becomes version n+1; the original is untouched."""
    if user.role not in UPLOAD_ROLES:
        raise HTTPException(403, "Your role cannot add evidence")
    parent = _item(db, ref, user)
    data = await file.read()
    try:
        item = ce.create(db, incident_id=parent.incident_id, data=data, content_type=file.content_type or parent.content_type,
                         filename=file.filename, user=user, description=note, location=parent.location, lat=parent.lat,
                         lng=parent.lng, captured_at=parent.captured_at, parent=parent, ip=_ip(request))
    except ce.EvidenceError as e:
        raise HTTPException(e.code, str(e))
    ce.custody(db, parent, "VERSIONED", user, f"new version {item.ref}: {note}", _ip(request))
    log_audit(db, user, "EVIDENCE_VERSION", "evidence_item", item.ref, f"of {ref}: {note}", request)
    db.commit()
    face_grouping.schedule(item.id)
    return item_out(db, item)


class DeleteBody(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/evidence-items/{ref}/delete")
def soft_delete(ref: str, body: DeleteBody, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    i = _item(db, ref, admin)
    if i.deleted_at:
        raise HTTPException(409, "Already deleted")
    i.deleted_at, i.deleted_by, i.delete_reason = utcnow(), admin.id, body.reason
    ce.custody(db, i, "DELETED", admin, body.reason, _ip(request))
    log_audit(db, admin, "EVIDENCE_DELETE", "evidence_item", ref, body.reason, request)
    db.commit()
    return item_out(db, i)


@router.get("/evidence-items/{ref}/verify")
def verify(ref: str, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    i = _item(db, ref, user)
    res = ce.verify_chain(db, i)
    ce.custody(db, i, "VERIFIED", user, json.dumps(res), _ip(request))
    db.commit()
    return res


# ——— faces & person folders ———

def group_out(db: Session, g: PersonGroup, counts: Optional[dict] = None) -> dict:
    faces = counts.get(g.id) if counts is not None else db.query(EvidenceFace).filter(EvidenceFace.group_id == g.id).count()
    kp = db.get(KnownPerson, g.known_person_id) if g.known_person_id else None
    cams = {c for (c,) in db.query(EvidenceItem.camera_id).join(EvidenceFace, EvidenceFace.item_id == EvidenceItem.id)
            .filter(EvidenceFace.group_id == g.id, EvidenceItem.camera_id.isnot(None))}
    locs = {loc for (loc,) in db.query(EvidenceItem.location).join(EvidenceFace, EvidenceFace.item_id == EvidenceItem.id)
            .filter(EvidenceFace.group_id == g.id, EvidenceItem.location.isnot(None))}
    return {"id": g.id, "code": g.code, "name": g.name, "status": g.status,
            "criminal": {"person_id": kp.person_id, "name": kp.name} if kp else None,
            "best_face_url": f"/api/v1/evidence-faces/{g.best_face_id}/crop" if g.best_face_id else None,
            "faces": faces, "first_seen": g.first_seen, "last_seen": g.last_seen, "seen_at": sorted(cams | locs)}


@router.get("/person-groups")
def list_groups(q: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db),
                user: User = Depends(operator_or_admin)):
    vis = db.query(EvidenceFace.group_id).join(EvidenceItem).filter(EvidenceItem.incident_id.in_(_visible(db, user)),
                                                                    EvidenceItem.deleted_at.is_(None))
    query = db.query(PersonGroup).filter(PersonGroup.merged_into.is_(None), PersonGroup.id.in_(vis))
    if status:
        query = query.filter(PersonGroup.status == status)
    if q:
        query = query.filter(or_(PersonGroup.code.ilike(f"%{q}%"), PersonGroup.name.ilike(f"%{q}%")))
    from sqlalchemy import func
    counts = dict(db.query(EvidenceFace.group_id, func.count(EvidenceFace.id)).group_by(EvidenceFace.group_id).all())
    return [group_out(db, g, counts) for g in query.order_by(PersonGroup.last_seen.desc()).limit(300)]


@router.get("/person-groups/{gid}")
def get_group(gid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    g = db.get(PersonGroup, gid)
    if not g or g.merged_into:
        raise HTTPException(404, "Folder not found")
    visible = {r[0] for r in _visible(db, user)}
    faces = []
    for f in db.query(EvidenceFace).filter(EvidenceFace.group_id == gid).order_by(EvidenceFace.id):
        it = db.get(EvidenceItem, f.item_id)
        if it.incident_id not in visible or it.deleted_at:
            continue
        faces.append({"id": f.id, "crop_url": f"/api/v1/evidence-faces/{f.id}/crop", "item_ref": it.ref, "incident_id": it.incident_id,
                      "kind": it.kind, "frame_ts": f.frame_ts, "at": it.captured_at or it.uploaded_at, "location": it.location,
                      "camera_id": it.camera_id, "similarity": f.group_similarity, "watch_similarity": f.watch_similarity,
                      "verify_status": f.verify_status})
    log_audit(db, user, "PERSON_GROUP_VIEW", "person_group", str(gid), "", request)
    db.commit()
    return {**group_out(db, g), "items": faces, "incidents": sorted({f["incident_id"] for f in faces})}


@router.get("/evidence-faces/{fid}/crop")
def face_crop(fid: int, db: Session = Depends(get_db), viewer: User = Depends(viewer_dep)):
    f = db.get(EvidenceFace, fid)
    if not f:
        raise HTTPException(404, "Face not found")
    _item(db, db.get(EvidenceItem, f.item_id).ref, viewer)
    return Response(content=unseal(f.crop, f.crop_encrypted), media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


def _op(db: Session, user: User, op: str, details: dict, request: Request):
    db.add(GroupOperation(op=op, actor_id=user.id, actor=user.username, details=json.dumps(details, default=str)))
    log_audit(db, user, f"PERSON_GROUP_{op.upper()}", "person_group", str(details.get("target") or details.get("group") or ""),
              json.dumps(details, default=str), request)


GROUP_EDIT_ROLES = ("operator", "investigator", "supervisor", "admin", "police")


class GroupPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    status: Optional[str] = Field(default=None, pattern="^(unknown|named|known)$")
    link_person_id: Optional[str] = None        # link to a criminal profile (pending verification)


@router.patch("/person-groups/{gid}")
def edit_group(gid: int, body: GroupPatch, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if user.role not in GROUP_EDIT_ROLES:
        raise HTTPException(403, "Read-only role")
    g = db.get(PersonGroup, gid)
    if not g or g.merged_into:
        raise HTTPException(404, "Folder not found")
    ch = body.model_dump(exclude_unset=True)
    if "name" in ch:
        g.name = (ch["name"] or "").strip() or None
        if g.status == "unknown" and g.name:
            g.status = "named"
    if ch.get("status"):
        g.status = ch["status"]
    if ch.get("link_person_id"):
        kp = db.query(KnownPerson).filter(KnownPerson.person_id == ch["link_person_id"]).first()
        if not kp:
            raise HTTPException(400, "Person not found")
        g.known_person_id, g.status = kp.id, "criminal_possible"
    _op(db, user, "rename" if "name" in ch else "link", {"group": gid, **ch}, request)
    db.commit()
    return group_out(db, g)


class MergeBody(BaseModel):
    target_id: int
    source_ids: List[int] = Field(min_length=1, max_length=50)


@router.post("/person-groups/merge")
def merge_groups(body: MergeBody, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if user.role not in GROUP_EDIT_ROLES:
        raise HTTPException(403, "Read-only role")
    target = db.get(PersonGroup, body.target_id)
    sources = [db.get(PersonGroup, s) for s in body.source_ids]
    if not target or target.merged_into or any(s is None or s.merged_into for s in sources):
        raise HTTPException(404, "Folder not found")
    crim = {s.known_person_id for s in sources + [target] if s.known_person_id}
    if len(crim) > 1:
        raise HTTPException(409, "These folders are linked to different criminal profiles")
    n = face_grouping.merge(db, target, sources)
    _op(db, user, "merge", {"target": target.id, "sources": body.source_ids, "faces": n}, request)
    db.commit()
    return group_out(db, target)


class MoveBody(BaseModel):
    face_ids: List[int] = Field(min_length=1, max_length=500)
    target_id: Optional[int] = None             # None = split into a new folder


@router.post("/person-groups/move")
def move_faces(body: MoveBody, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """Move faces to another folder, or (no target) split them into a new one."""
    if user.role not in GROUP_EDIT_ROLES:
        raise HTTPException(403, "Read-only role")
    faces = db.query(EvidenceFace).filter(EvidenceFace.id.in_(body.face_ids)).all()
    if len(faces) != len(set(body.face_ids)):
        raise HTTPException(404, "Face not found")
    if body.target_id:
        target = db.get(PersonGroup, body.target_id)
        if not target or target.merged_into:
            raise HTTPException(404, "Folder not found")
        op = "move"
    else:
        target = PersonGroup(code=face_grouping._next_code(db), status="unknown")
        db.add(target)
        db.flush()
        op = "split"
    origins = {f.group_id for f in faces}
    for f in faces:
        f.group_id = target.id
        if target.best_face_id is None:
            target.best_face_id = f.id
    for gid in origins:                    # keep a valid thumbnail on the folders left behind
        g = db.get(PersonGroup, gid)
        if g and (g.best_face_id in body.face_ids):
            left = db.query(EvidenceFace.id).filter(EvidenceFace.group_id == gid).first()
            g.best_face_id = left[0] if left else None
    _op(db, user, op, {"target": target.id, "faces": body.face_ids, "from": sorted(origins)}, request)
    db.commit()
    return group_out(db, target)


class VerifyBody(BaseModel):
    decision: str = Field(pattern="^(confirm|reject)$")
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/evidence-faces/{fid}/verify")
def verify_face(fid: int, body: VerifyBody, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """Officer decision on a 'possible criminal match' in evidence. Rejected faces leave the
    criminal's folder for a folder of their own."""
    if user.role not in GROUP_EDIT_ROLES:
        raise HTTPException(403, "Read-only role")
    f = db.get(EvidenceFace, fid)
    if not f or f.verify_status != "pending":
        raise HTTPException(409, "Nothing to verify on this face")
    _item(db, db.get(EvidenceItem, f.item_id).ref, user)
    f.verify_status, f.verified_by, f.verified_at = ("confirmed" if body.decision == "confirm" else "rejected"), user.id, utcnow()
    g = db.get(PersonGroup, f.group_id)
    if body.decision == "confirm" and g:
        g.status = "criminal"
    elif g:
        ng = PersonGroup(code=face_grouping._next_code(db), status="unknown", first_seen=g.first_seen, last_seen=g.last_seen,
                         best_face_id=f.id)
        db.add(ng)
        db.flush()
        f.group_id = ng.id
    _op(db, user, "verify", {"face": fid, "decision": body.decision, "note": body.note, "group": g.id if g else None}, request)
    db.commit()
    return {"face_id": fid, "verify_status": f.verify_status, "group_id": f.group_id}
