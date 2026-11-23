"""MFA requirement and admin IP allowlist (spec 14), enforced on the server."""
import uuid

from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.models.user import User

client = TestClient(app)
R = uuid.uuid4().hex[:6]


def _user(name, role, totp=False):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"), role=role,
             is_active=True, totp_enabled=totp)
    db.add(u)
    db.commit()
    tok = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {tok}"}


def test_mfa_required_blocks_everything_but_setup(monkeypatch):
    monkeypatch.setenv("MFA_REQUIRED", "true")
    no_mfa = _user(f"pol_a_{R}", "operator")
    with_mfa = _user(f"pol_b_{R}", "operator", totp=True)
    r = client.get("/api/v1/incidents/", headers=no_mfa)
    assert r.status_code == 403 and r.json()["detail"]["mfa_setup_required"] is True
    me = client.get("/api/v1/auth/me", headers=no_mfa).json()
    assert me["mfa_setup_required"] is True
    assert client.get("/api/v1/auth/2fa", headers=no_mfa).status_code == 200
    assert client.get("/api/v1/incidents/", headers=with_mfa).status_code == 200
    monkeypatch.setenv("MFA_REQUIRED", "false")
    assert client.get("/api/v1/incidents/", headers=no_mfa).status_code == 200


def test_admin_ip_allowlist(monkeypatch):
    admin = _user(f"pol_adm_{R}", "admin")
    op = _user(f"pol_op_{R}", "operator")
    monkeypatch.setenv("ADMIN_IP_ALLOWLIST", "10.20.0.0/16")
    assert client.get("/api/v1/officers", headers=admin).status_code == 403     # TestClient is "testclient"
    assert client.get("/api/v1/incidents/", headers=op).status_code == 200       # only admins are restricted
    monkeypatch.setenv("ADMIN_IP_ALLOWLIST", "")
    assert client.get("/api/v1/officers", headers=admin).status_code == 200


def test_retention_policy_and_accuracy():
    import json as _json
    from backend.models.alert import Alert
    from clock import utcnow
    admin = _user(f"pol_ret_{R}", "admin")
    op = _user(f"pol_ret_op_{R}", "operator")
    assert client.put("/api/v1/governance/retention", headers=op, json={"detection_days": 10, "capture_days": 5,
                                                                         "recording_hours": 24, "evidence_image_days": 60}).status_code == 403
    r = client.put("/api/v1/governance/retention", headers=admin, json={"detection_days": 10, "capture_days": 5,
                                                                         "recording_hours": 24, "evidence_image_days": 60}).json()
    assert r["detection_days"] == 10
    from backend.services.event_router import retention_days
    assert retention_days() == 10
    client.put("/api/v1/governance/retention", headers=admin, json={"detection_days": 30, "capture_days": 14,
                                                                     "recording_hours": 48, "evidence_image_days": 90})
    db = SessionLocal()
    cam = f"acc_{R}"
    for st, sim in (("confirmed", 0.81), ("rejected", 0.42), ("rejected", 0.45), ("pending", 0.6)):
        db.add(Alert(alert_type="FACE_MATCH", severity="high", camera_id=cam, timestamp=utcnow(), review_status=st,
                     details=_json.dumps({"face": {"model": "sface-2021dec", "similarity": sim}})))
    db.commit()
    db.close()
    acc = client.get("/api/v1/governance/accuracy?days=7", headers=op).json()
    row = next(c for c in acc["by_camera"] if c["key"] == cam)
    assert (row["matches"], row["confirmed"], row["rejected"], row["pending"]) == (4, 1, 2, 1)
    assert row["false_positive_rate"] == round(2 / 3, 3)
    assert any(s["key"] == "0.4–0.5" and s["rejected"] >= 2 for s in acc["by_score"])
