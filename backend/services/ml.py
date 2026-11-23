"""Datasets, model registry and review queue (spec 7.4).

Datasets are versioned: a draft is edited (add images, label, split); freezing snapshots the
class lists and makes it read-only; changes after that go into a new version (a copy).
Promoting a model copies it to the live models/ folder under the name the runtime loads
(e.g. models/vehicle_attr.onnx); the previous production model becomes 'archived' and can be
rolled back to. Training files are kept as plain JPEGs (the trainers read files) in
DATASETS_DIR with owner-only permissions — it is personal data: restrict that folder."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import random
import shutil
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from backend.models.ml import Dataset, DatasetItem, ModelVersion, ReviewQueueItem
from backend.utils.at_rest import unseal
from clock import utcnow

LIVE_NAMES = {
    "vehicle_attr": ("vehicle_attr.onnx", "vehicle_attr.labels.json"),
    "vehicle_reid": ("vehicle_reid.onnx", None),
    "vehicle_detect": ("vehicle_detect.onnx", "vehicle_detect.labels.json"),
    "face": ("face_recognition_custom.onnx", None),
    # YOLO detectors the pipeline loads through Ultralytics: promote the .pt weights.
    "plate_detect": ("plate_yolo.onnx", "plate_yolo.labels.json"),
    "weapon_detect": ("weapon_yolo.onnx", "weapon_yolo.labels.json"),
}
DETECT_TASKS = ("vehicle_detect", "plate_detect", "weapon_detect")
ATTR_FIELDS = ("vehicle_type", "color", "make_model")


class MLError(ValueError):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def _dir(name: str) -> Path:
    import paths
    p = getattr(paths, name)
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p


def live_models_dir() -> Path:
    d = Path(os.getenv("AEGIS_MODELS_DIR") or Path(__file__).resolve().parents[2] / "models")
    d.mkdir(parents=True, exist_ok=True)
    return d


# ——— review queue ———

def from_rejected_alert(db: Session, alert, user_id: Optional[int], note: Optional[str]) -> Optional[ReviewQueueItem]:
    """An operator rejected a face / vehicle match: keep the crop and what was predicted."""
    from backend.models.detection import Detection
    if alert.alert_type not in ("VEHICLE_MATCH", "FACE_MATCH", "LOOKOUT_MATCH"):
        return None
    try:
        d = json.loads(alert.details or "{}")
    except ValueError:
        d = {}
    det = db.get(Detection, d.get("detection_id")) if d.get("detection_id") else None
    kind = "face" if alert.alert_type == "FACE_MATCH" else "vehicle"
    predicted = (d.get("face") or {}).get("person_id") or (d.get("watch") or {}).get("ref") or d.get("bolo")
    score = (d.get("face") or {}).get("similarity") or (d.get("match") or {}).get("score")
    item = ReviewQueueItem(kind=kind, reason="rejected_match", field="identity", predicted=predicted, corrected=None,
                           note=note, alert_id=alert.id, detection_id=det.id if det else None,
                           crop=det.crop if det else None, crop_encrypted=det.crop_encrypted if det else False,
                           day_night="night" if det is not None and not det.color_reliable else "day",
                           score=score, created_by=user_id)
    db.add(item)
    return item


def add_correction(db: Session, detection_id: int, field: str, corrected: str, user_id: int, note: Optional[str] = None) -> ReviewQueueItem:
    from backend.models.detection import Detection
    if field not in ATTR_FIELDS + ("plate",):
        raise MLError(f"field must be one of {', '.join(ATTR_FIELDS + ('plate',))}")
    det = db.get(Detection, detection_id)
    if not det:
        raise MLError("Detection not found", 404)
    predicted = {"vehicle_type": det.vehicle_type, "color": det.color, "make_model": det.make_model, "plate": det.plate_raw}[field]
    item = ReviewQueueItem(kind="vehicle", reason="correction", field=field, predicted=predicted, corrected=corrected,
                           note=note, detection_id=det.id, alert_id=det.alert_id, crop=det.crop,
                           crop_encrypted=det.crop_encrypted, day_night="day" if det.color_reliable else "night",
                           created_by=user_id)
    db.add(item)
    return item


# ——— datasets ———

def _store_image(data: bytes) -> tuple:
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise MLError("Not an image", 415)
    sha = hashlib.sha256(data).hexdigest()
    folder = _dir("DATASETS_DIR") / "images" / sha[:2]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha}.jpg"
    if not path.exists():
        cv2.imwrite(str(path), img)
    from core.analysis.vehicle_attrs import is_night
    return str(path), sha, img.shape[1], img.shape[0], ("night" if is_night(img) else "day")


def editable(ds: Dataset) -> None:
    if ds.status == "frozen":
        raise MLError("This dataset version is frozen: create a new version to change it", 409)


def add_image(db: Session, ds: Dataset, data: bytes, *, labels: Optional[dict] = None, source: str = "upload",
              user_id: Optional[int] = None) -> DatasetItem:
    editable(ds)
    path, sha, w, h, dn = _store_image(data)
    if db.query(DatasetItem).filter(DatasetItem.dataset_id == ds.id, DatasetItem.sha256 == sha).first():
        raise MLError("Image already in this dataset", 409)
    it = DatasetItem(dataset_id=ds.id, path=path, sha256=sha, width=w, height=h, day_night=dn, source=source,
                     labels=json.dumps(labels or {}, ensure_ascii=False), labeled_by=user_id if labels else None,
                     labeled_at=utcnow() if labels else None)
    db.add(it)
    db.flush()
    return it


def vehicle_crops(data: bytes, min_px: int = 48) -> List[bytes]:
    """Vehicle crops from a road image with the COCO detector (YOLO), as JPEG bytes."""
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return []
    try:
        from ultralytics import YOLO
    except ImportError:
        return []
    weights = live_models_dir() / "yolov8s.pt"
    model = YOLO(str(weights) if weights.exists() else "yolov8s.pt")
    out = []
    for r in model(img, verbose=False):
        for box, cls in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy()):
            if model.names[int(cls)] not in ("car", "bus", "truck", "motorcycle"):
                continue
            x1, y1, x2, y2 = (int(v) for v in box)
            if min(x2 - x1, y2 - y1) < min_px:
                continue
            out.append(cv2.imencode(".jpg", img[y1:y2, x1:x2])[1].tobytes())
    return out


def _key(it: DatasetItem, task: str) -> str:
    lab = json.loads(it.labels or "{}")
    if task == "vehicle_reid" or task == "face":
        return str(lab.get("identity") or "?")
    return str(lab.get("vehicle_type") or lab.get("color") or "?")


def split(db: Session, ds: Dataset, ratios=(0.8, 0.1, 0.1), seed: int = 13) -> Dict[str, int]:
    """Stratified by the main label so every class appears in train / val / test. Re-ID and face
    sets split by identity (an identity never appears in two splits: no leakage)."""
    editable(ds)
    if abs(sum(ratios) - 1) > 1e-6 or any(r < 0 for r in ratios):
        raise MLError("ratios must be ≥ 0 and add up to 1")
    rng = random.Random(seed)
    items = list(ds.items)
    by = defaultdict(list)
    for it in items:
        by[_key(it, ds.task)].append(it)
    if ds.task in ("vehicle_reid", "face"):
        ids = sorted(by)
        rng.shuffle(ids)
        n = len(ids)
        cut1, cut2 = round(n * ratios[0]), round(n * (ratios[0] + ratios[1]))
        for i, ident in enumerate(ids):
            s = "train" if i < cut1 else "val" if i < cut2 else "test"
            for it in by[ident]:
                it.split = s
    else:
        for group in by.values():
            rng.shuffle(group)
            n = len(group)
            cut1, cut2 = round(n * ratios[0]), round(n * (ratios[0] + ratios[1]))
            for i, it in enumerate(group):
                it.split = "train" if i < cut1 else "val" if i < cut2 else "test"
    ds.split_seed = seed
    return dict(Counter(it.split for it in items))


def balance(ds: Dataset) -> dict:
    """Counts per split for each labelled field, plus day / night, plus what is unlabelled."""
    out = {"total": len(ds.items), "unlabelled": 0, "day_night": Counter(), "splits": Counter(), "fields": defaultdict(lambda: defaultdict(Counter))}
    for it in ds.items:
        lab = json.loads(it.labels or "{}")
        out["splits"][it.split or "none"] += 1
        out["day_night"][f"{it.split or 'none'}:{it.day_night}"] += 1
        if not any(lab.get(f) for f in ATTR_FIELDS + ("identity", "boxes")):
            out["unlabelled"] += 1
        for f in ATTR_FIELDS + ("identity",):
            if lab.get(f):
                out["fields"][f][str(lab[f])][it.split or "none"] += 1
    return {"total": out["total"], "unlabelled": out["unlabelled"], "splits": dict(out["splits"]),
            "day_night": dict(out["day_night"]),
            "fields": {f: {c: dict(v) for c, v in classes.items()} for f, classes in out["fields"].items()}}


def freeze(db: Session, ds: Dataset) -> None:
    editable(ds)
    if any(it.split is None for it in ds.items):
        raise MLError("Split the dataset before freezing it")
    from backend.models.watchlist import VehicleCatalog
    ds.classes = json.dumps({k: [c.code for c in db.query(VehicleCatalog).filter(VehicleCatalog.kind == k, VehicleCatalog.active == True)]  # noqa: E712
                             for k in ("type", "color", "model")})
    ds.status, ds.frozen_at = "frozen", utcnow()


def new_version(db: Session, ds: Dataset, user_id: Optional[int]) -> Dataset:
    latest = db.query(Dataset).filter(Dataset.name == ds.name).order_by(Dataset.version.desc()).first()
    nd = Dataset(name=ds.name, task=ds.task, version=latest.version + 1, status="draft", parent_id=ds.id,
                 notes=f"From v{ds.version}", created_by=user_id)
    db.add(nd)
    db.flush()
    for it in ds.items:
        db.add(DatasetItem(dataset_id=nd.id, path=it.path, sha256=it.sha256, width=it.width, height=it.height, split=it.split,
                           day_night=it.day_night, source=it.source, labels=it.labels, labeled_by=it.labeled_by,
                           labeled_at=it.labeled_at))
    db.flush()
    return nd


def from_review(db: Session, ds: Dataset, items: Iterable[ReviewQueueItem], user_id: Optional[int]) -> int:
    n = 0
    for r in items:
        if r.status != "open" or not r.crop:
            continue
        labels = {r.field: r.corrected} if r.reason == "correction" and r.field in ATTR_FIELDS else {"negative_for": r.predicted}
        try:
            it = add_image(db, ds, unseal(r.crop, r.crop_encrypted), labels=labels, source="review", user_id=user_id)
        except MLError:
            continue
        r.status, r.dataset_item_id = "used", it.id
        n += 1
    return n


def export(ds: Dataset, fmt: str) -> bytes:
    """yolo (detector: images/ + labels/ + data.yaml), coco (detector JSON), attributes
    (images per split + labels.csv for the attribute trainer), reid (images/<split>/<identity>/)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        names: List[str] = []
        if fmt == "yolo":
            for it in ds.items:
                lab = json.loads(it.labels or "{}")
                for b in lab.get("boxes", []):
                    if b["cls"] not in names:
                        names.append(b["cls"])
            for it in ds.items:
                lab = json.loads(it.labels or "{}")
                stem = it.sha256[:16]
                z.write(it.path, f"images/{it.split}/{stem}.jpg")
                lines = [f"{names.index(b['cls'])} {b['x']:.6f} {b['y']:.6f} {b['w']:.6f} {b['h']:.6f}" for b in lab.get("boxes", [])]
                z.writestr(f"labels/{it.split}/{stem}.txt", "\n".join(lines))
            z.writestr("data.yaml", "path: .\ntrain: images/train\nval: images/val\ntest: images/test\n"
                                    f"names: {json.dumps(names)}\n")
        elif fmt == "coco":
            cats = sorted({b["cls"] for it in ds.items for b in json.loads(it.labels or "{}").get("boxes", [])})
            coco = {"images": [], "annotations": [], "categories": [{"id": i + 1, "name": c} for i, c in enumerate(cats)]}
            aid = 1
            for i, it in enumerate(ds.items, start=1):
                z.write(it.path, f"images/{it.sha256[:16]}.jpg")
                coco["images"].append({"id": i, "file_name": f"images/{it.sha256[:16]}.jpg", "width": it.width,
                                       "height": it.height, "split": it.split})
                for b in json.loads(it.labels or "{}").get("boxes", []):
                    w, h = b["w"] * it.width, b["h"] * it.height
                    coco["annotations"].append({"id": aid, "image_id": i, "category_id": cats.index(b["cls"]) + 1,
                                                "bbox": [b["x"] * it.width - w / 2, b["y"] * it.height - h / 2, w, h],
                                                "area": w * h, "iscrowd": 0})
                    aid += 1
            z.writestr("annotations.json", json.dumps(coco))
        elif fmt == "attributes":
            rows = io.StringIO()
            wr = csv.writer(rows)
            wr.writerow(["file", "split", "day_night", *ATTR_FIELDS])
            for it in ds.items:
                lab = json.loads(it.labels or "{}")
                name = f"images/{it.split}/{it.sha256[:16]}.jpg"
                z.write(it.path, name)
                wr.writerow([name, it.split, it.day_night, *(lab.get(f, "") for f in ATTR_FIELDS)])
            z.writestr("labels.csv", rows.getvalue())
            z.writestr("classes.json", ds.classes or "{}")
        elif fmt == "reid":
            for it in ds.items:
                ident = json.loads(it.labels or "{}").get("identity")
                if ident:
                    z.write(it.path, f"images/{it.split}/{ident}/{it.sha256[:16]}.jpg")
        else:
            raise MLError("fmt must be yolo, coco, attributes or reid")
        z.writestr("DATASET.json", json.dumps({"name": ds.name, "version": ds.version, "task": ds.task, "status": ds.status,
                                               "split_seed": ds.split_seed, "items": len(ds.items)}))
    return buf.getvalue()


