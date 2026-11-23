"""Command reports: response times per stage, patterns, camera uptime, access."""
import json
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import SessionLocal, init_db
from backend.models.alert import Alert
from backend.models.camera import Camera
from backend.models.incident import Incident, IncidentEvent
from backend.models.jurisdiction import Jurisdiction
from backend.models.user import User
from backend.services import reports
from clock import utcnow

client = TestClient(app)
R = uuid.uuid4().hex[:6]


def _token(role):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = User(username=f"rp_{role}_{R}", email=f"rp_{role}_{R}@t.local", hashed_password=hash_password("pass12345678"), role=role, is_active=True)
    db.add(u)
    db.commit()
    t = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {t}"}


def test_stage_times_from_the_timeline():
    t0 = utcnow() - timedelta(hours=1)
    inc = Incident(ticket_id="X", title="t", created_at=t0, resolved_at=t0 + timedelta(minutes=30))
    ev = lambda kind, sec, payload=None, msg="": IncidentEvent(event_type=kind, message=msg, created_at=t0 + timedelta(seconds=sec),
                                                              payload=json.dumps(payload) if payload else None)
    events = [ev("ASSIGNED", 5, msg="Case owner: op"),           # case owner is not a dispatch
              ev("ASSIGNED", 60, msg="Assigned karim"),
              ev("OFFICER_STATE", 90, {"state": "acknowledged"}),
              ev("OFFICER_STATE", 120, {"state": "en_route"}),
              ev("OFFICER_STATE", 600, {"state": "on_scene"})]
    assert reports.stage_times(inc, events) == {"dispatch": 60, "acknowledge": 90, "arrive": 600, "resolve": 1800}
    assert reports.stage_times(inc, [])["dispatch"] is None


def test_report_endpoints_by_area_and_role():
    op, police = _token("operator"), _token("police")
    db = SessionLocal()
    district = Jurisdiction(code=f"D-{R}", name_en=f"District {R}", level="district")
    db.add(district)
    db.flush()
    thana = Jurisdiction(code=f"T-{R}", name_en=f"Thana {R}", level="thana", parent_id=district.id)
    db.add(thana)
    db.flush()
    t0 = utcnow() - timedelta(hours=2)
    inc = Incident(ticket_id=f"INC-R{R}", title="report test", priority="critical", jurisdiction_id=thana.id,
                   created_at=t0, resolved_at=t0 + timedelta(minutes=20))
    db.add(inc)
    db.flush()
    db.add_all([IncidentEvent(incident_id=inc.id, event_type="ASSIGNED", message="Assigned x", created_at=t0 + timedelta(seconds=30)),
                IncidentEvent(incident_id=inc.id, event_type="RESPONDER_ON_SCENE", message="x", created_at=t0 + timedelta(minutes=8))])
    cam = Camera(camera_id=f"up_{R}", name=f"Uptime cam {R}", location="x", active=True)
    db.add(cam)
    now = utcnow()
    db.add_all([Alert(alert_type="CAMERA_OFFLINE", camera_id=cam.camera_id, severity="high", timestamp=now - timedelta(hours=10)),
                Alert(alert_type="CAMERA_RESTORED", camera_id=cam.camera_id, severity="info", timestamp=now - timedelta(hours=8)),
                Alert(alert_type="CAMERA_OFFLINE", camera_id=cam.camera_id, severity="high", timestamp=now - timedelta(hours=1))])
    db.commit()
    did, tid = district.id, thana.id
    db.close()

    rt = client.get(f"/api/v1/reports/response-times?days=7&jurisdiction_id={did}", headers=op).json()
    assert rt["incidents"] == 1                                   # the district includes its thana
    assert rt["overall"]["dispatch"]["median_s"] == 30 and rt["overall"]["arrive"]["median_s"] == 480
    assert rt["by_area"][0]["name"] == f"Thana {R}" and rt["by_priority"]["critical"]["resolve"]["median_s"] == 1200
    pat = client.get(f"/api/v1/reports/patterns?days=7&jurisdiction_id={tid}", headers=op).json()
    assert sum(map(sum, pat["grid"])) == 1 and pat["peak"]["count"] == 1 and pat["by_area"][0]["incidents"] == 1
    up = client.get("/api/v1/reports/camera-uptime?days=1", headers=op).json()
    mine = next(c for c in up["cameras"] if c["camera_id"] == f"up_{R}")
    assert mine["outages"] == 2 and mine["down_now"] and abs(mine["downtime_s"] - 3 * 3600) < 120
    assert 87 < mine["uptime_pct"] < 88
    assert client.get("/api/v1/reports/response-times", headers=police).status_code == 403
