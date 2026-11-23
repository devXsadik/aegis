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
    "AEGIS_UPLOADS_DIR": f"{_tmp}/uploads",
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
    _seed_tracking(db)
    from backend.models.known_person import KnownPerson
    db.add(KnownPerson(person_id="P-E2E00001", name="Kalam Sheikh", category="criminal", criminal_status="wanted"))
    db.commit()


def _seed_tracking(db) -> None:
    """A confirmed target already followed from Gate to Lab, a lookout to the north, and a
    'target detected' notification for officer Karim (no alerts: the smoke test counts them)."""
    import json
    from datetime import timedelta
    from backend.models.bolo import Bolo, BoloCamera
    from backend.models.camera import Camera
    from backend.models.incident import Incident
    from backend.models.tracking import CrossCameraTrack, Notification, TrackHop
    from backend.models.user import User
    from clock import utcnow
    now = utcnow()
    db.add(Camera(camera_id="e2e_north", name="North road", location="North", lat=23.797, lng=90.416, heading=0))
    inc = Incident(ticket_id="INC-TRK1", title="E2E tracked vehicle", status="verified_match", priority="high",
                   camera_id="e2e_lab", camera_location="Lab", source="vehicle_match")
    db.add(inc)
    db.flush()
    t = CrossCameraTrack(kind="vehicle", target_ref="V-E2E", incident_id=inc.id, status="active", verified=True,
                         last_camera="e2e_lab", last_seen=now, direction="N", bearing=0)
    db.add(t)
    db.flush()
    db.add(TrackHop(track_id=t.id, camera_id="e2e_gate", seen_at=now - timedelta(minutes=4), direction="NE", method="plate:exact"))
    db.add(TrackHop(track_id=t.id, camera_id="e2e_lab", seen_at=now, direction="N", method="plate:exact"))
    b = Bolo(ref="B-E2E00001", kind="vehicle", target_ref="V-E2E", origin="auto", origin_camera="e2e_lab", direction="N",
             incident_id=inc.id, cross_track_id=t.id, window_start=now, window_end=now + timedelta(minutes=30), status="active")
    b.cameras.append(BoloCamera(camera_id="e2e_north", rank=0, eta_from_s=60, eta_to_s=300, distance_m=800))
    db.add(b)
    karim = db.query(User).filter(User.username == "e2e_off_karim").first()
    db.add(Notification(user_id=karim.id, kind="target_detected", priority="critical",
                        title="V-E2E detected at Lab gate, moving N", body="Towards North road, ETA ~2 min.",
                        payload=json.dumps({"camera_id": "e2e_lab", "direction": "N", "lat": 23.79, "lng": 90.415}),
                        incident_id=inc.id, ack_deadline=now + timedelta(minutes=10)))
    db.commit()


if __name__ == "__main__":
    import uvicorn

    seed()
    from backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("E2E_API_PORT", "8010")), log_level="warning")
