from sqlalchemy.orm import Session
from backend.models.audit_log import AuditLog
from backend.auth.auth import hmac_sha256
from datetime import datetime
from typing import Optional


class AuditLogger:
    def __init__(self, db: Session):
        self.db = db

    def _get_last_hash(self) -> str:
        last = (
            self.db.query(AuditLog)
            .order_by(AuditLog.id.desc())
            .first()
        )
        return last.hash if last else ""

    def _compute_hash(self, prev_hash: str, timestamp, user_id, username,
                      action, resource, resource_id, details, ip_address, user_agent) -> str:
        raw = "|".join(str(v) for v in [
            prev_hash, timestamp, user_id, username, action,
            resource, resource_id, details, ip_address, user_agent
        ])
        return hmac_sha256(raw)

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
        ts = datetime.utcnow()
        prev_hash = self._get_last_hash()
        log_hash = self._compute_hash(
            prev_hash, ts, user_id, username, action,
            resource, resource_id, details, ip_address, user_agent
        )
        log = AuditLog(
            timestamp=ts,
            user_id=user_id,
            username=username,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            previous_hash=prev_hash or None,
            hash=log_hash,
        )
        self.db.add(log)
        self.db.commit()

    def verify_chain(self) -> list:
        entries = self.db.query(AuditLog).order_by(AuditLog.id).all()
        broken = []
        prev_hash = ""
        for entry in entries:
            expected = self._compute_hash(
                prev_hash, entry.timestamp, entry.user_id, entry.username,
                entry.action, entry.resource, entry.resource_id,
                entry.details, entry.ip_address, entry.user_agent
            )
            if entry.hash != expected:
                broken.append({
                    "id": entry.id,
                    "expected": expected,
                    "actual": entry.hash,
                })
            prev_hash = entry.hash or ""
        return broken
