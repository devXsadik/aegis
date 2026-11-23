"""Datasets, model registry and review queue — ML engineers and admins (spec 7.4).
Operators feed the review queue (corrections, rejected matches) but cannot see datasets."""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.auth import ml_or_admin, operator_or_admin
from backend.db.database import get_db
from backend.models.ml import Dataset, DatasetItem, ModelVersion, ReviewQueueItem, TASKS
from backend.models.user import User
from backend.services import ml
from backend.services.audit import log_audit

router = APIRouter(prefix="/ml", tags=["ml"])
MAX_IMAGE = 15 * 1024 * 1024


def _err(e: ml.MLError):
    raise HTTPException(e.code, str(e))


def _ds(db: Session, did: int) -> Dataset:
    d = db.get(Dataset, did)
    if not d:
        raise HTTPException(404, "Dataset not found")
    return d


def ds_out(d: Dataset) -> dict:
    labelled = sum(1 for i in d.items if json.loads(i.labels or "{}"))
    return {"id": d.id, "name": d.name, "task": d.task, "version": d.version, "status": d.status, "items": len(d.items),
            "labelled": labelled, "split_seed": d.split_seed, "notes": d.notes, "created_at": d.created_at,
            "frozen_at": d.frozen_at, "parent_id": d.parent_id}


def item_out(i: DatasetItem) -> dict:
    return {"id": i.id, "split": i.split, "day_night": i.day_night, "source": i.source, "labels": json.loads(i.labels or "{}"),
            "width": i.width, "height": i.height, "image_url": f"/api/v1/ml/items/{i.id}/image"}


# ——— review queue (operators add, ML engineers use) ———

class Correction(BaseModel):
    detection_id: int
    field: str
    corrected: str = Field(min_length=1, max_length=80)
    note: Optional[str] = Field(default=None, max_length=300)


