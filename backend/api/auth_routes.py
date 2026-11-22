from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel, field_validator
from backend.models.audit_log import AuditLog
from backend.db.database import get_db
from backend.models.user import User
from backend.auth import totp
from backend.auth.auth import (
    hash_password, verify_password, issue_token, revoke_tokens,
    get_current_user, admin_only, operator_or_admin, VALID_ROLES, ROLES_OPS, ROLES_COMMAND,
    set_session_cookie, clear_session_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str
    code: Optional[str] = None              # two-factor code, when the account has it on


class LoginResponse(BaseModel):
    access_token: Optional[str] = None      # for API clients; the dashboard uses the session cookie
    token_type: str = "bearer"
    user_id: int
    role: str


MIN_PASSWORD = 10
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 10


def _check_password(v: str) -> str:
    if len(v) < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")
    if v.isalpha() or v.isdigit():
        raise ValueError("Password must mix letters and digits or symbols")
    return v


def _audit(db: Session, action: str, user: Optional[User], resource_id: str, details: str, request: Request = None):
    db.add(AuditLog(
        user_id=user.id if user else None, username=user.username if user else None,
        action=action, resource="user", resource_id=resource_id, details=details,
        ip_address=request.client.host if request and request.client else None,
    ))


class UserCreate(BaseModel):
    username: str
    email: str
    password: str

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        return _check_password(v)

    role: str = "viewer"
    phone: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    phone: Optional[str] = None
    totp_enabled: bool = False

    class Config:
        from_attributes = True


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    now = datetime.now(timezone.utc)
    if user and user.locked_until:
        until = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
        if until > now:
            mins = int((until - now).total_seconds() // 60) + 1
            raise HTTPException(status_code=429, detail=f"Account locked after repeated failures. Try again in {mins} min.")
    def fail(why: str, detail):
        if user:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_attempts = 0
        _audit(db, "LOGIN_FAILED", user, req.username, why, request)
        db.commit()
        raise HTTPException(status_code=401, detail=detail)

    if not user or not verify_password(req.password, user.hashed_password):
        fail("invalid credentials", "Invalid credentials")
    if not user.is_active:
        _audit(db, "LOGIN_DENIED", user, user.username, "account disabled", request)
        db.commit()
        raise HTTPException(status_code=403, detail="Account disabled")
    if user.totp_enabled:
        # Password was right; the code is asked for (no failure counted) or checked (failure counted).
        if not (req.code or "").strip():
            raise HTTPException(status_code=401, detail={"message": "Enter the 6-digit code from your authenticator app",
                                                         "totp_required": True})
        step = totp.matching_step(totp.open_secret(user.totp_secret), req.code)
        if step is None or (user.totp_last_step is not None and step <= user.totp_last_step):
            fail("invalid two-factor code", {"message": "That code is not valid. Enter the current code from your app.",
                                             "totp_required": True})
        user.totp_last_step = step              # a code works once
    user.failed_attempts = 0
    user.locked_until = None
    _audit(db, "LOGIN", user, user.username, "ok", request)
    db.commit()
    token = issue_token(user)
    set_session_cookie(response, token)
    return LoginResponse(access_token=token, user_id=user.id, role=user.role)


@router.post("/logout")
def logout(response: Response):
    """End this browser's session (the cookie cannot be removed by page scripts)."""
    clear_session_cookie(response)
    return {"status": "signed_out"}


@router.post("/users", response_model=UserResponse)
def create_user(req: UserCreate, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    if req.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Allowed: {', '.join(sorted(VALID_ROLES))}",
        )
    existing = db.query(User).filter(
        (User.username == req.username) | (User.email == req.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
        role=req.role,
        phone=(req.phone or "").strip() or None,
    )
    db.add(user)
    db.flush()
    _audit(db, "USER_CREATE", admin, user.username, f"role={user.role}", request)
    db.commit()
    db.refresh(user)
    return user


class ChangePassword(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        return _check_password(v)


@router.post("/change-password")
def change_password(body: ChangePassword, request: Request, response: Response, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.hashed_password = hash_password(body.new_password)
    revoke_tokens(user)                 # a stolen token must not outlive the password it came from
    _audit(db, "PASSWORD_CHANGE", user, user.username, "self-service", request)
    db.commit()
    token = issue_token(user)
    set_session_cookie(response, token)                                  # keeps this session signed in
    return {"status": "changed", "access_token": token}


@router.post("/logout-all")
def logout_all(request: Request, response: Response, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """Sign this account out on every device."""
    revoke_tokens(user)
    clear_session_cookie(response)
    _audit(db, "LOGOUT_ALL", user, user.username, "all sessions revoked", request)
    db.commit()
    return {"status": "revoked"}


class UserPatch(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    phone: Optional[str] = None
    new_password: Optional[str] = None
    reset_2fa: Optional[bool] = None        # lost phone: turn two-factor off so they can set it up again

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        return _check_password(v) if v is not None else v


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, body: UserPatch, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(admin_only)):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    changes = body.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Allowed: {', '.join(sorted(VALID_ROLES))}")
    if target.id == admin.id and (changes.get("is_active") is False or changes.get("role", "admin") != "admin"):
        raise HTTPException(status_code=400, detail="You cannot disable or demote your own account")
    if (changes.get("new_password") or changes.get("is_active") is False
            or changes.get("role", target.role) != target.role):
        revoke_tokens(target)           # reset, disable or role change ends the user's open sessions
    if "role" in changes:
        target.role = changes["role"]
    if "is_active" in changes and changes["is_active"] is not None:
        target.is_active = changes["is_active"]
        if target.is_active:
            target.failed_attempts, target.locked_until = 0, None
    if "phone" in changes:
        target.phone = (changes["phone"] or "").strip() or None
    if changes.get("new_password"):
        target.hashed_password = hash_password(changes["new_password"])
    if changes.get("reset_2fa"):
        target.totp_enabled, target.totp_secret, target.totp_last_step = False, None, None
        revoke_tokens(target)
    shown = {k: ("***" if k == "new_password" else v) for k, v in changes.items()}
    _audit(db, "USER_UPDATE", admin, target.username, str(shown), request)
    db.commit()
    db.refresh(target)
    return target


@router.post("/refresh", response_model=LoginResponse)
def refresh_token(request: Request, response: Response, user: User = Depends(get_current_user)):
    """Sliding session: a still-valid token buys a fresh one, so an open control-room screen never expires.

    A Bearer client gets it in the body, as before. A cookie session gets a new cookie only:
    handing the token to page scripts would let an XSS take it away."""
    token = issue_token(user)
    if request.headers.get("authorization", "").lower().startswith("bearer "):
        return LoginResponse(access_token=token, user_id=user.id, role=user.role)
    set_session_cookie(response, token)
    return LoginResponse(user_id=user.id, role=user.role)


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    return user


# --- Two-factor sign-in ------------------------------------------------------------------------
TWO_FACTOR_ROLES = ROLES_COMMAND        # prompted to turn it on (admins, supervisors)


class CodeBody(BaseModel):
    code: str


class DisableBody(BaseModel):
    password: str
    code: str


@router.get("/2fa")
def two_factor_status(user: User = Depends(get_current_user)):
    return {"enabled": bool(user.totp_enabled), "recommended": user.role in TWO_FACTOR_ROLES}


@router.post("/2fa/setup")
def two_factor_setup(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """A new secret for the authenticator app (shown once as a QR code). Not active until confirmed."""
    if user.totp_enabled:
        raise HTTPException(409, "Two-factor sign-in is already on")
    secret = totp.new_secret()
    user.totp_secret, user.totp_last_step = totp.seal_secret(secret), None
    db.commit()
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, user.username)}


@router.post("/2fa/enable")
def two_factor_enable(body: CodeBody, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    if not user.totp_secret:
        raise HTTPException(400, "Start the setup first")
    step = totp.matching_step(totp.open_secret(user.totp_secret), body.code)
    if step is None:
        raise HTTPException(400, "That code does not match. Check the time on your phone and try the current code.")
    user.totp_enabled, user.totp_last_step = True, step
    _audit(db, "2FA_ENABLED", user, user.username, "", request)
    db.commit()
    return {"enabled": True}


@router.post("/2fa/disable")
def two_factor_disable(body: DisableBody, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    if not user.totp_enabled:
        return {"enabled": False}
    if not verify_password(body.password, user.hashed_password) or \
            totp.matching_step(totp.open_secret(user.totp_secret), body.code) is None:
        raise HTTPException(400, "Password or code is not right")
    user.totp_enabled, user.totp_secret, user.totp_last_step = False, None, None
    _audit(db, "2FA_DISABLED", user, user.username, "", request)
    db.commit()
    return {"enabled": False}


class Assignee(BaseModel):
    id: int
    username: str
    role: str


@router.get("/assignees", response_model=list[Assignee])
def list_assignees(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """Active operational users an incident can be assigned to (no email/phone)."""
    return (db.query(User).filter(User.is_active == True, User.role.in_(sorted(ROLES_OPS)))  # noqa: E712
            .order_by(User.username).all())


@router.get("/users", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    return db.query(User).all()

