"""A criminal alert on a camera is auto-assigned to that camera's police officer and SMSed to them."""
import asyncio
import os
import sys
import types

os.environ["DATABASE_URL"] = "sqlite:///./test_officer.db"
os.environ["USE_SQLITE"] = "false"
sys.modules.setdefault("face_recognition", types.ModuleType("face_recognition"))

from unittest.mock import AsyncMock, patch  # noqa: E402

from backend.db.database import Base, SessionLocal, engine, init_db  # noqa: E402
from backend.models.camera import Camera  # noqa: E402
from backend.models.camera_officer import CameraOfficer  # noqa: E402
from backend.models.incident import Incident  # noqa: E402
from backend.models.known_person import KnownPerson  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.services import alert_dispatcher as ad  # noqa: E402
from backend.services import officer_dispatch as od  # noqa: E402


def test_alert_routes_to_assigned_officer(monkeypatch):
    monkeypatch.setenv("ALERTS_ENABLED", "true")
    monkeypatch.setenv("SMS_WEBHOOK", "http://sms.test/send")
    init_db()
    db = SessionLocal()
    db.add_all([
        User(username="off1", email="o1@t", hashed_password="x", role="police", phone="+8801700000001"),
        User(username="off2", email="o2@t", hashed_password="x", role="police"),
        Camera(camera_id="gate_a", name="Gate A", lat=23.8, lng=90.4),
        Camera(camera_id="gate_b", name="Gate B", lat=23.9, lng=90.5),
        KnownPerson(person_id="X", name="Test Crook", category="criminal", criminal_status="wanted"),
    ])
    db.commit()
    o1 = db.query(User).filter(User.username == "off1").first()
    db.add(CameraOfficer(camera_id="gate_a", user_id=o1.id, priority=0))
    db.commit()
    db.close()

    loop = asyncio.get_event_loop_policy().new_event_loop()
    posted = []

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, timeout=None): posted.append((url, json))

    with patch.object(ad, "broadcast_live_event", new=AsyncMock(side_effect=lambda **kw: dict(kw.get("extra") or {}))), \
         patch.object(ad.manager, "broadcast", new=AsyncMock()), \
         patch.object(od.httpx, "AsyncClient", FakeClient):
        res = loop.run_until_complete(ad.dispatch_alert(
            alert_type="CRIMINAL_DETECTED", severity="critical", person_name="X",
            camera_id="gate_a", camera_location="Gate A"))
        assert [o["name"] for o in res["payload"]["assigned_officers"]] == ["off1"]
        assert len(posted) == 1 and posted[0][1]["to"] == "+8801700000001"
        assert "Test Crook" not in posted[0][1]["message"] or "unverified" in posted[0][1]["message"]
        assert "23.80000,90.40000" in posted[0][1]["message"]            # camera coordinates

        db = SessionLocal()
        inc = db.query(Incident).filter(Incident.alert_id == res["alert_id"]).first()
        assert inc.assigned_name == "off1"
        db.close()

        # a camera with no officer: alert still raised, nobody paged
        posted.clear()
        res2 = loop.run_until_complete(ad.dispatch_alert(
            alert_type="CRIMINAL_DETECTED", severity="critical", person_name="X", camera_id="gate_b"))
        assert res2["payload"]["assigned_officers"] == [] and posted == []
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
