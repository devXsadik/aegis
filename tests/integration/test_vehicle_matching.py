"""End-to-end vehicle matching: ingest → score → alert, lookouts, search with audit."""
import base64
import json
import uuid
from datetime import timedelta

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.models.alert import Alert
from backend.models.bolo import Bolo, BoloCamera
from backend.models.user import User
from clock import utcnow

client = TestClient(app)
RUN = uuid.uuid4().hex[:6]
KEY = {"X-Internal-Key": "test-internal-key-for-ci"}


def _user(name, role):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == name).first()
    if not u:
        u = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"), role=role, is_active=True)
        db.add(u)
        db.commit()
    tok = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {tok}"}


def car_jpeg(bgr):
    img = np.full((100, 160, 3), 90, np.uint8)
    img[10:45, 20:140] = (30, 30, 30)
    img[45:85, 10:150] = bgr
    return cv2.imencode(".jpg", img)[1].tobytes()


def _legal():
    now = utcnow()
    return {"case_no": "FIR-9", "legal_basis": "Court order 1/2026 for vehicle tracing",
            "issuing_authority": "DMP", "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(days=5)).isoformat()}


@pytest.fixture(scope="module")
def setup(monkeypatch_module=None):
    import os
    os.environ["ALERT_DEDUPE_SECONDS"] = "0"
    admin, op, sup = _user(f"vm_admin_{RUN}", "admin"), _user(f"vm_op_{RUN}", "operator"), _user(f"vm_sup_{RUN}", "supervisor")
    cams = [f"vm_a_{RUN}", f"vm_b_{RUN}"]
    for c in cams:
        assert client.post("/api/v1/cameras/", headers=admin, json={"camera_id": c, "name": c, "lat": 23.79, "lng": 90.41}).status_code == 200
    plate = f"Dhaka Metro Ga {RUN[:2].translate(str.maketrans('abcdef', '123456'))}-{(abs(hash(RUN)) % 9000) + 1000}"
    v = client.post("/api/v1/watchlist/vehicles", headers=op, json={**_legal(), "plate": plate, "vehicle_type": "car",
                                                                      "color_primary": "white", "make_model": "toyota_axio"}).json()
    client.post(f"/api/v1/watchlist/vehicles/{v['ref']}/photos", headers=op,
                files={"file": ("car.jpg", car_jpeg((245, 245, 245)), "image/jpeg")})
    assert client.post(f"/api/v1/watchlist/vehicles/{v['ref']}/approve", headers=sup, json={}).json()["status"] == "active"
    return {"admin": admin, "op": op, "cams": cams, "plate": plate, "ref": v["ref"]}


def _ingest(cam, **ev):
    r = client.post(f"/api/v1/ingest/generic/{cam}", headers=KEY, json={"type": "vehicle", **ev})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]["results"]


def _alert(alert_id):
    db = SessionLocal()
    a = db.get(Alert, alert_id)
    db.close()
    return a


def test_exact_plate_and_attributes_is_critical_and_needs_review(setup):
    res = _ingest(setup["cams"][0], plate_text=setup["plate"], vehicle_type="car", color="white",
                  make_model="Toyota Axio", attribute_confidences={"plate": 0.95, "type": 0.9, "color": 0.9, "model": 0.8},
                  direction="N")
    assert res[0]["level"] == "confirmed" and res[0]["severity"] == "critical"
    a = _alert(res[0]["alert_id"])
    d = json.loads(a.details)
    assert a.alert_type == "VEHICLE_MATCH" and a.review_status == "pending"
    assert d["match"]["label"] == "Confirmed vehicle match" and d["watch"]["ref"] == setup["ref"] and d["direction"] == "N"
    assert {c["attribute"]: c["result"] for c in d["match"]["checks"]}["model"] == "match"


def test_plate_on_wrong_vehicle_is_flagged(setup):
    res = _ingest(setup["cams"][1], plate_text=setup["plate"], vehicle_type="pickup", color="white",
                  attribute_confidences={"plate": 0.95, "type": 0.9, "color": 0.9})
    assert res[0]["level"] == "plate_mismatch" and "swapped" in json.loads(_alert(res[0]["alert_id"]).details)["match"]["label"]


def test_attribute_only_needs_a_lookout(setup):
    crop = base64.b64encode(car_jpeg((240, 240, 240))).decode()
    ev = dict(vehicle_type="car", color="white", make_model="Toyota Axio", crop_image=crop,
              attribute_confidences={"type": 0.9, "color": 0.9, "model": 0.9})
    assert _ingest(setup["cams"][0], **ev) == []                      # nationwide: suppressed
    db = SessionLocal()
    b = Bolo(ref=f"B-{RUN}", kind="vehicle", target_ref=setup["ref"], window_start=utcnow() - timedelta(minutes=1),
             window_end=utcnow() + timedelta(minutes=30), status="active")
    b.cameras.append(BoloCamera(camera_id=setup["cams"][0], rank=0))
    db.add(b)
    db.commit()
    db.close()
    res = _ingest(setup["cams"][0], **ev)
    assert res and res[0]["level"] == "candidate" and res[0]["severity"] == "medium"
    assert _ingest(setup["cams"][1], **ev) == []                      # the other camera is not on the lookout


