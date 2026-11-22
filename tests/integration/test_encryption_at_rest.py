"""Faces at rest: stored encrypted, served as JPEG, old plaintext rows converted by a script."""

import hashlib
import os
import uuid

import cv2
import numpy as np
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_encryption_at_rest.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.alert import Alert  # noqa: E402
from backend.models.capture import AlertCapture  # noqa: E402
from backend.models.custody import CustodyRecord  # noqa: E402
from backend.models.evidence import Evidence  # noqa: E402
from backend.models.known_person import KnownPerson  # noqa: E402
from backend.models.person_image import PersonImage  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.utils.encryption import MAGIC_V1  # noqa: E402
from clock import utcnow  # noqa: E402

client = TestClient(app)
KEY = {"X-Internal-Key": os.environ["INTERNAL_API_KEY"]}


def _jpeg():
    ok, buf = cv2.imencode(".jpg", np.full((400, 160, 3), 90, np.uint8))
    return buf.tobytes()


def _auth():
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == "ear_op").first()
    if not u:
        u = User(username="ear_op", email="ear@t.local", hashed_password=hash_password("pass12345678"), role="operator", is_active=True)
        db.add(u)
        db.commit()
    token = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def test_capture_is_stored_encrypted_and_served_as_the_jpeg():
    init_db()
    db = SessionLocal()
    db.add(Alert(alert_type="WEAPON_DETECTED", severity="critical", camera_id="ear_cam", timestamp=utcnow()))
    db.commit()
    db.close()
    jpg = _jpeg()
    r = client.post("/api/v1/captures/ingest", headers=KEY, files={"file": ("c.jpg", jpg, "image/jpeg")},
                    data={"camera_id": "ear_cam", "alert_type": "WEAPON_DETECTED", "bbox": "0.1,0.1,0.3,0.6"})
    assert r.status_code == 200 and r.json()["status"] == "stored", r.text
    cid = r.json()["id"]
    db = SessionLocal()
    row = db.get(AlertCapture, cid)
    assert row.encrypted and row.image_data.startswith(MAGIC_V1) and not row.image_data.startswith(b"\xff\xd8")
    assert row.content_sha256 != hashlib.sha256(row.image_data).hexdigest()     # hash is of the JPEG, not the ciphertext
    db.close()
    served = client.get(f"/api/v1/captures/{cid}/image", headers=_auth())
    assert served.status_code == 200 and served.content[:2] == b"\xff\xd8"


def test_script_encrypts_old_plaintext_rows_once(monkeypatch):
    import scripts.encrypt_existing as script
    init_db()
    db = SessionLocal()
    person = KnownPerson(person_id=f"EAR_{uuid.uuid4().hex[:8]}", name="Old Photo", category="civilian")
    db.add(person)
    db.flush()
    jpg = _jpeg()
    img = PersonImage(person_id=person.id, image_data=jpg, encrypted=False)
    ev = Evidence(camera_location="EAR", track_id=1, category="suspicious", frame_data=jpg, roi_data=jpg,
                  encrypted=False, content_sha256=hashlib.sha256(jpg).hexdigest())
    db.add_all([img, ev])
    db.commit()
    img_id, ev_id = img.id, ev.id
    db.close()

    assert script.main(dry_run=True)["evidence"] >= 1
    counts = script.main(dry_run=False)
    assert counts["evidence"] >= 1 and counts["enrolment_photos"] >= 1
    assert script.main(dry_run=False) == {"evidence": 0, "captures": 0, "enrolment_photos": 0}

    db = SessionLocal()
    assert db.get(PersonImage, img_id).image_data.startswith(MAGIC_V1)
    e = db.get(Evidence, ev_id)
    assert e.encrypted and e.content_sha256 == hashlib.sha256(jpg).hexdigest()       # hash still of the JPEG
    assert db.query(CustodyRecord).filter(CustodyRecord.evidence_id == ev_id, CustodyRecord.action == "ENCRYPTED").count() == 1
    db.close()
    photo = client.get(f"/api/v1/faces/images/{img_id}", headers=_auth())
    assert photo.status_code == 200 and photo.content == jpg
