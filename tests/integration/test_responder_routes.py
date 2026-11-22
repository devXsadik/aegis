"""Responder view: which alerts an officer sees, and on my way / on scene / resolved."""

import os

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_responder_routes.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.alert import Alert  # noqa: E402
from backend.models.camera import Camera  # noqa: E402
from backend.models.camera_officer import CameraOfficer  # noqa: E402
from backend.models.incident import Incident  # noqa: E402
from backend.models.user import User  # noqa: E402
from clock import utcnow  # noqa: E402

client = TestClient(app)
API = "/api/v1/responder"


def _user(name, role="police"):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == name).first()
    if not u:
        u = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"), role=role, is_active=True)
        db.add(u)
        db.commit()
    uid, token = u.id, issue_token(u)
    db.close()
    return uid, {"Authorization": f"Bearer {token}"}


def setup_module():
    init_db()
    db = SessionLocal()
    db.query(Alert).filter(Alert.camera_id.in_(["rs_gate", "rs_yard"])).delete()
    db.query(Camera).filter(Camera.camera_id.in_(["rs_gate", "rs_yard"])).delete()
    db.add_all([Camera(camera_id="rs_gate", name="Gate", location="Gate", lat=23.8, lng=90.4, active=True),
                Camera(camera_id="rs_yard", name="Yard", location="Yard", active=True)])
    now = utcnow()
    db.add_all([
        Alert(alert_type="WEAPON_DETECTED", severity="critical", camera_id="rs_gate", camera_location="Gate", timestamp=now,
              review_status="pending"),
        Alert(alert_type="FALL_SUSPECTED", severity="high", camera_id="rs_yard", camera_location="Yard", timestamp=now),
        Alert(alert_type="ANOMALY_DETECTED", severity="medium", camera_id="rs_gate", timestamp=now),   # not serious enough
    ])
    db.commit()
    db.close()


def _mine(hdr):
    return [a for a in client.get(f"{API}/alerts", headers=hdr).json()["alerts"] if a["camera_id"] in ("rs_gate", "rs_yard")]


def test_unassigned_officer_sees_all_serious_alerts_assigned_one_only_theirs():
    _, free = _user("rs_free")
    assert sorted(a["type"] for a in _mine(free)) == ["FALL_SUSPECTED", "WEAPON_DETECTED"]
    uid, gate = _user("rs_gate_officer")
    db = SessionLocal()
    if not db.query(CameraOfficer).filter(CameraOfficer.user_id == uid).first():
        db.add(CameraOfficer(camera_id="rs_gate", user_id=uid))
        db.commit()
    db.close()
    (a,) = _mine(gate)
    assert a["type"] == "WEAPON_DETECTED" and a["maps_url"].endswith("23.8,90.4") and a["status"] is None


def test_steps_are_logged_on_the_incident_and_resolving_closes_the_loop():
    _, hdr = _user("rs_free")
    alert_id = next(a["id"] for a in _mine(hdr) if a["type"] == "WEAPON_DETECTED")
    r1 = client.post(f"{API}/alerts/{alert_id}/status", headers=hdr, json={"status": "en_route"}).json()
    assert r1["ticket_id"] and [s["status"] for s in r1["steps"]] == ["en_route"]
    client.post(f"{API}/alerts/{alert_id}/status", headers=hdr, json={"status": "on_scene", "note": "suspect left"})
    r3 = client.post(f"{API}/alerts/{alert_id}/status", headers=hdr, json={"status": "resolved"}).json()
    assert [s["status"] for s in r3["steps"]] == ["en_route", "on_scene", "resolved"]
    assert "suspect left" in r3["steps"][1]["message"]
    db = SessionLocal()
    alert = db.get(Alert, alert_id)
    inc = db.query(Incident).filter(Incident.alert_id == alert_id).first()
    assert alert.acknowledged and alert.review_status == "confirmed" and inc.status == "resolved"
    db.close()
    assert next(a for a in _mine(hdr) if a["id"] == alert_id)["status"] == "resolved"


def test_bad_status_roles_and_missing_alert():
    _, hdr = _user("rs_free")
    assert client.post(f"{API}/alerts/1/status", headers=hdr, json={"status": "napping"}).status_code == 422
    assert client.post(f"{API}/alerts/999999/status", headers=hdr, json={"status": "en_route"}).status_code == 404
    _, inv = _user("rs_investigator", "investigator")
    assert client.post(f"{API}/alerts/1/status", headers=inv, json={"status": "en_route"}).status_code == 403
    _, viewer = _user("rs_viewer", "viewer")
    assert client.get(f"{API}/alerts", headers=viewer).status_code == 403
