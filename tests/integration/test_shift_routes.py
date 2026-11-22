"""Shift log: notes, the running summary, handover and acceptance by the next operator."""

import os

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_shift_routes.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.alert import Alert  # noqa: E402
from backend.models.shift import ShiftEntry  # noqa: E402
from backend.models.user import User  # noqa: E402
from clock import utcnow  # noqa: E402

client = TestClient(app)
API = "/api/v1/shift"


def _auth(name, role="operator"):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    user = db.query(User).filter(User.username == name).first()
    if not user:
        user = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"),
                    role=role, is_active=True)
        db.add(user)
        db.commit()
    token = issue_token(user)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def setup_function():
    init_db()
    db = SessionLocal()
    db.query(ShiftEntry).delete()
    db.commit()
    db.close()


def test_notes_are_logged_newest_first_and_validated():
    day = _auth("shift_day")
    assert client.post(f"{API}/notes", headers=day, json={"text": "Gate 2 camera wobbling in the wind"}).status_code == 200
    client.post(f"{API}/notes", headers=day, json={"text": "Delivery van at loading bay", "camera_id": "dock"})
    log = client.get(f"{API}/log", headers=day).json()
    assert [e["text"] for e in log] == ["Delivery van at loading bay", "Gate 2 camera wobbling in the wind"]
    assert log[0]["camera_id"] == "dock" and log[0]["username"] == "shift_day"
    assert client.post(f"{API}/notes", headers=day, json={"text": ""}).status_code == 422
    assert client.get(f"{API}/log", headers=_auth("shift_viewer", "viewer")).status_code == 403


def test_summary_counts_this_shift_and_handover_starts_a_new_one():
    day = _auth("shift_day")
    db = SessionLocal()
    db.add(Alert(alert_type="CAMERA_TAMPER", severity="high", camera_id="sh_cam", review_status="pending",
                 timestamp=utcnow()))
    db.commit()
    db.close()
    client.post(f"{API}/notes", headers=day, json={"text": "Checked the yard"})
    s = client.get(f"{API}/summary", headers=day).json()
    assert s["tamper_alerts"] >= 1 and s["alerts_waiting"] >= 1 and s["notes"] == 1

    h = client.post(f"{API}/handover", headers=day, json={"notes": "Yard camera needs a technician"}).json()
    assert h["kind"] == "handover" and h["summary"]["notes"] == 1 and h["accepted_at"] is None
    assert client.get(f"{API}/pending", headers=day).json()["id"] == h["id"]
    assert client.get(f"{API}/summary", headers=day).json()["notes"] == 0      # a new shift started


def test_only_another_operator_accepts_and_only_once():
    day, night = _auth("shift_day"), _auth("shift_night")
    h = client.post(f"{API}/handover", headers=day, json={"notes": ""}).json()
    assert client.post(f"{API}/handover/{h['id']}/accept", headers=day).status_code == 400
    ok = client.post(f"{API}/handover/{h['id']}/accept", headers=night).json()
    assert ok["accepted_by"] == "shift_night" and ok["accepted_at"]
    assert client.post(f"{API}/handover/{h['id']}/accept", headers=night).status_code == 409
    assert client.get(f"{API}/pending", headers=night).json() is None
    assert client.post(f"{API}/handover/99999/accept", headers=night).status_code == 404