# ——— model registry ———

def register(db: Session, *, task: str, name: str, version: str, data: bytes, filename: str, metrics: dict,
             dataset_id: Optional[int], labels: Optional[bytes], user_id: Optional[int], notes: Optional[str] = None) -> ModelVersion:
    from backend.models.ml import TASKS
    if task not in TASKS:
        raise MLError(f"task must be one of {', '.join(TASKS)}")
    if db.query(ModelVersion).filter(ModelVersion.task == task, ModelVersion.version == version).first():
        raise MLError("This version is already registered", 409)
    fmt = Path(filename).suffix.lstrip(".").lower() or "onnx"
    if fmt not in ("onnx", "pt", "engine"):
        raise MLError("Model file must be .onnx, .pt or .engine")
    folder = _dir("MODEL_STORE_DIR") / task / version
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"model.{fmt}"
    path.write_bytes(data)
    lpath = None
    if labels:
        lpath = folder / "labels.json"
        lpath.write_bytes(labels)
    m = ModelVersion(task=task, name=name, version=version, metrics=json.dumps(metrics or {}), dataset_id=dataset_id,
                     artifact_path=str(path), labels_path=str(lpath) if lpath else None, format=fmt,
                     sha256=hashlib.sha256(data).hexdigest(), stage="staging", notes=notes, created_by=user_id)
    db.add(m)
    db.flush()
    return m


