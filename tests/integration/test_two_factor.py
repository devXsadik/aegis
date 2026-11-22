"""Two-factor sign-in: setup, sign-in with a code, replay and lockout, disable, admin reset."""

import os
import time

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_two_factor.db")

from backend.main import app  # noqa: E402
from backend.auth import totp  # noqa: E402
from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.middleware import rate_limiter  # noqa: E402
from backend.models.user import User  # noqa: E402

client = TestClient(app)
API = "/api/v1/auth"
PW = "TwoFactor123!"


def _user(name, role="supervisor"):
    from backend.auth.auth import hash_password, issue_token
    init_db()
    db = SessionLocal()
    u = db.query(User).filter(User.username == name).first()
    if not u:
        u = User(username=name, email=f"{name}@t.local", role=role, is_active=True, hashed_password=hash_password(PW))
        db.add(u)
    u.totp_enabled, u.totp_secret, u.totp_last_step, u.failed_attempts, u.locked_until = False, None, None, 0, None
    db.commit()
    token = issue_token(u)
    uid = u.id
    db.close()
    return uid, {"Authorization": f"Bearer {token}"}


def setup_function():
    rate_limiter._limiter._buckets.clear()          # login attempts from other tests must not throttle these


def _code(secret, offset_steps=0):
    return totp.code_at(secret, int(time.time() // 30) + offset_steps)


def _enrol(hdr):
    s = client.post(f"{API}/2fa/setup", headers=hdr).json()
    assert s["otpauth_uri"].startswith("otpauth://totp/") and client.get(f"{API}/2fa", headers=hdr).json() == {"enabled": False, "recommended": True}
    assert client.post(f"{API}/2fa/enable", headers=hdr, json={"code": "000000" if _code(s["secret"]) != "000000" else "111111"}).status_code == 400
    assert client.post(f"{API}/2fa/enable", headers=hdr, json={"code": _code(s["secret"], -1)}).json() == {"enabled": True}
    return s["secret"]


def test_setup_then_sign_in_needs_the_code_and_a_code_works_once():
    _, hdr = _user("tf_sup")
    secret = _enrol(hdr)
    assert client.post(f"{API}/2fa/setup", headers=hdr).status_code == 409
    client.cookies.clear()
    ask = client.post(f"{API}/login", json={"username": "tf_sup", "password": PW})
    assert ask.status_code == 401 and ask.json()["detail"]["totp_required"]
    ok = client.post(f"{API}/login", json={"username": "tf_sup", "password": PW, "code": _code(secret)})
    assert ok.status_code == 200
    again = client.post(f"{API}/login", json={"username": "tf_sup", "password": PW, "code": _code(secret)})
    assert again.status_code == 401 and "not valid" in again.json()["detail"]["message"]     # replay refused
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}).json()["totp_enabled"]


def test_wrong_codes_count_towards_lockout():
    _, hdr = _user("tf_lock")
    secret = _enrol(hdr)
    wrong = "000000" if _code(secret) != "000000" else "111111"
    for _ in range(5):
        client.post(f"{API}/login", json={"username": "tf_lock", "password": PW, "code": wrong})
    locked = client.post(f"{API}/login", json={"username": "tf_lock", "password": PW, "code": _code(secret)})
    assert locked.status_code == 429


def test_disable_needs_password_and_code_and_admin_can_reset():
    uid, hdr = _user("tf_off")
    secret = _enrol(hdr)
    assert client.post(f"{API}/2fa/disable", headers=hdr, json={"password": "wrong", "code": _code(secret)}).status_code == 400
    assert client.post(f"{API}/2fa/disable", headers=hdr, json={"password": PW, "code": _code(secret)}).json() == {"enabled": False}
    _enrol(hdr)
    _, admin = _user("tf_admin", "admin")
    assert client.patch(f"{API}/users/{uid}", headers=admin, json={"reset_2fa": True}).json()["totp_enabled"] is False
    client.cookies.clear()
    assert client.post(f"{API}/login", json={"username": "tf_off", "password": PW}).status_code == 200
