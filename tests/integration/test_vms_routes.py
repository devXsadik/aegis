"""Recordings (segments, timeline, playback, thumbnails, retention) and digital PTZ.

The recordings folder is a temp dir for every test: segment ingest runs a retention purge,
which must never reach the real data/recordings."""

import os
from datetime import timedelta

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_vms_routes.db")

from backend.main import app  # noqa: E402
from backend.api import vms_routes  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.recording import RecordingClip  # noqa: E402
from backend.models.user import User  # noqa: E402
from clock import utcnow  # noqa: E402

client = TestClient(app)
KEY = {"X-Internal-Key": os.environ["INTERNAL_API_KEY"]}
API = "/api/v1/vms"


def _auth(role="operator"):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    name = f"vms_{role}"
    u = db.query(User).filter(User.username == name).first()
    if not u:
        u = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"), role=role, is_active=True)
        db.add(u)
        db.commit()
    token = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def rec(tmp_path, monkeypatch):
    root = tmp_path
    recordings = root / "data" / "recordings"
    (recordings / "vms_cam" / "continuous").mkdir(parents=True)
    monkeypatch.setattr(vms_routes, "ROOT", root)
    monkeypatch.setattr(vms_routes, "RECORDINGS_DIR", recordings)
    init_db()
    db = SessionLocal()
    db.query(RecordingClip).filter(RecordingClip.camera_id == "vms_cam").delete()
    db.commit()
    db.close()
    return recordings


def _clip(path):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 8, (160, 120))
    for i in range(16):
        w.write(np.full((120, 160, 3), i * 12, np.uint8))
    w.release()
    cv2.imwrite(str(path.with_suffix(".jpg")), np.full((90, 160, 3), 100, np.uint8))
    return path


def _ingest(rec, minutes_ago=5, trigger="continuous"):
    start = utcnow() - timedelta(minutes=minutes_ago)
    path = _clip(rec / "vms_cam" / "continuous" / f"seg{minutes_ago}.mp4")
    r = client.post(f"{API}/segments", headers=KEY, json={
        "camera_id": "vms_cam", "camera_location": "Lab", "started_at": start.isoformat(),
        "ended_at": (start + timedelta(seconds=60)).isoformat(), "duration_seconds": 60, "trigger": trigger,
        "file_path": str(path), "thumbnail_path": str(path.with_suffix(".jpg")), "frame_count": 16})
    assert r.status_code == 200, r.text
    return r.json()["id"], start


def test_segments_timeline_playback_and_thumbnail(rec):
    hdr = _auth()
    clip_id, start = _ingest(rec)
    tl = client.get(f"{API}/timeline?camera_id=vms_cam&hours=1", headers=hdr).json()
    assert tl["segment_count"] == 1 and tl["segments"][0]["has_thumb"] and tl["continuous_coverage_hours"] == round(60 / 3600, 2)
    play = client.get(f"{API}/playback", headers=hdr, params={"camera_id": "vms_cam", "t": (start + timedelta(seconds=25)).isoformat()})
    assert play.status_code == 200 and play.headers["content-type"] == "video/mp4"
    assert float(play.headers["x-seek-offset-seconds"]) == pytest.approx(25, abs=0.01)
    assert client.get(f"{API}/segments/{clip_id}/thumb", headers=hdr).headers["content-type"] == "image/jpeg"
    assert client.get(f"{API}/playback", headers=hdr, params={"camera_id": "nope", "t": start.isoformat()}).status_code == 404
    assert client.get(f"{API}/playback", headers=hdr, params={"camera_id": "vms_cam", "t": "yesterday"}).status_code == 400


def test_segment_ingest_is_pipeline_only_and_stays_in_the_recordings_folder(rec, tmp_path):
    body = {"camera_id": "vms_cam", "started_at": utcnow().isoformat(), "file_path": str(tmp_path / "x.mp4")}
    assert client.post(f"{API}/segments", json=body).status_code == 401
    assert client.post(f"{API}/segments", headers=KEY, json=body).status_code == 403     # outside recordings


