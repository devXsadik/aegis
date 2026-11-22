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
})


def seed() -> None:
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
    db.close()


if __name__ == "__main__":
    import uvicorn

    seed()
    from backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("E2E_API_PORT", "8010")), log_level="warning")
