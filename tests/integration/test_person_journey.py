"""Where was this person? Face, look-alike and capture sightings merged into visits."""

import os
from datetime import timedelta

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_person_journey.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.alert import Alert  # noqa: E402
from backend.models.camera import Camera  # noqa: E402
from backend.models.capture import AlertCapture  # noqa: E402
from backend.models.evidence import Evidence  # noqa: E402
from backend.models.user import User  # noqa: E402
from clock import utcnow  # noqa: E402

client = TestClient(app)
NAME = "Journey Person"


def _auth():
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    user = db.query(User).filter(User.username == "pj_op").first()
    if not user:
        user = User(username="pj_op", email="pj@t.local", hashed_password=hash_password("pass12345678"),
                    role="operator", is_active=True)
        db.add(user)
        db.commit()
    token = issue_token(user)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def setup_module():
    init_db()
    db = SessionLocal()
    for model in (Evidence, Alert, AlertCapture):
        db.query(model).filter(model.person_name == NAME).delete()
    db.query(Camera).filter(Camera.camera_id.in_(["pj_gate", "pj_lobby"])).delete()
    db.add_all([Camera(camera_id="pj_gate", name="Main gate", location="Gate", lat=23.81, lng=90.41, active=True),
                Camera(camera_id="pj_lobby", name="Lobby", location="Lobby", active=True)])
    t0 = utcnow() - timedelta(hours=1)
    at = lambda s: t0 + timedelta(seconds=s)  # noqa: E731
    db.add_all([
        Evidence(person_name=NAME, camera_id="pj_gate", camera_location="Gate", track_id=1, category="criminal",
                 timestamp=at(0), frame_data=b"jpg"),
        Alert(person_name=NAME, camera_id="pj_gate", camera_location="Gate", alert_type="CRIMINAL_DETECTED",
              severity="critical", timestamp=at(30)),
        Alert(person_name=NAME, camera_id="pj_lobby", camera_location="Lobby", alert_type="PERSON_TRACKED",
              severity="high", timestamp=at(300)),
        AlertCapture(person_name=NAME, camera_id="pj_lobby", camera_location="Lobby", alert_type="PERSON_TRACKED",
                     timestamp=at(350), image_data=b"jpg"),
        Evidence(person_name=NAME, camera_id="pj_gate", camera_location="Gate", track_id=2, category="criminal",
                 timestamp=at(900)),
        Alert(person_name=NAME, camera_id="pj_gate", alert_type="WEAPON_DETECTED", severity="critical", timestamp=at(901)),
    ])
    db.commit()
    db.close()


def test_sightings_become_visits_in_time_order_with_camera_positions():
    r = client.get(f"/api/v1/reid/persons/{NAME}?hours=3", headers=_auth()).json()
    assert r["sightings"] == 5                                    # the weapon alert is not a sighting of him
    v = r["visits"]
    assert [x["camera"] for x in v] == ["Main gate", "Lobby", "Main gate"]   # gate, lobby, back to the gate
    assert v[0]["count"] == 2 and v[0]["image"] == {"kind": "evidence", "id": v[0]["image"]["id"]}
    assert (v[0]["lat"], v[0]["lng"]) == (23.81, 90.41) and v[1]["lat"] is None
    assert v[1]["sources"] == ["Capture", "Look-alike (clothing, build)"] and v[1]["image"]["kind"] == "capture"
    assert v[2]["image"] is None
    assert r["cameras"] == ["Lobby", "Main gate"]


def test_unknown_person_has_no_visits_and_needs_a_role():
    assert client.get("/api/v1/reid/persons/Nobody", headers=_auth()).json()["visits"] == []
    assert client.get(f"/api/v1/reid/persons/{NAME}").status_code == 401