def test_retention_purge_is_admin_only(rec):
    _ingest(rec, minutes_ago=5)
    assert client.post(f"{API}/retention/purge", headers=_auth()).status_code == 403
    r = client.post(f"{API}/retention/purge", headers=_auth("admin")).json()
    assert r["retention_hours"] == float(os.getenv("DVR_RETENTION_HOURS", "48")) and r["purged_rows"] == 0


def test_digital_ptz_moves_zooms_saves_presets_and_goes_home():
    hdr = _auth()
    cam = "vms_ptz"
    assert client.post(f"{API}/ptz/{cam}/mode", headers=hdr, json={"mode": "digital"}).status_code == 200
    st = client.post(f"{API}/ptz/{cam}/absolute", headers=hdr, json={"pan": 0.3, "tilt": -0.2, "zoom": 2.0}).json()["digital"]
    assert st["zoom"] == 2.0 and st["pan"] == 0.3
    client.post(f"{API}/ptz/{cam}/presets", headers=hdr, json={"name": "door"})
    client.post(f"{API}/ptz/{cam}/home", headers=hdr)
    assert client.get(f"{API}/ptz/{cam}", headers=hdr).json()["digital"]["zoom"] == 1.0
    back = client.post(f"{API}/ptz/{cam}/presets/door/goto", headers=hdr).json()
    assert back["digital"]["zoom"] == 2.0 and back["digital"]["pan"] == 0.3 and back["presets"] == ["door"]
    moved = client.post(f"{API}/ptz/{cam}/move", headers=hdr, json={"pan": 0.1, "tilt": 0, "zoom": 0.5}).json()["digital"]
    assert moved["pan"] != 0.3 or moved["zoom"] != 2.0
    assert client.post(f"{API}/ptz/{cam}/stop", headers=hdr).status_code == 200
    assert client.post(f"{API}/ptz/{cam}/presets/missing/goto", headers=hdr).status_code in (404, 400)
    from backend.services import ptz
    frame = np.full((480, 640, 3), 50, np.uint8)
    assert ptz.apply_digital_crop(frame, cam).shape == frame.shape                 # zoomed crop, same size


def test_ptz_settings_persist_and_follow_gates_the_tracker():
    from backend.services import ptz
    admin, op = _auth("admin"), _auth("operator")
    cam = "ptz_follow_cam"
    r = client.post(f"/api/v1/vms/ptz/{cam}/onvif", headers=admin,
                    json={"host": "http://192.0.2.10", "username": "ptz", "password": "s3cret-pw"})
    assert r.status_code == 200 and r.json()["onvif"]["configured"]
    move = {"action": "move", "pan": 0.5, "tilt": 0, "zoom": 0}
    assert client.post(f"/api/v1/vms/ptz/{cam}/track", headers=KEY, json=move).json() == {"following": False}
    assert client.post(f"/api/v1/vms/ptz/{cam}/track", json=move).status_code in (401, 403)
    assert client.post(f"/api/v1/vms/ptz/{cam}/follow", headers=op, json={"enabled": True}).json()["follow"] is True
    ptz._states.clear()
    ptz._loaded.clear()                                          # a restart, or another API worker
    st = client.get(f"/api/v1/vms/ptz/{cam}", headers=op).json()
    assert st["follow"] is True and st["onvif"]["host"] == "http://192.0.2.10"
    assert ptz.get_state(cam).onvif_pass == "s3cret-pw"
    from backend.db.database import SessionLocal
    from backend.models.config_entry import ConfigEntry
    db = SessionLocal()
    raw = db.query(ConfigEntry).filter(ConfigEntry.key == f"ptz:{cam}").first().value
    db.close()
    assert "s3cret-pw" not in raw                                # password is sealed at rest
    out = client.post(f"/api/v1/vms/ptz/{cam}/track", headers=KEY, json=move).json()
    assert out == {"following": True, "action": "move"}
    client.post(f"/api/v1/vms/ptz/{cam}/follow", headers=op, json={"enabled": False})
