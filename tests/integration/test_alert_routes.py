"""Alert API the Alerts page runs on: queues, context, confirm/reject, manual dispatch.

External channels (webhooks, SMS) are replaced with fakes: nothing leaves the test.
"""

import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_alert_routes.db")

from backend.main import app  # noqa: E402
from backend.api import alert_routes  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.alert import Alert  # noqa: E402
from backend.models.audit_log import AuditLog  # noqa: E402
from backend.models.event import Event  # noqa: E402
from backend.models.evidence import Evidence  # noqa: E402
from backend.models.user import User  # noqa: E402
from clock import utcnow  # noqa: E402

client = TestClient(app)
API = "/api/v1/alerts"
CAM = "ar_cam"


def _auth(role="operator"):
    from backend.auth.auth import hash_password, issue_token
    db = SessionLocal()
    name = f"ar_{role}"
    user = db.query(User).filter(User.username == name).first()
    if not user:
        user = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"),
                    role=role, is_active=True)
        db.add(user)
        db.commit()
    token = issue_token(user)
    db.close()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    init_db()
    db = SessionLocal()
    for model in (Alert, Event, Evidence):
        db.query(model).filter(model.camera_id == CAM).delete()
    db.commit()
    db.close()
    calls = {"released": [], "redispatched": []}

    async def fake_release(alert):
        calls["released"].append(alert.id)
        return "webhook"

    async def fake_redispatch(alert, message, db):
        calls["redispatched"].append((alert.id, message))
        return {"channels": "webhook"}

    monkeypatch.setattr(alert_routes, "release_held_webhooks", fake_release)
    monkeypatch.setattr(alert_routes, "redispatch_alert", fake_redispatch)
    yield calls


def _audits(alert_id, action):
    db = SessionLocal()
    n = db.query(AuditLog).filter(AuditLog.resource_id == str(alert_id), AuditLog.action == action).count()
    db.close()
    return n


def _alert(**kw):
    db = SessionLocal()
    a = Alert(**{"alert_type": "SUSPICIOUS_BEHAVIOR", "severity": "high", "camera_id": CAM,
                 "camera_location": "Lab", "track_id": 3, "review_status": "not_required",
                 "timestamp": utcnow(), **kw})
    db.add(a)
    db.commit()
    db.refresh(a)
    db.close()
    return a


def test_list_filters_and_queues():
    hdr = _auth()
    _alert(review_status="pending", alert_type="CRIMINAL_DETECTED", severity="critical")
    _alert(acknowledged=True)
    _alert(dismissed=True)
    mine = lambda r: [a for a in r.json() if a["camera_location"] == "Lab"]  # noqa: E731
    assert len(mine(client.get(f"{API}/?camera_id={CAM}", headers=hdr))) == 3
    assert [a["alert_type"] for a in mine(client.get(f"{API}/?camera_id={CAM}&review_status=pending", headers=hdr))] == ["CRIMINAL_DETECTED"]
    assert len(mine(client.get(f"{API}/?camera_id={CAM}&alert_type=criminal_detected", headers=hdr))) == 1
    assert len(mine(client.get(f"{API}/?camera_id={CAM}&acknowledged=false&dismissed=false", headers=hdr))) == 1
    assert client.get(f"{API}/?review_status=bogus", headers=hdr).status_code == 422
    assert len(mine(client.get(f"{API}/unacknowledged", headers=hdr))) == 1
    stats = client.get(f"{API}/stats?hours=1", headers=hdr).json()
    assert stats["by_type"]["SUSPICIOUS_BEHAVIOR"] >= 2 and stats["period_hours"] == 1
    rc = client.get(f"{API}/review-queue-count", headers=hdr).json()
    assert rc["pending"] >= 1
    assert rc["escalate_after_seconds"] == int(os.getenv("ESCALATE_AFTER_SECONDS", "120"))
    assert rc["escalated_types"] == ["CRIMINAL_DETECTED", "WEAPON_DETECTED"]


def test_viewers_cannot_read_alerts():
    assert client.get(f"{API}/", headers=_auth("viewer")).status_code == 403
    assert client.get(f"{API}/").status_code == 401


