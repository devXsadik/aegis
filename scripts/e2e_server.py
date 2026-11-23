#!/usr/bin/env python3
"""Throwaway API for the dashboard's Playwright smoke test (frontend/e2e).

Fresh SQLite in a temp folder, test secrets, and every outside channel (webhooks, SMS, CAD)
blanked before .env is read, so confirming or dispatching in the test reaches nobody.
Seeds one operator and a few pending alerts, then serves on E2E_API_PORT (default 8010).

    python scripts/e2e_server.py
"""

import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

USER, PASSWORD = "e2e_operator", "e2e-pass-12345"
_tmp = tempfile.mkdtemp(prefix="aegis_e2e_api_")
# Set before any backend import: load_dotenv() never overrides a variable that is already set.
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/e2e.db",
    "AEGIS_CAMERAS_YAML": f"{_tmp}/cameras.yaml",      # copied below; the dashboard may edit it
    "USE_SQLITE": "false",
    "SECRET_KEY": "e2e-secret-key-not-for-production-0123456789",
    "ENCRYPTION_KEY": "e2e-encryption-key-32-characters!",
    "ENCRYPTION_SALT": "e2e-salt",
    "INTERNAL_API_KEY": "e2e-internal-key-not-default",
    "ALERTS_ENABLED": "false",
    "LAW_ENFORCEMENT_WEBHOOK": "", "EMERGENCY_WEBHOOK": "", "SECURITY_TEAM_WEBHOOK": "",
    "CAD_WEBHOOK": "", "RADIO_WEBHOOK": "", "SMS_WEBHOOK": "",
    "REDIS_URL": "",
    "CORS_ORIGINS": "http://localhost:5174",
    "LOGIN_RATE_LIMIT": "200",              # every e2e test signs in from 127.0.0.1
    "WRITE_RATE_LIMIT": "5000",             # …and all four browsers write from it too
})


def _copy_cameras_yaml() -> None:
    import shutil
    shutil.copy(ROOT / "config" / "cameras.yaml", os.environ["AEGIS_CAMERAS_YAML"])


def seed() -> None:
    _copy_cameras_yaml()
    from backend.auth.auth import hash_password
    from backend.db.database import SessionLocal, init_db
    from backend.models.alert import Alert
    from backend.models.user import User
    from clock import utcnow

    init_db()
    db = SessionLocal()
    db.add(User(username=USER, email="e2e@example.invalid", hashed_password=hash_password(PASSWORD),
                role="operator", is_active=True))
    now = utcnow()
    for minutes in (1, 4):                     # one person, seen twice: one queue entry "×2"
        db.add(Alert(timestamp=now - timedelta(minutes=minutes), alert_type="CRIMINAL_DETECTED",
                     severity="critical", camera_id="e2e_gate", camera_location="Gate", track_id=4,
                     person_name="Test Person", message="WATCHLIST MATCH (unverified): Test Person",
                     review_status="pending", escalated_at=now))      # no escalation paging
    db.add(Alert(timestamp=now - timedelta(minutes=30), alert_type="SUSPICIOUS_BEHAVIOR", severity="high",
                 camera_id="e2e_lab", camera_location="Lab", track_id=9, message="Loitering",
                 review_status="pending", escalated_at=now))
    db.commit()
    _seed_areas(db, hash_password)
    db.close()


def _seed_areas(db, hash_password) -> None:
    """One thana around the Lab camera, a neighbour, two officers inside and one next door,
    and a supervisor (for the neighbour override)."""
    import json
    from backend.models.camera import Camera
    from backend.models.jurisdiction import Jurisdiction, OfficerJurisdiction, OfficerProfile
    from backend.models.user import User

    def box(lat0, lng0, lat1, lng1):
        return json.dumps({"type": "Polygon", "coordinates": [[[lng0, lat0], [lng1, lat0], [lng1, lat1], [lng0, lat1], [lng0, lat0]]]})

    dist = Jurisdiction(code="E2E-DIST", name_en="E2E district", level="district", geojson=box(23.70, 90.35, 23.90, 90.45))
    db.add(dist)
    db.flush()
    gulshan = Jurisdiction(code="E2E-GULSHAN", name_en="Gulshan", name_bn="গুলশান", level="thana", parent_id=dist.id,
                           geojson=box(23.775, 90.405, 23.800, 90.430))
    badda = Jurisdiction(code="E2E-BADDA", name_en="Badda", level="thana", parent_id=dist.id,
                         geojson=box(23.775, 90.430, 23.800, 90.450))
    db.add_all([gulshan, badda])
    db.flush()
    db.add(Camera(camera_id="e2e_lab", name="Lab gate", location="Lab", lat=23.79, lng=90.415, jurisdiction_id=gulshan.id))
    db.add(Camera(camera_id="e2e_gate", name="Main gate", location="Gate", lat=23.785, lng=90.41))
    # Second operator: the smoke test signs e2e_operator out, which revokes all of its sessions.
    db.add(User(username="e2e_desk", email="desk@example.invalid", hashed_password=hash_password(PASSWORD),
                role="operator", is_active=True))
    db.add(User(username="e2e_admin", email="admin@example.invalid", hashed_password=hash_password(PASSWORD),
                role="admin", is_active=True))
    db.add(User(username="e2e_supervisor", email="sup@example.invalid", hashed_password=hash_password(PASSWORD),
                role="supervisor", is_active=True))
    for name, full, area, duty in (("e2e_off_karim", "Karim Hossain", gulshan, "available"),
                                   ("e2e_off_nasrin", "Nasrin Akter", gulshan, "busy"),
                                   ("e2e_off_badda", "Rafiq Uddin", badda, "available")):
        u = User(username=name, email=f"{name}@example.invalid", hashed_password=hash_password(PASSWORD), role="police",
                 is_active=True, phone="+8801700000000")
        db.add(u)
        db.flush()
        db.add(OfficerProfile(user_id=u.id, full_name=full, rank="SI", badge_no=f"E2E-{u.id}", station_id=area.id, duty_status=duty))
        db.add(OfficerJurisdiction(user_id=u.id, jurisdiction_id=area.id))
    # Recent vehicle sightings for Vehicle Search (no watchlist hit: they raise no alert).
    from datetime import timedelta as _td
    from backend.models.detection import Detection
    from clock import utcnow as _now
    for i, (plate, color, vtype, model) in enumerate((("ঢাকা মেট্রো-গ ১২-৩৪৫৬", "white", "car", "Toyota Axio"),
                                                     ("ঢাকা মেট্রো-খ ৫১-০০১২", "black", "microbus", "Toyota Noah"),
                                                     (None, "white", "car", "Toyota Premio"))):
        db.add(Detection(event_id=f"e2e-det-{i}", camera_id="e2e_lab", ts=_now() - _td(minutes=5 + i), kind="vehicle",
                         source="simulator", plate_raw=plate, plate_canonical=__import__("core.analysis.bd_plate", fromlist=["x"]).canonical(plate) if plate else None,
                         vehicle_type=vtype, color=color, make_model=model, expires_at=_now() + _td(days=30)))
    from backend.models.known_person import KnownPerson
    db.add(KnownPerson(person_id="P-E2E00001", name="Kalam Sheikh", category="criminal", criminal_status="wanted"))
    db.commit()


if __name__ == "__main__":
    import uvicorn

    seed()
    from backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("E2E_API_PORT", "8010")), log_level="warning")
