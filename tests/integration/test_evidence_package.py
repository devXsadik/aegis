"""Evidence package: contents, manifest, signature, custody record, and the verify check."""

import hashlib
import io
import os
import zipfile
from datetime import timedelta

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_evidence_package.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.alert import Alert  # noqa: E402
from backend.models.capture import AlertCapture  # noqa: E402
from backend.models.custody import CustodyRecord  # noqa: E402
from backend.models.evidence import Evidence  # noqa: E402
from backend.models.incident import Incident  # noqa: E402
from backend.models.user import User  # noqa: E402
from clock import utcnow  # noqa: E402

client = TestClient(app)


def _auth():
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    user = db.query(User).filter(User.username == "ep_op").first()
    if not user:
        user = User(username="ep_op", email="ep@t.local", hashed_password=hash_password("pass12345678"),
                    role="operator", is_active=True)
        db.add(user)
        db.commit()
    token = issue_token(user)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def _incident():
    init_db()
    db = SessionLocal()
    t = utcnow() - timedelta(minutes=5)
    alert = Alert(alert_type="WEAPON_DETECTED", severity="critical", camera_id="ep_cam", camera_location="EP Gate",
                  track_id=3, message="WEAPON DETECTED (in hand)", timestamp=t)
    db.add(alert)
    db.flush()
    db.add_all([
        Evidence(camera_location="EP Gate", camera_id="ep_cam", track_id=3, category="weapon", timestamp=t,
                 frame_data=b"\xff\xd8frame", roi_data=b"\xff\xd8roi", content_sha256=hashlib.sha256(b"\xff\xd8frame").hexdigest()),
        Evidence(camera_location="Elsewhere", track_id=9, category="weapon", timestamp=t, frame_data=b"\xff\xd8other"),
        AlertCapture(alert_id=alert.id, alert_type="WEAPON_DETECTED", camera_id="ep_cam", timestamp=t, image_data=b"\xff\xd8cap"),
    ])
    inc = Incident(ticket_id=f"TKT-EP{alert.id}", title="Armed person at the gate", incident_type="WEAPON_DETECTED",
                   priority="critical", status="open", camera_id="ep_cam", camera_location="EP Gate", alert_id=alert.id)
    db.add(inc)
    db.commit()
    iid = inc.id
    db.close()
    return iid


def test_package_holds_the_case_and_proves_it_is_intact():
    iid = _incident()
    r = client.get(f"/api/v1/incidents/{iid}/package", headers=_auth())
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "_evidence_package.zip" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"README.txt", "incident.json", "alert.json", "MANIFEST.sha256", "SIGNATURE.txt"} <= names
    stills = sorted(n for n in names if n.startswith("evidence/"))
    assert len([n for n in stills if n.endswith("_frame.jpg")]) == 1       # only the alert's camera
    assert any(n.startswith("captures/") for n in names)
    for line in z.read("MANIFEST.sha256").decode().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256(z.read(name)).hexdigest() == digest

    ev_id = int(stills[0].split("/")[1].split("_")[0].split(".")[0])
    db = SessionLocal()
    assert db.query(CustodyRecord).filter(CustodyRecord.evidence_id == ev_id, CustodyRecord.action == "EXPORTED").count() >= 1
    db.close()

    ok = client.post("/api/v1/incidents/package/verify", headers=_auth(),
                     files={"file": ("p.zip", r.content, "application/zip")}).json()
    assert ok["ok"] and ok["signature_valid"] and ok["changed_or_missing"] == []


def test_verify_catches_a_changed_file_and_a_forged_signature():
    iid = _incident()
    original = zipfile.ZipFile(io.BytesIO(client.get(f"/api/v1/incidents/{iid}/package", headers=_auth()).content))

    def rebuild(change):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as out:
            for n in original.namelist():
                out.writestr(n, change(n, original.read(n)))
        return buf.getvalue()

    edited = rebuild(lambda n, d: b'{"title": "edited"}' if n == "incident.json" else d)
    r = client.post("/api/v1/incidents/package/verify", headers=_auth(), files={"file": ("p.zip", edited)}).json()
    assert not r["ok"] and r["changed_or_missing"] == ["incident.json"]

    forged = rebuild(lambda n, d: b"HMAC-SHA256 " + b"0" * 64 if n == "SIGNATURE.txt" else d)
    r = client.post("/api/v1/incidents/package/verify", headers=_auth(), files={"file": ("p.zip", forged)}).json()
    assert not r["ok"] and not r["signature_valid"]

    junk = client.post("/api/v1/incidents/package/verify", headers=_auth(), files={"file": ("x.zip", b"nope")}).json()
    assert junk["ok"] is False and "Not an evidence package" in junk["error"]


def test_missing_incident_and_auth():
    assert client.get("/api/v1/incidents/999999/package", headers=_auth()).status_code == 404
    assert client.get("/api/v1/incidents/1/package").status_code == 401
