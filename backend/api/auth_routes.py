from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from backend.db.database import get_db
from backend.models.user import User
from backend.auth.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, admin_only, VALID_ROLES,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    role: str


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "viewer"
    phone: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    phone: Optional[str] = None

    class Config:
        from_attributes = True


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"user_id": user.id, "role": user.role})
    return LoginResponse(access_token=token, user_id=user.id, role=user.role)


@router.post("/users", response_model=UserResponse)
def create_user(req: UserCreate, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
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
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.get("/users", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    return db.query(User).all()

