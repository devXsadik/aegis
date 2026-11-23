"""Review queue, datasets (split / freeze / version / export) and model registry (spec 7.4)."""
import io
import json
import os
import uuid
import zipfile
from datetime import timedelta

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.models.alert import Alert
from backend.models.detection import Detection
from backend.models.user import User
from backend.utils.at_rest import seal
from clock import utcnow

client = TestClient(app)
R = uuid.uuid4().hex[:6]


def _user(name, role):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"), role=role, is_active=True)
    db.add(u)
    db.commit()
    tok = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {tok}"}


def img(seed, color=None):
    a = np.random.default_rng(seed).integers(0, 255, (64, 96, 3), dtype=np.uint8)
    if color:
        a[20:50, 10:86] = color
    return cv2.imencode(".jpg", a)[1].tobytes()


@pytest.fixture(scope="module")
def u():
    return {"ml": _user(f"ml_{R}", "ml_engineer"), "op": _user(f"mlop_{R}", "operator"), "admin": _user(f"mladm_{R}", "admin")}


def test_rejected_match_and_correction_feed_the_review_queue(u):
    db = SessionLocal()
    blob, enc = seal(img(1))
    det = Detection(event_id=f"ml-{R}", camera_id="c", ts=utcnow(), kind="vehicle", crop=blob, crop_encrypted=enc,
                    color="grey", vehicle_type="car", expires_at=utcnow() + timedelta(days=1))
    db.add(det)
    db.flush()
    a = Alert(alert_type="VEHICLE_MATCH", severity="high", camera_id="c", timestamp=utcnow(), review_status="pending",
              details=json.dumps({"detection_id": det.id, "watch": {"ref": "V-TEST"}, "match": {"score": 0.7}}))
    db.add(a)
    db.commit()
    aid, did = a.id, det.id
    db.close()
    client.put(f"/api/v1/alerts/{aid}/acknowledge", headers=u["op"], json={"acknowledged": False, "dismissed": True, "note": "Different car"})
    q = client.get("/api/v1/ml/review-queue", headers=u["ml"]).json()
    rej = next(x for x in q if x["alert_id"] == aid)
    assert rej["reason"] == "rejected_match" and rej["predicted"] == "V-TEST" and rej["image_url"]
    r = client.post("/api/v1/ml/review-queue", headers=u["op"], json={"detection_id": did, "field": "color", "corrected": "white"})
    assert r.status_code == 201
    q = client.get("/api/v1/ml/review-queue", headers=u["ml"]).json()
    corr = next(x for x in q if x["reason"] == "correction" and x["corrected"] == "white")
    assert corr["predicted"] == "grey"
    assert client.get("/api/v1/ml/review-queue", headers=u["op"]).status_code == 403          # operators feed, don't browse
    assert client.get(f"/api/v1/ml/review-queue/{corr['id']}/image", headers=u["ml"]).status_code == 200
    pytest.shared = {"corr": corr["id"]}


def test_dataset_lifecycle(u):
    h = u["ml"]
    d = client.post("/api/v1/ml/datasets", headers=h, json={"name": f"attrs-{R}", "task": "vehicle_attr"}).json()
    files = [("files", (f"{i}.jpg", img(i), "image/jpeg")) for i in range(10, 22)]
    labels = [{"vehicle_type": "car" if i % 2 else "bus", "color": "white" if i % 3 else "red"} for i in range(12)]
    r = client.post(f"/api/v1/ml/datasets/{d['id']}/items", headers=h, files=files[:6], data={"labels": json.dumps(labels[0])}).json()
    assert r["added"] == 6
    client.post(f"/api/v1/ml/datasets/{d['id']}/items", headers=h, files=files[6:], data={"labels": json.dumps(labels[1])})
    dup = client.post(f"/api/v1/ml/datasets/{d['id']}/items", headers=h, files=files[:1]).json()
    assert dup["added"] == 0 and "already" in dup["skipped"][0]["error"]
    added = client.post(f"/api/v1/ml/datasets/{d['id']}/from-review", headers=h, json={"review_ids": [pytest.shared["corr"]]}).json()
    assert added["added"] == 1
    assert client.post(f"/api/v1/ml/datasets/{d['id']}/freeze", headers=h).status_code == 400          # not split yet
    s = client.post(f"/api/v1/ml/datasets/{d['id']}/split", headers=h, json={"train": 0.6, "val": 0.2, "test": 0.2, "seed": 7}).json()
    assert sum(s["counts"].values()) == 13 and set(s["counts"]) <= {"train", "val", "test"}
    bal = s["balance"]
    assert "vehicle_type" in bal["fields"] and bal["total"] == 13
    assert client.post(f"/api/v1/ml/datasets/{d['id']}/freeze", headers=h).json()["status"] == "frozen"
    assert client.post(f"/api/v1/ml/datasets/{d['id']}/items", headers=h, files=files[:1]).status_code == 409
    v2 = client.post(f"/api/v1/ml/datasets/{d['id']}/versions", headers=h).json()
    assert v2["version"] == 2 and v2["status"] == "draft" and v2["items"] == 13
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/v1/ml/datasets/{d['id']}/export?fmt=attributes", headers=h).content))
    names = z.namelist()
    assert "labels.csv" in names and "classes.json" in names and sum(n.startswith("images/") for n in names) == 13
    assert "white" in z.read("labels.csv").decode()
    assert client.get("/api/v1/ml/datasets", headers=u["op"]).status_code == 403


