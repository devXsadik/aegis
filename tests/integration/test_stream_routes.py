"""Live video: the pipeline pushes JPEG frames, signed-in operators pull them."""

import os
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_stream_routes.db")

from backend.main import app  # noqa: E402
from backend.api import stream_routes  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.user import User  # noqa: E402

client = TestClient(app)
KEY = {"X-Internal-Key": os.environ["INTERNAL_API_KEY"]}
API = "/api/v1/stream"


def _jpeg(v=90):
    ok, buf = cv2.imencode(".jpg", np.full((48, 64, 3), v, np.uint8))
    assert ok
    return buf.tobytes()


def _auth(role="operator"):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    name = f"stream_{role}"
    user = db.query(User).filter(User.username == name).first()
    if not user:
        user = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"),
                    role=role, is_active=True)
        db.add(user)
        db.commit()
    token = issue_token(user)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def setup_function():
    stream_routes._frames.clear()


def test_only_the_pipeline_can_push_frames():
    assert client.post(f"{API}/frame/cam_a", content=_jpeg()).status_code == 401
    assert client.post(f"{API}/frame/cam_a", content=_jpeg(), headers={"X-Internal-Key": "wrong"}).status_code == 401
    assert client.post(f"{API}/frame/cam_a", content=b"", headers=KEY).status_code == 400
    assert client.post(f"{API}/frame/cam_a", content=_jpeg(), headers=KEY).status_code == 200


def test_viewers_need_an_operational_role():
    client.post(f"{API}/frame/cam_a", content=_jpeg(), headers=KEY)
    assert client.get(f"{API}/cameras").status_code == 401
    assert client.get(f"{API}/cam_a/snapshot", headers=_auth("viewer")).status_code == 403
    assert client.get(f"{API}/cameras", headers=_auth()).json() == {"cameras": ["cam_a"]}


def test_snapshot_returns_the_newest_frame_and_404s_when_stale(monkeypatch):
    hdr = _auth()
    client.post(f"{API}/frame/cam_a", content=_jpeg(10), headers=KEY)
    client.post(f"{API}/frame/cam_a", content=_jpeg(200), headers=KEY)
    snap = client.get(f"{API}/cam_a/snapshot", headers=hdr)
    assert snap.status_code == 200 and snap.headers["content-type"] == "image/jpeg"
    assert snap.content == _jpeg(200)
    assert snap.headers["cache-control"] == "no-store"
    assert client.get(f"{API}/nope/snapshot", headers=hdr).status_code == 404

    real = time.monotonic
    monkeypatch.setattr(stream_routes.time, "monotonic", lambda: real() + stream_routes.FRAME_STALE_SECONDS + 1)
    assert client.get(f"{API}/cam_a/snapshot", headers=hdr).status_code == 404
    assert client.get(f"{API}/cameras", headers=hdr).json() == {"cameras": []}


def test_digital_ptz_leaves_frames_alone_when_not_zoomed():
    raw = _jpeg()
    assert stream_routes._frame_with_digital_ptz("cam_a", raw) == raw
    assert stream_routes._frame_with_digital_ptz("cam_a", b"not a jpeg") == b"not a jpeg"
