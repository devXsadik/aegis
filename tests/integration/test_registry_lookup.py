"""Vehicle registry lookups: off until configured, role + reason + case number, audit-logged."""
import uuid

from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.models.audit_log import AuditLog
from backend.models.user import User

client = TestClient(app)
R = uuid.uuid4().hex[:6]


def _tok(role):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = User(username=f"rg_{role}_{R}", email=f"rg_{role}_{R}@t.local", hashed_password=hash_password("pass12345678"), role=role, is_active=True)
    db.add(u)
    db.commit()
    t = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {t}"}


Q = {"plate": "Dhaka Metro Ga 11-2233", "reason": "Vehicle seen at robbery scene", "case_ref": "GD 1234/26"}


def test_registry_lookup(monkeypatch):
    inv, op = _tok("investigator"), _tok("operator")
    monkeypatch.delenv("VEHICLE_REGISTRY_URL", raising=False)
    assert client.get("/api/v1/vehicles/registry/status", headers=inv).json() == {"configured": False, "allowed": True}
    assert client.get("/api/v1/vehicles/registry", headers=inv, params=Q).status_code == 503
    assert client.get("/api/v1/vehicles/registry", headers=op, params=Q).status_code == 403
    assert client.get("/api/v1/vehicles/registry", headers=inv, params={**Q, "reason": "x"}).status_code == 422

    calls = []

    class Resp:
        status_code = 200

        def json(self):
            return {"plate": "x", "registered_owner": "A. Rahman", "make": "Toyota", "reported_stolen": False, "secret": "dropped"}

    def get(url, params, headers, timeout):
        calls.append((url, params, headers))
        return Resp()
    import requests
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setenv("VEHICLE_REGISTRY_URL", "https://registry.example/api/v1/plates")
    monkeypatch.setenv("VEHICLE_REGISTRY_TOKEN", "tkn")
    out = client.get("/api/v1/vehicles/registry", headers=inv, params=Q).json()
    assert out["found"] and out["record"]["registered_owner"] == "A. Rahman" and "secret" not in out["record"]
    assert calls[0][2]["Authorization"] == "Bearer tkn" and calls[0][1]["plate"] == out["plate"]
    db = SessionLocal()
    logs = db.query(AuditLog).filter(AuditLog.action == "REGISTRY_LOOKUP").all()
    db.close()
    assert any("GD 1234/26" in (entry.details or "") and "robbery" in (entry.details or "") for entry in logs)
    assert not any("A. Rahman" in (entry.details or "") for entry in logs)      # the answer is not stored
