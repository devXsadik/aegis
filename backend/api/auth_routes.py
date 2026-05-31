import pyotp
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.models.user import User
from backend.auth.auth import create_access_token, verify_token, pwd_context
from pydantic import BaseModel, field_validator
from datetime import datetime, timedelta

router = APIRouter(prefix="/auth", tags=["authentication"])

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "viewer"

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain an uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain a lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain a digit")
        return v


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True


class TotpSetupResponse(BaseModel):
    secret: str
    uri: str


class TotpVerifyRequest(BaseModel):
    code: str


@router.post("/2fa/setup")
def setup_2fa(
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db),
):
    secret = pyotp.random_base32()
    current_user.totp_secret = secret
    current_user.totp_enabled = False
    db.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email,
        issuer_name="AI Surveillance System"
    )
    return TotpSetupResponse(secret=secret, uri=uri)


@router.post("/2fa/verify")
def verify_2fa(
    req: TotpVerifyRequest,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db),
):
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA not set up")
    totp = pyotp.TOTP(current_user.totp_secret)
    if not totp.verify(req.code):
        raise HTTPException(status_code=401, detail="Invalid 2FA code")
    current_user.totp_enabled = True
    db.commit()
    return {"status": "2FA enabled", "message": "Two-factor authentication is now active"}


@router.post("/2fa/disable")
def disable_2fa(
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db),
):
    current_user.totp_secret = None
    current_user.totp_enabled = False
    db.commit()
    return {"status": "2FA disabled"}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain an uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain a lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain a digit")
        return v


@router.post("/login", response_model=LoginResponse)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == credentials.username).first()
    now = datetime.utcnow()

    if user and user.locked_until and user.locked_until > now:
        remaining = int((user.locked_until - now).total_seconds() // 60)
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account locked. Try again in {remaining} minute(s)."
        )

    if not user or not pwd_context.verify(credentials.password, user.hashed_password):
        if user:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login = now
    db.commit()

    token = create_access_token({"sub": user.username, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username
    }


@router.post("/users", response_model=UserResponse)
def create_user(user_data: UserCreate, admin: User = Depends(verify_token)):
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can create users")

    db = next(get_db())
    existing = db.query(User).filter(
        (User.username == user_data.username) | (User.email == user_data.email)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username or email already exists")

    hashed = pwd_context.hash(user_data.password)
    user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed,
        role=user_data.role
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    if not pwd_context.verify(req.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    current_user.hashed_password = pwd_context.hash(req.new_password)
    db.commit()
    return {"message": "Password changed successfully"}


@router.post("/refresh")
def refresh_token(current_user: User = Depends(verify_token)):
    token = create_access_token({"sub": current_user.username, "role": current_user.role})
    return {"access_token": token, "token_type": "bearer"}