def test_context_has_nearby_evidence_related_events_and_held_flag():
    hdr = _auth()
    a = _alert(alert_type="CRIMINAL_DETECTED", review_status="pending", person_name="Sadik")
    db = SessionLocal()
    db.add_all([
        Evidence(camera_location="Lab", camera_id=CAM, track_id=3, category="criminal",
                 timestamp=a.timestamp + timedelta(seconds=5), frame_data=b"jpeg"),
        Evidence(camera_location="Lab", camera_id=CAM, track_id=3, category="criminal",
                 timestamp=a.timestamp + timedelta(minutes=10), frame_data=b"far away in time"),
        Event(event_type="CRIMINAL_DETECTED", camera_id=CAM, alert_id=a.id, confidence=0.83, zone="Gate"),
        Event(event_type="LOITERING", camera_id=CAM, alert_id=None, message="earlier"),
    ])
    db.commit()
    db.close()
    ctx = client.get(f"{API}/{a.id}/context", headers=hdr).json()
    assert len(ctx["evidence"]) == 1 and ctx["evidence"][0]["has_image"]
    assert (ctx["confidence"], ctx["zone"]) == (0.83, "Gate")
    assert [r["type"] for r in ctx["related_events"]] == ["LOITERING"]
    assert ctx["holds_external_notification"] is True
    assert client.get(f"{API}/999999/context", headers=hdr).status_code == 404


def test_confirming_a_held_match_releases_its_notifications_once(clean):
    hdr = _auth()
    a = _alert(alert_type="CRIMINAL_DETECTED", review_status="pending", escalated_at=utcnow())
    listed = [x for x in client.get(f"{API}/?camera_id={CAM}", headers=hdr).json() if x["id"] == a.id][0]
    assert listed["escalated_at"] and listed["camera_id"] == CAM     # the queue shows "backup paged"
    before = _audits(a.id, "ALERT_CONFIRMED")         # ids are reused across runs of this test DB
    r = client.put(f"{API}/{a.id}/acknowledge", headers=hdr, json={"acknowledged": True, "note": "same person"})
    assert r.json()["review_status"] == "confirmed" and r.json()["webhooks_released"] == "webhook"
    client.put(f"{API}/{a.id}/acknowledge", headers=hdr, json={"acknowledged": True})
    assert clean["released"] == [a.id]                       # a second confirm does not page again
    db = SessionLocal()
    row = db.get(Alert, a.id)
    assert row.acknowledged and row.acknowledged_by and row.review_note is None
    db.close()
    assert _audits(a.id, "ALERT_CONFIRMED") - before == 2


def test_rejecting_records_the_reason_and_releases_nothing(clean):
    a = _alert(alert_type="CRIMINAL_DETECTED", review_status="pending")
    r = client.put(f"{API}/{a.id}/acknowledge", headers=_auth(),
                   json={"acknowledged": False, "dismissed": True, "note": "lookalike"})
    assert r.json()["review_status"] == "rejected"
    assert clean["released"] == []
    db = SessionLocal()
    assert db.get(Alert, a.id).review_note == "lookalike"
    db.close()
    assert client.put(f"{API}/999999/acknowledge", headers=_auth(), json={}).status_code == 404


def test_manual_dispatch_acknowledges_confirms_and_audits(clean):
    a = _alert(alert_type="CRIMINAL_DETECTED", review_status="pending", message="Watchlist match")
    before = _audits(a.id, "MANUAL_DISPATCH")
    r = client.post(f"{API}/{a.id}/dispatch", headers=_auth())
    assert r.json()["status"] == "dispatched"
    (alert_id, message), = clean["redispatched"]
    assert alert_id == a.id and message.startswith("[MANUAL DISPATCH by ar_operator]")
    db = SessionLocal()
    row = db.get(Alert, a.id)
    assert row.acknowledged and row.review_status == "confirmed"
    db.close()
    assert _audits(a.id, "MANUAL_DISPATCH") - before == 1
    assert client.post(f"{API}/999999/dispatch", headers=_auth()).status_code == 404
