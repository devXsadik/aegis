"""Nightly maintenance: evidence retention keeps the record and custody, backups rotate."""

import json
import os
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_maintenance.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.capture import AlertCapture  # noqa: E402
from backend.models.custody import CustodyRecord  # noqa: E402
from backend.models.evidence import Evidence  # noqa: E402
from backend.models.incident import Incident  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.services import backup, maintenance  # noqa: E402
from clock import utcnow  # noqa: E402
from utils.data.retention import RetentionPolicy  # noqa: E402

client = TestClient(app)


def _evidence(days_old, **kw):
    db = SessionLocal()
    e = Evidence(camera_location="MT", track_id=1, category="suspicious", frame_data=b"\xff\xd8f", roi_data=b"\xff\xd8r",
                 timestamp=utcnow() - timedelta(days=days_old), **kw)
    db.add(e)
    db.commit()
    eid = e.id
    db.close()
    return eid


def test_retention_purges_images_but_keeps_record_custody_and_open_cases(tmp_path):
    init_db()
    old, fresh, held = _evidence(100), _evidence(5), _evidence(100)
    db = SessionLocal()
    db.add(Incident(ticket_id=f"MT-{held}", title="Open case", status="investigating", evidence_id=held))
    db.commit()
    db.close()

    dry = RetentionPolicy({"enabled": True, "evidence_days": 90, "archive_path": str(tmp_path), "dry_run": True}).run()
    assert dry["purged"] >= 1
    r = RetentionPolicy({"enabled": True, "evidence_days": 90, "archive_path": str(tmp_path)}).run()
    assert r["status"] == "completed" and r["held"] >= 1

    db = SessionLocal()
    o, f, h = db.get(Evidence, old), db.get(Evidence, fresh), db.get(Evidence, held)
    assert o is not None and o.frame_data is None and o.roi_data is None        # record kept, images gone
    assert f.frame_data and h.frame_data                                         # too new / legal hold
    assert db.query(CustodyRecord).filter(CustodyRecord.evidence_id == old, CustodyRecord.action == "PURGED").count() == 1
    db.close()
    assert json.loads((tmp_path / f"evidence_{old}.json").read_text())["id"] == old
    again = RetentionPolicy({"enabled": True, "evidence_days": 90, "archive_path": str(tmp_path)}).run()
    db = SessionLocal()
    assert db.query(CustodyRecord).filter(CustodyRecord.evidence_id == old, CustodyRecord.action == "PURGED").count() == 1
    db.close()
    assert again["status"] == "completed"                                         # nothing purged twice


def test_capture_purge_and_maintenance_runs_every_step(monkeypatch, tmp_path):
    init_db()
    db = SessionLocal()
    db.add(AlertCapture(alert_type="X", timestamp=utcnow() - timedelta(days=30), image_data=b"x"))
    db.commit()
    db.close()
    monkeypatch.setenv("CAPTURE_RETENTION_DAYS", "7")
    assert maintenance.purge_captures()["rows"] >= 1
    monkeypatch.setattr(maintenance, "purge_recordings", lambda: (_ for _ in ()).throw(RuntimeError("disk gone")))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    out = maintenance.run_maintenance()
    assert out["recordings"]["status"] == "error"                                # one failure ...
    assert "rows" in out["captures"] and out["backup"]["name"]                   # ... the rest still ran


def test_backup_is_a_usable_copy_and_old_ones_rotate(monkeypatch, tmp_path):
    init_db()
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    for name in ("20260101_0300", "20260102_0300", "notes"):          # 'notes' is not ours: never touched
        (tmp_path / name).mkdir()
    info = backup.run_backup(keep=2)
    copy = tmp_path / info["name"] / "aegis.db"
    tables = {r[0] for r in sqlite3.connect(copy).execute("select name from sqlite_master where type='table'")}
    assert {"users", "alerts", "evidence", "shift_entries"} <= tables
    assert (tmp_path / info["name"] / "config" / "config.yaml").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(["20260102_0300", info["name"], "notes"])
    assert backup.list_backups()[0]["database_sha256"] == info["database_sha256"]


@pytest.fixture
def admin():
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == "mt_admin").first()
    if not u:
        u = User(username="mt_admin", email="mt@t.local", hashed_password=hash_password("pass12345678"), role="admin", is_active=True)
        db.add(u)
        db.commit()
    token = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def test_backup_endpoints_are_admin_only(admin, monkeypatch, tmp_path):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    made = client.post("/api/v1/system/backups", headers=admin).json()
    listed = client.get("/api/v1/system/backups", headers=admin).json()
    assert listed["backups"][0]["name"] == made["name"] and listed["keep"] == 7
    assert client.get("/api/v1/system/backups").status_code == 401
