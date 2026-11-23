import os
import secrets
from datetime import timedelta
from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.models.user import User
from clock import utcnow

# No built-in fallback: with SECRET_KEY unset, a random per-process key is used, so tokens
# cannot be forged with a value read from the source (they just stop working on restart).
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

security = HTTPBearer(auto_error=False)

# The dashboard's session lives in an httpOnly cookie: page scripts (and so an XSS) cannot read
# it, and <img>/<video>/WebSocket requests carry it without a token in the URL. SameSite=Strict
# keeps other sites from riding on it. Scripts and API clients keep using a Bearer header.
SESSION_COOKIE = "aegis_session"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}   # true behind HTTPS


def request_token(conn) -> Optional[str]:
    """Bearer header if present, else the session cookie. `conn`: a Request or WebSocket."""
    auth = conn.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return conn.cookies.get(SESSION_COOKIE)


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60, path="/",
        httponly=True, samesite="strict", secure=COOKIE_SECURE,
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=COOKIE_SECURE)


def _to_bytes(password: str) -> bytes:
    # bcrypt limit is 72 bytes
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    expire = utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def issue_token(user: User) -> str:
    """Token bound to the user's current token_version (see revoke_tokens)."""
    return create_access_token({"user_id": user.id, "role": user.role, "tv": user.token_version or 0})


def revoke_tokens(user: User) -> None:
    """Invalidate every token already issued to this user (password change, demotion, disable)."""
    user.token_version = (user.token_version or 0) + 1


def user_from_token(token: Optional[str], db: Session) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    # Disabled accounts fall through: both callers reject them with their own "disabled" answer.
    if user.is_active and payload.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="Session revoked. Sign in again.")
    return user


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    user = user_from_token(credentials.credentials if credentials else request.cookies.get(SESSION_COOKIE), db)
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")   # applies to every role guard
    return user


# National-security role matrix (least privilege → most)
ROLES_OPS = frozenset({"admin", "supervisor", "operator", "police", "investigator"})
ROLES_COMMAND = frozenset({"admin", "supervisor"})
ROLES_ADMIN = frozenset({"admin"})
# ml_engineer: datasets / model registry only. auditor: read-only audit trail. Neither is an
# operational role, so neither sees alerts, faces or evidence.
VALID_ROLES = frozenset({
    "admin", "supervisor", "operator", "police", "investigator", "viewer", "ml_engineer", "auditor",
})
ROLES_AUDIT = frozenset({"admin", "auditor"})
ROLES_ML = frozenset({"admin", "ml_engineer"})


# The viewer role is a wall display: it may look at the live picture (alerts, cameras, map,
# status) and change nothing. Personal and investigative data stays with operational roles.
VIEWER_DENIED_PATHS = (
    "/api/v1/faces", "/api/v1/evidence", "/api/v1/captures", "/api/v1/reid", "/api/v1/custody",
    "/api/v1/reports", "/api/v1/incidents", "/api/v1/shift", "/api/v1/vehicles", "/api/v1/audit",
    "/api/v1/calibration", "/api/v1/recordings", "/api/v1/vms", "/api/v1/responder", "/api/v1/auth/assignees",
    "/api/v1/officers", "/api/v1/watchlist", "/api/v1/detections", "/api/v1/vehicle-search", "/api/v1/vehicle-match", "/api/v1/lookouts", "/api/v1/tracks", "/api/v1/camera-graph", "/api/v1/notifications",
)


def viewer_may_read(user: User, request: Request) -> bool:
    return (user.role == "viewer" and request.method == "GET"
            and not request.url.path.startswith(VIEWER_DENIED_PATHS))


def operator_or_admin(request: Request, user: User = Depends(get_current_user)) -> User:
    """Any operational role can view alerts, evidence, cameras, analytics; viewers may read
    the live picture (GET, outside VIEWER_DENIED_PATHS) and nothing else."""
    if viewer_may_read(user, request):
        return user
    if user.role not in ROLES_OPS:
        raise HTTPException(status_code=403, detail="Operational access required")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    return user


def supervisor_or_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ROLES_COMMAND:
        raise HTTPException(status_code=403, detail="Supervisor or admin access required")
    return user


def admin_only(user: User = Depends(get_current_user)) -> User:
    if user.role not in ROLES_ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def auditor_or_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ROLES_AUDIT:
        raise HTTPException(status_code=403, detail="Auditor or admin access required")
    return user


def ml_or_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ROLES_ML:
        raise HTTPException(status_code=403, detail="ML engineer or admin access required")
    return user
