"""Audit trail: one place to write rows, a hash chain that seals every row, and a guard that
refuses UPDATE / DELETE of audit rows through the ORM (Postgres also gets a trigger, 0014).

Every AuditLog added to any session is sealed in `before_flush`, whichever module created it,
so older code that does `db.add(AuditLog(...))` is covered too."""

from __future__ import annotations

import hashlib
import json
from datetime import timezone
from typing import Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.models.audit_log import AuditLog
from backend.models.user import User
from clock import utcnow

_LOCK_KEY = 0x41E615   # pg advisory lock id for the chain head


def log_audit(db: Session, user: Optional[User], action: str, resource: str, resource_id: str = "",
              details: str = "", request=None) -> AuditLog:
    row = AuditLog(
        user_id=user.id if user else None, username=user.username if user else "SYSTEM",
        action=action, resource=resource, resource_id=str(resource_id)[:50], details=details,
        ip_address=request.client.host if request is not None and getattr(request, "client", None) else None,
    )
    db.add(row)
    return row


def _ts(ts) -> Optional[str]:
    """UTC, no tz suffix: SQLite hands back naive datetimes and Postgres aware ones."""
    if ts is None:
        return None
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts.isoformat(timespec="microseconds")


def _payload(row: AuditLog) -> str:
    return json.dumps({
        "ts": _ts(row.timestamp), "user_id": row.user_id, "username": row.username,
        "action": row.action, "resource": row.resource, "resource_id": row.resource_id,
        "details": row.details, "ip": row.ip_address,
    }, sort_keys=True, ensure_ascii=False, default=str)


def seal(row: AuditLog, prev_hash: Optional[str]) -> str:
    row.prev_hash = prev_hash
    row.record_hash = hashlib.sha256(((prev_hash or "") + "|" + _payload(row)).encode()).hexdigest()
    return row.record_hash


def _head(session: Session) -> Optional[str]:
    with session.no_autoflush:
        last = (session.query(AuditLog.record_hash).filter(AuditLog.record_hash.isnot(None))
                .order_by(AuditLog.id.desc()).first())
    return last[0] if last else None


@event.listens_for(Session, "before_flush")
def _audit_before_flush(session: Session, flush_context, instances) -> None:
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, AuditLog) and (obj in session.deleted or session.is_modified(obj)):
            raise PermissionError("Audit log rows are append-only")
    if not any(isinstance(o, AuditLog) for o in session.new):
        return
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    session.info["audit_head"] = _head(session)


@event.listens_for(AuditLog, "before_insert")
def _audit_before_insert(mapper, connection, row: AuditLog) -> None:
    """Seal in the order rows are actually inserted, so the chain follows the id order."""
    from sqlalchemy.orm import object_session
    session = object_session(row)
    if row.timestamp is None:
        row.timestamp = utcnow()
    prev = session.info.get("audit_head") if session is not None else None
    sealed = seal(row, prev)
    if session is not None:
        session.info["audit_head"] = sealed


def verify_chain(db: Session, limit: Optional[int] = None) -> dict:
    """Walk the sealed rows in id order; report the first row whose hash or link is wrong."""
    q = db.query(AuditLog).filter(AuditLog.record_hash.isnot(None)).order_by(AuditLog.id)
    rows = q.limit(limit).all() if limit else q.all()
    unsealed = db.query(AuditLog).filter(AuditLog.record_hash.is_(None)).count()
    prev = None
    for row in rows:
        expected = hashlib.sha256(((row.prev_hash or "") + "|" + _payload(row)).encode()).hexdigest()
        if row.prev_hash != prev or row.record_hash != expected:
            return {"ok": False, "checked": rows.index(row), "broken_at": row.id, "unsealed_legacy_rows": unsealed}
        prev = row.record_hash
    return {"ok": True, "checked": len(rows), "broken_at": None, "unsealed_legacy_rows": unsealed}
