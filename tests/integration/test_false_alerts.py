"""Operator feedback: false-alert rate per camera and type, and the tuning it suggests."""

import os

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_false_alerts.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.alert import Alert  # noqa: E402
from backend.models.user import User  # noqa: E402
from clock import utcnow  # noqa: E402

client = TestClient(app)


def _auth():
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == "fa_op").first()
    if not u:
        u = User(username="fa_op", email="fa@t.local", hashed_password=hash_password("pass12345678"), role="operator", is_active=True)
        db.add(u)
        db.commit()
    token = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def _decisions(cam, typ, confirmed, rejected_as):
    db = SessionLocal()
    for _ in range(confirmed):
        db.add(Alert(alert_type=typ, severity="high", camera_id=cam, camera_location=cam.upper(), timestamp=utcnow(),
                     review_status="confirmed"))
    for reason in rejected_as:
        db.add(Alert(alert_type=typ, severity="high", camera_id=cam, camera_location=cam.upper(), timestamp=utcnow(),
                     review_status="rejected", dismissed=True, review_note=f"{reason}: checked"))
    db.commit()
    db.close()


def setup_module():
    init_db()
    db = SessionLocal()
    db.query(Alert).filter(Alert.camera_id.like("fa_%")).delete(synchronize_session=False)
    db.commit()
    db.close()
    _decisions("fa_gate", "WEAPON_DETECTED", 2, ["false_detection"] * 4)         # 4 of 6 wrong: noisy
    _decisions("fa_lobby", "WEAPON_DETECTED", 5, ["false_detection"])            # 1 of 6: fine
    _decisions("fa_door", "INTRUSION", 1, ["false_detection"] * 3 + ["known_person"])
    _decisions("fa_yard", "CRIMINAL_DETECTED", 1, ["known_person"] * 5)            # staff, not detector errors
    _decisions("fa_hall", "WEAPON_DETECTED", 0, ["false_detection"] * 2)           # too few to judge


def _groups():
    r = client.get("/api/v1/analytics/false-alerts?days=7", headers=_auth()).json()
    return {(g["camera_id"], g["alert_type"]): g for g in r["groups"] if g["camera_id"].startswith("fa_")}


def test_noisy_camera_gets_a_threshold_step_quiet_one_none():
    g = _groups()
    gate = g[("fa_gate", "WEAPON_DETECTED")]
    assert (gate["reviewed"], gate["false_detections"], gate["false_rate"]) == (6, 4, 0.67)
    assert gate["suggestion"]["key"] == "weapon_conf_threshold"
    assert gate["suggestion"]["to"] == round(gate["suggestion"]["from"] + 0.05, 2)
    assert g[("fa_lobby", "WEAPON_DETECTED")]["suggestion"] is None
    assert g[("fa_hall", "WEAPON_DETECTED")]["suggestion"] is None                # 2 decisions: no advice


def test_zone_alerts_get_advice_and_known_people_are_not_detector_errors():
    g = _groups()
    door = g[("fa_door", "INTRUSION")]
    assert door["false_rate"] == 0.6 and "active hours" in door["suggestion"]["text"]
    assert door["reasons"] == {"false_detection": 3, "known_person": 1}
    yard = g[("fa_yard", "CRIMINAL_DETECTED")]
    assert yard["false_rate"] == 0 and yard["suggestion"] is None


def test_sorted_worst_first():
    rates = [g["false_rate"] for g in client.get("/api/v1/analytics/false-alerts", headers=_auth()).json()["groups"]]
    assert rates == sorted(rates, reverse=True)
