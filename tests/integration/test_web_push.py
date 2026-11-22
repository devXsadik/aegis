"""Web Push: subscribe/unsubscribe, VAPID header, who is pushed, gone devices removed."""

import asyncio
import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_web_push.db")

from backend.main import app  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.camera_officer import CameraOfficer  # noqa: E402
from backend.models.push_subscription import PushSubscription  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.services import web_push  # noqa: E402

client = TestClient(app)
API = "/api/v1/responder/push"


def _auth(name, role="police"):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == name).first()
    if not u:
        u = User(username=name, email=f"{name}@t.local", hashed_password=hash_password("pass12345678"), role=role, is_active=True)
        db.add(u)
        db.commit()
    uid, token = u.id, issue_token(u)
    db.close()
    return uid, {"Authorization": f"Bearer {token}"}


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_vapid_header_is_a_valid_es256_jwt(tmp_path, monkeypatch):
    monkeypatch.setattr(web_push, "KEY_FILE", tmp_path / "vapid.pem")
    monkeypatch.setattr(web_push, "_key", None)
    auth = web_push.vapid_header("https://fcm.googleapis.com/fcm/send/abc", now=1_000)
    jwt, k = auth.removeprefix("vapid t=").split(", k=")
    head, claims, sig = jwt.split(".")
    assert json.loads(_unb64(claims)) == {"aud": "https://fcm.googleapis.com", "exp": 1_000 + 43200,
                                          "sub": os.getenv("VAPID_SUBJECT", "https://localhost")}
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _unb64(k))
    raw = _unb64(sig)
    pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
               f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))      # raises if wrong
    assert (tmp_path / "vapid.pem").exists() and oct((tmp_path / "vapid.pem").stat().st_mode)[-3:] == "600"


def test_subscribe_targets_and_cleanup(monkeypatch):
    a_id, a = _auth("push_assigned")
    f_id, f = _auth("push_free", "operator")
    o_id, o = _auth("push_other")
    db = SessionLocal()
    db.query(PushSubscription).delete()
    db.query(CameraOfficer).filter(CameraOfficer.user_id.in_([a_id, o_id])).delete()
    db.add_all([CameraOfficer(camera_id="push_cam", user_id=a_id), CameraOfficer(camera_id="elsewhere", user_id=o_id)])
    db.commit()
    db.close()
    assert client.get(API, headers=a).json()["public_key"]
    assert client.post(API, headers=a, json={"endpoint": "http://insecure"}).status_code == 422
    for hdr, ep in ((a, "https://push.example/a"), (f, "https://push.example/f"), (o, "https://push.example/o")):
        assert client.post(API, headers=hdr, json={"endpoint": ep}).json() == {"subscribed": True}
    assert client.post(API, headers=a, json={"endpoint": "https://push.example/a"}).status_code == 200   # same device again
    assert client.get(API, headers=a).json()["devices"] == 1

    sent = []

    async def fake_send(_client, endpoint):
        sent.append(endpoint)
        return 410 if endpoint.endswith("/f") else 201
    monkeypatch.setattr(web_push, "_send", fake_send)
    assert asyncio.run(web_push.notify("push_cam", "critical")) == 1
    assert sorted(sent) == ["https://push.example/a", "https://push.example/f"]     # not the officer of another camera
    assert client.get(API, headers=f).json()["devices"] == 0                         # gone (410) removed
    assert asyncio.run(web_push.notify("push_cam", "low")) == 0
    assert client.request("DELETE", API, headers=a, json={"endpoint": "https://push.example/a"}).json()["removed"] == 1
