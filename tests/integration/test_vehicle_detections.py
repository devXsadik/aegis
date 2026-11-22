"""Vehicle detections: pipeline ingest fills GET /vehicles/detections (was previously empty)."""

import os

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_vehicle_detections.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci-only-32chars")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-32-chars!!")
os.environ.setdefault("ENVIRONMENT", "development")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.models.vehicle import LicensePlate, VehicleDetection  # noqa: E402

client = TestClient(app)
KEY = {"X-Internal-Key": os.environ["INTERNAL_API_KEY"]}


def _token():
    from backend.auth.auth import hash_password, issue_token

    db = SessionLocal()
    user = db.query(User).filter(User.username == "vehops").first()
    if not user:
        user = User(
            username="vehops",
            email="veh@t.local",
            hashed_password=hash_password("pass1234"),
            role="operator",
            is_active=True,
        )
        db.add(user)
        db.commit()
    token = issue_token(user)
    db.close()
    return token


def test_ingest_persists_detection_and_flags_watchlisted_plates():
    init_db()
    db = SessionLocal()
    db.add(LicensePlate(plate_number="ABC1234", watchlisted=True, reason="audit"))
    db.commit()
    db.close()

    bad = client.post(
        "/api/v1/vehicles/detections/ingest",
        json={"camera_location": "Gate", "track_id": 3, "license_plate": "XYZ9999"},
    )
    assert bad.status_code in (401, 503)

    r = client.post(
        "/api/v1/vehicles/detections/ingest",
        json={
            "camera_location": "Gate",
            "track_id": 3,
            "vehicle_type": "car",
            "license_plate": "abc1234",
            "plate_confidence": 0.91,
        },
        headers=KEY,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"

    token = _token()
    listed = client.get(
        "/api/v1/vehicles/detections",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    rows = listed.json()
    assert any(row["license_plate"] == "ABC1234" and row["is_suspicious"] for row in rows)

    db = SessionLocal()
    stored = db.query(VehicleDetection).filter(VehicleDetection.license_plate == "ABC1234").first()
    assert stored is not None
    assert stored.vehicle_type == "car"
    assert stored.plate_confidence == "0.910"
    db.close()


def test_watchlisted_plate_alert_also_writes_vehicle_detection():
    init_db()
    r = client.post(
        "/api/v1/alerts/dispatch",
        json={
            "alert_type": "WATCHLISTED_VEHICLE",
            "severity": "critical",
            "camera_location": "North",
            "camera_id": "cam_n",
            "track_id": 11,
            "plate_number": "DHK7788",
            "message": "Watchlisted plate",
            "confidence": 0.8,
        },
        headers=KEY,
    )
    assert r.status_code == 200, r.text

    db = SessionLocal()
    row = db.query(VehicleDetection).filter(VehicleDetection.license_plate == "DHK7788").first()
    assert row is not None
    assert row.is_suspicious is True
    assert row.camera_location == "North"
    db.close()
