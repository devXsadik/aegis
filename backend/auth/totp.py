"""Time-based one-time passwords (RFC 6238): the 6-digit codes authenticator apps show.

The shared secret is stored encrypted (backend.utils.encryption). A code is accepted in the
current 30-second step or one step either side (clock drift), and never twice: the last used
step is remembered per user, so a code seen over someone's shoulder cannot be replayed.
"""

import base64
import hashlib
import hmac
import os
import struct
import time
from typing import Optional
from urllib.parse import quote

STEP = 30
DIGITS = 6
ISSUER = "Aegis"


def new_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def matching_step(secret: str, code: str, now: Optional[float] = None, window: int = 1) -> Optional[int]:
    """The time step `code` belongs to (within ±window steps of now), or None."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == DIGITS):
        return None
    current = int((now if now is not None else time.time()) // STEP)
    for step in range(current - window, current + window + 1):
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str) -> str:
    """otpauth:// link the authenticator app reads from the QR code."""
    label = quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP}"


def seal_secret(secret: str) -> str:
    from backend.utils.encryption import EncryptionManager
    return base64.b64encode(EncryptionManager().encrypt(secret.encode())).decode()


def open_secret(sealed: str) -> str:
    from backend.utils.encryption import EncryptionManager
    return EncryptionManager().decrypt(base64.b64decode(sealed)).decode()
