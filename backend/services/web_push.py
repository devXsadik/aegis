"""Web Push for responders: a phone that has the dashboard installed buzzes on a new alert.

Standard Web Push (RFC 8030) with VAPID (RFC 8292) and an EMPTY message: no alert data
leaves the server through the push service (Google, Apple, Mozilla). The push only wakes
the service worker (frontend/public/sw.js), which then fetches the officer's own alert list
over the normal signed-in API and shows the newest one. So no payload encryption is needed,
and the push services never see a name, a camera or a place.

Who is pushed mirrors the responder list (backend/api/responder_routes.py): officers assigned
to the alert's camera; a subscribed user with no camera assignment gets every critical/high
alert. The VAPID key pair is made once and kept in data/push/vapid.pem (or VAPID_PRIVATE_KEY).
"""

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from paths import ROOT

logger = logging.getLogger(__name__)
KEY_FILE = Path(os.getenv("VAPID_KEY_FILE", ROOT / "data" / "push" / "vapid.pem"))
PUSH_SEVERITIES = {"critical", "high"}
_key: Optional[ec.EllipticCurvePrivateKey] = None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def private_key() -> ec.EllipticCurvePrivateKey:
    global _key
    if _key is None:
        pem = os.getenv("VAPID_PRIVATE_KEY", "").replace("\\n", "\n").encode()
        if not pem and KEY_FILE.exists():
            pem = KEY_FILE.read_bytes()
        if pem:
            _key = serialization.load_pem_private_key(pem, password=None)
        else:
            _key = ec.generate_private_key(ec.SECP256R1())
            KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            KEY_FILE.write_bytes(_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                    serialization.NoEncryption()))
            os.chmod(KEY_FILE, 0o600)
    return _key


def public_key() -> str:
    """The application server key the browser subscribes with (uncompressed P-256 point, base64url)."""
    return _b64(private_key().public_key().public_bytes(serialization.Encoding.X962,
                                                       serialization.PublicFormat.UncompressedPoint))


def vapid_header(endpoint: str, now: Optional[float] = None) -> str:
    u = urlparse(endpoint)
    claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int((now or time.time()) + 12 * 3600),
              "sub": os.getenv("VAPID_SUBJECT", "https://localhost")}
    signing = f"{_b64(json.dumps({'typ': 'JWT', 'alg': 'ES256'}).encode())}.{_b64(json.dumps(claims).encode())}"
    r, s = decode_dss_signature(private_key().sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
    jwt = f"{signing}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={jwt}, k={public_key()}"


async def _send(client: httpx.AsyncClient, endpoint: str) -> int:
    r = await client.post(endpoint, headers={"Authorization": vapid_header(endpoint), "TTL": "600",
                                             "Urgency": "high", "Content-Length": "0"})
    return r.status_code


def recipients(db, camera_id: Optional[str]) -> List:
    """Subscriptions of the users who would see this alert in their responder list."""
    from backend.models.camera_officer import CameraOfficer
    from backend.models.push_subscription import PushSubscription
    from backend.models.user import User
    assigned = {uid for (uid,) in db.query(CameraOfficer.user_id).distinct()}
    here = {uid for (uid,) in db.query(CameraOfficer.user_id).filter(CameraOfficer.camera_id == camera_id)} if camera_id else set()
    subs = (db.query(PushSubscription).join(User, User.id == PushSubscription.user_id)
            .filter(User.is_active == True).all())  # noqa: E712
    return [s for s in subs if s.user_id in here or s.user_id not in assigned]


async def notify(camera_id: Optional[str], severity: str) -> int:
    """Wake every recipient's device. Gone subscriptions (404/410) are removed. Returns pushes sent."""
    if severity not in PUSH_SEVERITIES or os.getenv("WEB_PUSH_ENABLED", "true").lower() == "false":
        return 0
    from backend.db.database import SessionLocal
    from backend.models.push_subscription import PushSubscription
    db = SessionLocal()
    try:
        subs = [(s.id, s.endpoint) for s in recipients(db, camera_id)]
        if not subs:
            return 0
        async with httpx.AsyncClient(timeout=8) as client:
            results = await asyncio.gather(*(_send(client, e) for _, e in subs), return_exceptions=True)
        gone = [sid for (sid, _), r in zip(subs, results) if r in (404, 410)]
        if gone:
            db.query(PushSubscription).filter(PushSubscription.id.in_(gone)).delete(synchronize_session=False)
            db.commit()
        failed = [r for r in results if isinstance(r, Exception) or (isinstance(r, int) and r >= 400 and r not in (404, 410))]
        if failed:
            logger.warning(f"Web push: {len(failed)} of {len(subs)} failed ({failed[:3]})")
        return sum(1 for r in results if isinstance(r, int) and r < 300)
    finally:
        db.close()


def notify_later(camera_id: Optional[str], severity: str) -> None:
    """Fire and forget: the alert path never waits for push services."""
    if severity not in PUSH_SEVERITIES:
        return
    task = asyncio.get_running_loop().create_task(notify(camera_id, severity))
    task.add_done_callback(lambda t: t.exception() and logger.warning(f"Web push failed: {t.exception()}"))
