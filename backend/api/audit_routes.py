from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc
from backend.db.database import get_db
from backend.models.audit_log import AuditLog
from backend.auth.auth import auditor_or_admin
from backend.services.audit import verify_chain
from backend.models.user import User
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    username: Optional[str]
    action: str
    resource: Optional[str]
    resource_id: Optional[str]
    details: Optional[str]
    ip_address: Optional[str]
    record_hash: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/", response_model=list[AuditLogResponse])
def list_audit_logs(
    skip: int = 0,
    limit: int = 100,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(auditor_or_admin)
):
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    return query.order_by(desc(AuditLog.timestamp)).offset(skip).limit(limit).all()


@router.get("/verify")
def verify_audit_chain(db: Session = Depends(get_db), user: User = Depends(auditor_or_admin)):
    """Re-compute the hash chain: any edited or removed row breaks it."""
    return verify_chain(db)
