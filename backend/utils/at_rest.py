"""Encryption at rest for stored images: evidence stills, capture stills, enrolment photos.

All three are personal data (faces). With ENCRYPT_AT_REST=true (default) new images are stored
AES-GCM encrypted (backend.utils.encryption, key from ENCRYPTION_KEY/ENCRYPTION_SALT) and the
row's `encrypted` flag says so; older plaintext rows stay readable. Hashes (content_sha256) are
always of the plaintext JPEG, so exported images can be checked against them.
scripts/encrypt_existing.py encrypts rows stored before this was on.
"""

import os
from typing import Optional, Tuple


def enabled() -> bool:
    return os.getenv("ENCRYPT_AT_REST", "true").lower() in {"1", "true", "yes"}


def seal(data: bytes) -> Tuple[bytes, bool]:
    """(bytes to store, encrypted?)"""
    if not enabled():
        return data, False
    from backend.utils.encryption import EncryptionManager
    return EncryptionManager().encrypt(data), True


def unseal(data: Optional[bytes], encrypted: bool) -> Optional[bytes]:
    if not data or not encrypted:
        return data
    from backend.utils.encryption import EncryptionManager
    return EncryptionManager().decrypt(data)
