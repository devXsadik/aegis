from sqlalchemy.orm import Session
from backend.models.audit_log import AuditLog
from datetime import datetime
from typing import Optional


class AuditLogger:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        action: str,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        log = AuditLog(
            timestamp=datetime.utcnow(),
            user_id=user_id,
            username=username,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        self.db.add(log)
        self.db.commit()