def test_detector_export_yolo(u):
    h = u["ml"]
    d = client.post("/api/v1/ml/datasets", headers=h, json={"name": f"det-{R}", "task": "vehicle_detect"}).json()
    client.post(f"/api/v1/ml/datasets/{d['id']}/items", headers=h, files=[("files", ("a.jpg", img(40), "image/jpeg"))],
                data={"labels": json.dumps({"boxes": [{"cls": "cng", "x": 0.5, "y": 0.5, "w": 0.4, "h": 0.3}]})})
    client.post(f"/api/v1/ml/datasets/{d['id']}/split", headers=h, json={"train": 1, "val": 0, "test": 0})
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/v1/ml/datasets/{d['id']}/export?fmt=yolo", headers=h).content))
    lbl = [n for n in z.namelist() if n.startswith("labels/train/")][0]
    assert z.read(lbl).decode() == "0 0.500000 0.500000 0.400000 0.300000"
    assert 'names: ["cng"]' in z.read("data.yaml").decode()
    coco = json.loads(zipfile.ZipFile(io.BytesIO(client.get(f"/api/v1/ml/datasets/{d['id']}/export?fmt=coco", headers=h).content)).read("annotations.json"))
    assert coco["annotations"][0]["category_id"] == 1


def test_registry_promote_and_rollback(u):
    h = u["ml"]
    live = os.environ["AEGIS_MODELS_DIR"]

    def reg(version, payload):
        return client.post("/api/v1/ml/models", headers=h, data={"task": "vehicle_reid", "name": "reid-resnet50", "version": version,
                                                                   "metrics": json.dumps({"rank1": 0.8, "mAP": 0.6})},
                           files={"file": ("m.onnx", payload, "application/octet-stream")}).json()
    a = reg(f"1.0-{R}", b"model-A")
    b = reg(f"1.1-{R}", b"model-B")
    assert a["stage"] == "staging" and a["metrics"]["rank1"] == 0.8
    assert client.post("/api/v1/ml/models", headers=h, data={"task": "vehicle_reid", "name": "x", "version": f"1.0-{R}"},
                       files={"file": ("m.onnx", b"x")}).status_code == 409
    client.post(f"/api/v1/ml/models/{a['id']}/promote", headers=h)
    assert open(os.path.join(live, "vehicle_reid.onnx"), "rb").read() == b"model-A"
    out = client.post(f"/api/v1/ml/models/{b['id']}/promote", headers=h).json()
    assert out["promoted"]["stage"] == "production" and out["archived"]["id"] == a["id"]
    assert open(os.path.join(live, "vehicle_reid.onnx"), "rb").read() == b"model-B"
    back = client.post("/api/v1/ml/models/rollback?task=vehicle_reid", headers=h).json()
    assert back["id"] == a["id"] and back["stage"] == "production"
    assert open(os.path.join(live, "vehicle_reid.onnx"), "rb").read() == b"model-A"
    stages = {m["id"]: m["stage"] for m in client.get("/api/v1/ml/models?task=vehicle_reid", headers=h).json()}
    assert stages[b["id"]] == "archived"
    assert client.post(f"/api/v1/ml/models/{a['id']}/promote", headers=u["op"]).status_code == 403
    logs = client.get("/api/v1/audit/?action=MODEL_PROMOTE", headers=u["admin"]).json()
    assert len(logs) >= 2