def promote(db: Session, m: ModelVersion, user_id: Optional[int]) -> Optional[ModelVersion]:
    """Make `m` the production model of its task. Returns the one it replaced (now archived)."""
    if m.stage == "shadow":
        stop_shadow(db, m.task)
    if m.format != "onnx" and m.task not in DETECT_TASKS:
        raise MLError("Only ONNX models can go to production for this task (export first)")
    live_name, live_labels = LIVE_NAMES[m.task]
    if m.format != "onnx":
        live_name = live_name.replace(".onnx", f".{m.format}")
    target = live_models_dir() / live_name
    tmp = target.with_suffix(target.suffix + ".tmp")
    shutil.copyfile(m.artifact_path, tmp)
    tmp.replace(target)                     # atomic swap: running workers pick up a whole file
    if live_labels and m.labels_path:
        shutil.copyfile(m.labels_path, live_models_dir() / live_labels)
    prev = db.query(ModelVersion).filter(ModelVersion.task == m.task, ModelVersion.stage == "production",
                                         ModelVersion.id != m.id).first()
    if prev:
        prev.stage = "archived"
    m.stage, m.promoted_by, m.promoted_at = "production", user_id, utcnow()
    try:                                     # running processes reload models on next use
        from core.analysis import vehicle_attrs
        vehicle_attrs._net.cache_clear()
        vehicle_attrs._attr_labels.cache_clear()
    except Exception:
        pass
    return prev


