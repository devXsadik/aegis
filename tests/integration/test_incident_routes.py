"""Incidents: open (by hand or from an alert), list, change, note, resolve, close."""

import os

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_incident_routes.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.alert import Alert  # noqa: E402
from backend.models.user import User  # noqa: E402
from clock import utcnow  # noqa: E402

client = TestClient(app)
API = "/api/v1/incidents"


def _auth(name="inc_op", role="operator"):
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


def test_manual_incident_lifecycle_with_timeline():
    _, hdr = _auth()
    officer_id, _ = _auth("inc_officer", "police")
    inc = client.post(f"{API}/", headers=hdr, json={"title": "Bag left at gate", "priority": "high",
                                                     "camera_location": "Gate"}).json()
    assert inc["ticket_id"] and inc["status"] == "open"
    iid = inc["id"]
    upd = client.put(f"{API}/{iid}", headers=hdr, json={"status": "investigating", "priority": "critical",
                                                         "assigned_to": officer_id}).json()
    assert (upd["status"], upd["priority"], upd["assigned_name"]) == ("investigating", "critical", "inc_officer")
    note = client.post(f"{API}/{iid}/notes", headers=hdr, json={"body": "Owner found, bag is clothes"}).json()
    assert note["body"] == "Owner found, bag is clothes"
    done = client.put(f"{API}/{iid}", headers=hdr, json={"status": "resolved"}).json()
    assert done["resolved_at"]
    full = client.get(f"{API}/{iid}", headers=hdr).json()
    kinds = [e["event_type"] for e in full["events"]]
    assert "STATUS" in kinds and "PRIORITY" in kinds and len(full["notes"]) == 1
    assert client.put(f"{API}/{iid}", headers=hdr, json={"status": "napping"}).status_code == 400
    assert client.put(f"{API}/{iid}", headers=hdr, json={"priority": "urgent!"}).status_code == 400


def test_from_alert_is_idempotent_and_lists_filter():
    _, hdr = _auth()
    db = SessionLocal()
    a = Alert(alert_type="WEAPON_DETECTED", severity="critical", camera_id="inc_cam", camera_location="Inc", timestamp=utcnow(),
              message="WEAPON DETECTED")
    db.add(a)
    db.commit()
    aid = a.id
    db.close()
    first = client.post(f"{API}/from-alert/{aid}", headers=hdr).json()
    again = client.post(f"{API}/from-alert/{aid}", headers=hdr).json()
    assert first["id"] == again["id"] and first["alert_id"] == aid and first["priority"] == "critical"
    assert client.post(f"{API}/from-alert/999999", headers=hdr).status_code == 404
    crit = client.get(f"{API}/?priority=critical", headers=hdr).json()
    assert any(i["id"] == first["id"] for i in crit) and all(i["priority"] == "critical" for i in crit)
    stats = client.get(f"{API}/stats", headers=hdr).json()
    assert stats["total"] >= 1 and stats["by_status"].get("open", 0) >= 1
    assert client.get(f"{API}/999999", headers=hdr).status_code == 404