@router.post("/review-queue", status_code=201)
def add_correction(body: Correction, request: Request, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if user.role not in ("operator", "supervisor", "admin", "investigator"):
        raise HTTPException(403, "Your role cannot correct detections")
    try:
        r = ml.add_correction(db, body.detection_id, body.field, body.corrected, user.id, body.note)
    except ml.MLError as e:
        _err(e)
    log_audit(db, user, "DETECTION_CORRECTION", "detection", str(body.detection_id), f"{body.field}: {r.predicted} → {body.corrected}", request)
    db.commit()
    return {"id": r.id}


@router.get("/review-queue")
def review_queue(status: str = "open", db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    rows = db.query(ReviewQueueItem).filter(ReviewQueueItem.status == status).order_by(ReviewQueueItem.id.desc()).limit(300)
    return [{"id": r.id, "kind": r.kind, "reason": r.reason, "field": r.field, "predicted": r.predicted, "corrected": r.corrected,
             "note": r.note, "alert_id": r.alert_id, "day_night": r.day_night, "score": r.score, "created_at": r.created_at,
             "status": r.status, "image_url": f"/api/v1/ml/review-queue/{r.id}/image" if r.crop else None} for r in rows]


@router.get("/review-queue/{rid}/image")
def review_image(rid: int, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    r = db.get(ReviewQueueItem, rid)
    data = ml.crop_of(r) if r else None
    if not data:
        raise HTTPException(404, "No image")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.post("/review-queue/{rid}/dismiss")
def dismiss(rid: int, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    r = db.get(ReviewQueueItem, rid)
    if not r:
        raise HTTPException(404, "Not found")
    r.status = "dismissed"
    db.commit()
    return {"id": rid, "status": r.status}


# ——— datasets ———

class DatasetIn(BaseModel):
    name: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_\-. ]+$")
    task: str
    notes: Optional[str] = Field(default=None, max_length=1000)


@router.get("/datasets")
def datasets(db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    return [ds_out(d) for d in db.query(Dataset).order_by(Dataset.name, Dataset.version.desc())]


@router.post("/datasets", status_code=201)
def create_dataset(body: DatasetIn, request: Request, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    if body.task not in TASKS:
        raise HTTPException(400, f"task must be one of {', '.join(TASKS)}")
    if db.query(Dataset).filter(Dataset.name == body.name).first():
        raise HTTPException(409, "A dataset with this name exists: add a version instead")
    d = Dataset(name=body.name, task=body.task, version=1, notes=body.notes, created_by=user.id)
    db.add(d)
    db.flush()
    log_audit(db, user, "DATASET_CREATE", "dataset", str(d.id), f"{body.name} ({body.task})", request)
    db.commit()
    return ds_out(d)


@router.get("/datasets/{did}")
def dataset(did: int, split: Optional[str] = None, unlabelled: bool = False, db: Session = Depends(get_db),
            user: User = Depends(ml_or_admin)):
    d = _ds(db, did)
    items = [i for i in d.items if (not split or i.split == split) and (not unlabelled or not json.loads(i.labels or "{}"))]
    return {**ds_out(d), "balance": ml.balance(d), "items_list": [item_out(i) for i in items[:500]]}


@router.post("/datasets/{did}/items")
async def add_items(did: int, request: Request, files: List[UploadFile] = File(...), crop_vehicles: bool = Form(False),
                    labels: Optional[str] = Form(None), db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    """Images (or road scenes with crop_vehicles=true: every detected vehicle becomes an item)."""
    d = _ds(db, did)
    try:
        ml.editable(d)
        lab = json.loads(labels) if labels else None
    except ml.MLError as e:
        _err(e)
    except ValueError:
        raise HTTPException(400, "labels must be JSON")
    added, skipped = 0, []
    for f in files:
        data = await f.read()
        if len(data) > MAX_IMAGE:
            skipped.append({"file": f.filename, "error": "larger than 15 MB"})
            continue
        chunks = ml.vehicle_crops(data) if crop_vehicles else [data]
        for c in chunks:
            try:
                ml.add_image(db, d, c, labels=lab, source="crop" if crop_vehicles else "upload", user_id=user.id)
                added += 1
            except ml.MLError as e:
                skipped.append({"file": f.filename, "error": str(e)})
    log_audit(db, user, "DATASET_ADD", "dataset", str(did), f"{added} item(s)", request)
    db.commit()
    return {"added": added, "skipped": skipped}


class LabelBody(BaseModel):
    labels: dict


@router.put("/items/{iid}/labels")
def label(iid: int, body: LabelBody, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    from clock import utcnow
    it = db.get(DatasetItem, iid)
    if not it:
        raise HTTPException(404, "Item not found")
    try:
        ml.editable(it.dataset)
    except ml.MLError as e:
        _err(e)
    it.labels, it.labeled_by, it.labeled_at = json.dumps(body.labels, ensure_ascii=False), user.id, utcnow()
    db.commit()
    return item_out(it)


@router.get("/items/{iid}/image")
def item_image(iid: int, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    it = db.get(DatasetItem, iid)
    if not it:
        raise HTTPException(404, "Item not found")
    with open(it.path, "rb") as fh:
        return Response(content=fh.read(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


class SplitBody(BaseModel):
    train: float = 0.8
    val: float = 0.1
    test: float = 0.1
    seed: int = 13


@router.post("/datasets/{did}/split")
def do_split(did: int, body: SplitBody, request: Request, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    d = _ds(db, did)
    try:
        counts = ml.split(db, d, (body.train, body.val, body.test), body.seed)
    except ml.MLError as e:
        _err(e)
    log_audit(db, user, "DATASET_SPLIT", "dataset", str(did), json.dumps(counts), request)
    db.commit()
    return {"counts": counts, "balance": ml.balance(d)}


@router.post("/datasets/{did}/freeze")
def do_freeze(did: int, request: Request, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    d = _ds(db, did)
    try:
        ml.freeze(db, d)
    except ml.MLError as e:
        _err(e)
    log_audit(db, user, "DATASET_FREEZE", "dataset", str(did), f"{d.name} v{d.version}", request)
    db.commit()
    return ds_out(d)


@router.post("/datasets/{did}/versions", status_code=201)
def do_version(did: int, request: Request, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    nd = ml.new_version(db, _ds(db, did), user.id)
    log_audit(db, user, "DATASET_VERSION", "dataset", str(nd.id), f"{nd.name} v{nd.version}", request)
    db.commit()
    return ds_out(nd)


class FromReview(BaseModel):
    review_ids: List[int] = Field(min_length=1, max_length=500)


@router.post("/datasets/{did}/from-review")
def do_from_review(did: int, body: FromReview, request: Request, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    d = _ds(db, did)
    try:
        ml.editable(d)
    except ml.MLError as e:
        _err(e)
    n = ml.from_review(db, d, db.query(ReviewQueueItem).filter(ReviewQueueItem.id.in_(body.review_ids)).all(), user.id)
    log_audit(db, user, "DATASET_FROM_REVIEW", "dataset", str(did), f"{n} item(s)", request)
    db.commit()
    return {"added": n}


@router.get("/datasets/{did}/export")
def do_export(did: int, request: Request, fmt: str = Query(pattern="^(yolo|coco|attributes|reid)$"),
              db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    d = _ds(db, did)
    try:
        data = ml.export(d, fmt)
    except ml.MLError as e:
        _err(e)
    log_audit(db, user, "DATASET_EXPORT", "dataset", str(did), fmt, request)
    db.commit()
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{d.name}_v{d.version}_{fmt}.zip"'})


# ——— model registry ———

def model_out(m: ModelVersion) -> dict:
    return {"id": m.id, "task": m.task, "name": m.name, "version": m.version, "metrics": json.loads(m.metrics or "{}"),
            "dataset_id": m.dataset_id, "format": m.format, "sha256": m.sha256, "stage": m.stage, "notes": m.notes,
            "created_at": m.created_at, "promoted_at": m.promoted_at}


@router.get("/models")
def models(task: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    q = db.query(ModelVersion)
    if task:
        q = q.filter(ModelVersion.task == task)
    return [model_out(m) for m in q.order_by(ModelVersion.task, ModelVersion.id.desc())]


@router.post("/models", status_code=201)
async def register_model(request: Request, task: str = Form(...), name: str = Form(...), version: str = Form(...),
                         metrics: str = Form("{}"), dataset_id: Optional[int] = Form(None), notes: Optional[str] = Form(None),
                         file: UploadFile = File(...), labels: Optional[UploadFile] = File(None),
                         db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    try:
        m = ml.register(db, task=task, name=name, version=version, data=await file.read(), filename=file.filename or "model.onnx",
                        metrics=json.loads(metrics), dataset_id=dataset_id, labels=(await labels.read()) if labels else None,
                        user_id=user.id, notes=notes)
    except ml.MLError as e:
        _err(e)
    except ValueError:
        raise HTTPException(400, "metrics must be JSON")
    log_audit(db, user, "MODEL_REGISTER", "model", str(m.id), f"{task} {version}", request)
    db.commit()
    return model_out(m)


@router.post("/models/{mid}/promote")
def promote(mid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    m = db.get(ModelVersion, mid)
    if not m:
        raise HTTPException(404, "Model not found")
    try:
        prev = ml.promote(db, m, user.id)
    except ml.MLError as e:
        _err(e)
    log_audit(db, user, "MODEL_PROMOTE", "model", str(mid), f"{m.task} {m.version} (replaces {prev.version if prev else '-'})", request)
    db.commit()
    return {"promoted": model_out(m), "archived": model_out(prev) if prev else None}


@router.post("/models/rollback")
def rollback(request: Request, task: str = Query(...), db: Session = Depends(get_db), user: User = Depends(ml_or_admin)):
    try:
        m = ml.rollback(db, task, user.id)
    except ml.MLError as e:
        _err(e)
    log_audit(db, user, "MODEL_ROLLBACK", "model", str(m.id), f"{task} → {m.version}", request)
    db.commit()
    return model_out(m)