SHADOW_TASKS = ("vehicle_attr",)


def shadow_dir() -> Path:
    d = live_models_dir() / "shadow"
    d.mkdir(parents=True, exist_ok=True)
    return d


def start_shadow(db: Session, m: ModelVersion) -> None:
    """Run `m` next to production on live traffic without using its answers. Per task, one shadow;
    the comparison (agreement with production) shows in the registry before anyone promotes."""
    if m.task not in SHADOW_TASKS:
        raise MLError(f"Shadow runs are available for: {', '.join(SHADOW_TASKS)}")
    if m.format != "onnx":
        raise MLError("Only ONNX models can run in shadow")
    if m.stage not in ("staging", "archived"):
        raise MLError(f"A {m.stage} model cannot go to shadow")
    live_name, live_labels = LIVE_NAMES[m.task]
    for other in db.query(ModelVersion).filter(ModelVersion.task == m.task, ModelVersion.stage == "shadow"):
        other.stage = "staging"
    tmp = shadow_dir() / (live_name + ".tmp")
    shutil.copyfile(m.artifact_path, tmp)
    tmp.replace(shadow_dir() / live_name)
    if live_labels and m.labels_path:
        shutil.copyfile(m.labels_path, shadow_dir() / live_labels)
    m.stage = "shadow"
    from core.analysis import shadow
    shadow.reset(m.task)
    shadow.reload()


def stop_shadow(db: Session, task: str) -> None:
    live_name, live_labels = LIVE_NAMES[task]
    for name in (live_name, live_labels):
        if name and (shadow_dir() / name).exists():
            (shadow_dir() / name).unlink()
    for m in db.query(ModelVersion).filter(ModelVersion.task == task, ModelVersion.stage == "shadow"):
        m.stage = "staging"
    from core.analysis import shadow
    shadow.reload()


def rollback(db: Session, task: str, user_id: Optional[int]) -> ModelVersion:
    prev = (db.query(ModelVersion).filter(ModelVersion.task == task, ModelVersion.stage == "archived",
                                          ModelVersion.promoted_at.isnot(None))
            .order_by(ModelVersion.promoted_at.desc()).first())
    if not prev:
        raise MLError("No earlier production model to roll back to", 409)
    promote(db, prev, user_id)
    return prev


def crop_of(r: ReviewQueueItem) -> Optional[bytes]:
    return unseal(r.crop, r.crop_encrypted) if r.crop else None

