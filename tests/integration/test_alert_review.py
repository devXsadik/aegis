"""Watchlist alerts hold external webhooks until an operator confirms."""
import asyncio
import os
import sys
import types

os.environ["DATABASE_URL"] = "sqlite:///./test_review.db"
os.environ["USE_SQLITE"] = "false"
sys.modules.setdefault("face_recognition", types.ModuleType("face_recognition"))

from unittest.mock import AsyncMock, patch  # noqa: E402

from backend.db.database import Base, SessionLocal, engine, init_db  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.services import alert_dispatcher as ad  # noqa: E402


def test_criminal_alert_holds_webhooks_then_releases():
    init_db()
    ok = asyncio.get_event_loop_policy().new_event_loop()
    with patch.object(ad, "_send_webhooks", new=AsyncMock(return_value="law_enforcement")) as sw, \
         patch.object(ad, "broadcast_live_event", new=AsyncMock(return_value={})), \
         patch.object(ad.manager, "broadcast", new=AsyncMock()):
        res = ok.run_until_complete(ad.dispatch_alert(
            alert_type="CRIMINAL_DETECTED", severity="critical", person_name="X"))
        sw.assert_not_called()
        db = SessionLocal()
        from backend.models.alert import Alert
        a = db.query(Alert).get(res["alert_id"])
        assert a.review_status == "pending" and "law" not in (a.channels_sent or "")
        assert "unverified" in a.message
        ok.run_until_complete(ad.release_held_webhooks(a))
        sw.assert_called_once()
        db.close()
        # non-identification alert is not held
        ok.run_until_complete(ad.dispatch_alert(alert_type="WEAPON_DETECTED", severity="critical"))
        assert sw.call_count == 2
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    try:
        os.remove("test_review.db")
    except OSError:
        pass
