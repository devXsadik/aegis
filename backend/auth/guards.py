"""Shared request guards: internal pipeline key, media viewer token, path containment."""

import hmac
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth.auth import ROLES_OPS, request_token, user_from_token
from backend.db.database import SessionLocal, get_db
from backend.models.user import User

_INSECURE_INTERNAL_KEYS = {"", "pipeline-internal-key-change-me", "CHANGE_THIS_INTERNAL_API_KEY"}


def internal_key_is_secure() -> bool:
    return os.getenv("INTERNAL_API_KEY", "") not in _INSECURE_INTERNAL_KEYS


def verify_internal_key(key: Optional[str]) -> None:
    """Pipeline→backend auth. Fails closed when the key is unset or a known default."""
    expected = os.getenv("INTERNAL_API_KEY", "")
    if expected in _INSECURE_INTERNAL_KEYS:
        raise HTTPException(status_code=503, detail="Internal API key not configured")
    if not key or not hmac.compare_digest(key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid internal API key")


def viewer_user(token: Optional[str], db: Session) -> User:
    """Resolve the user behind a session for <img>/<video>/WebSocket requests (see request_token).

    A session is always required, in every environment, and the user must hold an
    operational role and be active.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Token required")
    try:
        user = user_from_token(token, db)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid token")
    if user.role not in ROLES_OPS and user.role != "viewer":
        raise HTTPException(status_code=403, detail="Operational access required")
    return user


def verify_viewer_token(token: Optional[str]) -> User:
    """Session-less variant for endpoints that don't otherwise hold a DB session."""
    db = SessionLocal()
    try:
        return viewer_user(token, db)
    finally:
        db.close()


def viewer_dep(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependency for media endpoints: session cookie (browser) or Bearer header.
    The viewer role (a wall display) gets live video only: no faces, evidence or captures."""
    user = viewer_user(request_token(request), db)
    if user.role == "viewer" and not request.url.path.startswith("/api/v1/stream"):
        raise HTTPException(status_code=403, detail="Operational access required")
    return user


def safe_media_path(raw: str, base: Path, root: Path) -> Path:
    """Resolve a stored path and require it to stay inside `base`."""
    p = Path(raw)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if not p.is_relative_to(base.resolve()):
        raise HTTPException(status_code=403, detail="Path outside media directory")
    return p
