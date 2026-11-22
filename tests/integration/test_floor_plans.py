"""Floor plans: admin uploads/moves/deletes, everyone on the map reads, bad input refused."""

import os

import cv2
import numpy as np
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_floor_plans.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.user import User  # noqa: E402

client = TestClient(app)
API = "/api/v1/map/floorplans"
BOX = {"south": "23.80", "west": "90.40", "north": "23.801", "east": "90.4015"}


def _auth(role):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    name = f"fp_{role}"
    u = db.query(User).filter(User.username == name).first()
    if not u:
        u = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"), role=role, is_active=True)
        db.add(u)
        db.commit()
    token = issue_token(u)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def _png(w=5000, h=2500):
    img = np.full((h, w, 3), 255, np.uint8)
    cv2.rectangle(img, (100, 100), (w - 100, h - 100), (0, 0, 0), 20)
    return cv2.imencode(".png", img)[1].tobytes()


def test_floor_plan_lifecycle():
    admin, op, viewer = _auth("admin"), _auth("operator"), _auth("viewer")
    files = {"file": ("plan.png", _png(), "image/png")}
    assert client.post(API, headers=op, data={"name": "HQ", **BOX}, files=files).status_code == 403
    plan = client.post(API, headers=admin, data={"name": "HQ ground floor", **BOX}, files=files).json()
    assert (plan["width"], plan["height"]) == (4000, 2000)                         # scaled down
    assert plan["bounds"] == [[23.80, 90.40], [23.801, 90.4015]]
    img = client.get(f"{API}/{plan['id']}/image", headers=viewer)                    # wall screens see it too
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert any(p["id"] == plan["id"] for p in client.get(API, headers=op).json())
    moved = client.put(f"{API}/{plan['id']}", headers=admin,
                       json={"bounds": [[23.7, 90.3], [23.702, 90.303]], "opacity": 0.5}).json()
    assert moved["bounds"][0] == [23.7, 90.3] and moved["opacity"] == 0.5
    assert client.put(f"{API}/{plan['id']}", headers=admin, json={"bounds": [[23.8, 90.4], [23.7, 90.5]]}).status_code == 400
    assert client.delete(f"{API}/{plan['id']}", headers=admin).json() == {"deleted": plan["id"]}
    assert client.get(f"{API}/{plan['id']}/image", headers=op).status_code == 404


def test_rejects_bad_uploads():
    admin = _auth("admin")
    assert client.post(API, headers=admin, data={"name": "x", **BOX},
                       files={"file": ("x.png", b"<svg onload=alert(1)>", "image/png")}).status_code == 400
    assert client.post(API, headers=admin, data={"name": "x", **BOX, "north": "25"},
                       files={"file": ("p.png", _png(50, 50), "image/png")}).status_code == 400   # whole region