def test_baseline_fills_attributes_from_crop(setup):
    crop = base64.b64encode(car_jpeg((245, 245, 245))).decode()
    res = _ingest(setup["cams"][1], plate_text=setup["plate"], crop_image=crop, attribute_confidences={"plate": 0.95},
                  extra={"detector_class": "car"})
    assert res[0]["level"] in ("confirmed", "plate_mismatch")
    from backend.models.detection import Detection
    db = SessionLocal()
    d = db.query(Detection).filter(Detection.alert_id == res[0]["alert_id"]).first()
    assert d.color == "white" and d.embedding is not None and d.matched
    db.close()


def test_search_requires_reason_and_is_audited(setup):
    op = setup["op"]
    assert client.get("/api/v1/vehicle-search?color=white", headers=op).status_code == 422          # no reason
    assert client.get("/api/v1/vehicle-search?reason=FIR-9 tracing", headers=op).status_code == 400  # no criteria
    digits = setup["plate"].split()[-1]
    r = client.get(f"/api/v1/vehicle-search?reason=FIR-9 tracing&plate={digits}", headers=op).json()
    assert r["total"] >= 1 and all(i["plate_canonical"] for i in r["items"])
    r2 = client.get(f"/api/v1/vehicle-search?reason=FIR-9 tracing&color=white&vehicle_type=car&camera_id={setup['cams'][0]}", headers=op).json()
    assert r2["total"] >= 1 and all(i["camera_id"] == setup["cams"][0] for i in r2["items"])
    logs = client.get("/api/v1/audit/?action=VEHICLE_SEARCH", headers=setup["admin"]).json()
    assert "FIR-9 tracing" in logs[0]["details"]
    photo = client.post("/api/v1/vehicle-search/photo", headers=op, data={"reason": "FIR-9 photo search"},
                        files={"file": ("q.jpg", car_jpeg((245, 245, 245)), "image/jpeg")}).json()
    assert photo["items"] and photo["items"][0]["similarity"] > 0.8
    assert client.get("/api/v1/vehicle-search?reason=xxxxx&color=white", headers=_user(f"vm_pol_{RUN}", "police")).status_code == 403


def test_match_config_admin_only(setup):
    cfg = client.get("/api/v1/vehicle-match/config", headers=setup["op"]).json()
    assert cfg["config"]["weights"]["plate"] == 0.55
    assert client.put("/api/v1/vehicle-match/config", headers=setup["op"], json={"reid_threshold": 0.6}).status_code == 403
    assert client.put("/api/v1/vehicle-match/config", headers=setup["admin"], json={"reid_threshold": 2}).status_code == 400
    ok = client.put("/api/v1/vehicle-match/config", headers=setup["admin"], json={"reid_threshold": 0.7}).json()
    assert ok["config"]["reid_threshold"] == 0.7


def test_manual_lookout_by_area_boosts_cameras_and_enables_candidates(setup):
    from backend.models.camera import Camera
    op = setup["op"]
    assert client.post("/api/v1/lookouts", headers=op, json={"reason": "FIR-9", "vehicle_type": "car"}).status_code == 400
    assert client.post("/api/v1/lookouts", headers=op, json={"reason": "FIR-9 lookout", "vehicle_type": "car",
                                                             "color_primary": "white"}).status_code == 400   # no cameras
    b = client.post("/api/v1/lookouts", headers=op, json={"reason": "FIR-9 lookout", "vehicle_type": "car", "color_primary": "white",
                                                          "make_model": "toyota_axio", "camera_ids": [setup["cams"][1]], "hours": 2}).json()
    assert b["status"] == "active" and [c["camera_id"] for c in b["cameras"]] == [setup["cams"][1]]
    db = SessionLocal()
    assert db.query(Camera).filter(Camera.camera_id == setup["cams"][1]).first().priority == 5
    db.close()
    res = _ingest(setup["cams"][1], vehicle_type="car", color="white", make_model="Toyota Axio",
                  attribute_confidences={"type": 0.9, "color": 0.9, "model": 0.9})
    assert any(r["level"] == "candidate" for r in res)
    assert [x["ref"] for x in client.get("/api/v1/lookouts", headers=op).json()].count(b["ref"]) == 1
    done = client.post(f"/api/v1/lookouts/{b['ref']}/cancel", headers=op).json()
    assert done["status"] == "cancelled"
    db = SessionLocal()
    assert db.query(Camera).filter(Camera.camera_id == setup["cams"][1]).first().priority == 0
    db.close()
    assert client.post(f"/api/v1/lookouts/{b['ref']}/cancel", headers=op).status_code == 409
