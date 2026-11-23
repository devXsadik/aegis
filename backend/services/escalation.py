"""Escalate critical alerts nobody acknowledged: page the backup officers, once."""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.database import SessionLocal
from backend.models.alert import Alert
from backend.services import officer_dispatch
from backend.services.audit import log_audit
from backend.utils.websocket import manager
from clock import utcnow

logger = logging.getLogger(__name__)


async def escalate_unacknowledged(db: Session, after_seconds: int, now: Optional[datetime] = None) -> int:
    """Returns how many alerts were escalated. Each alert escalates at most once."""
    now = now or utcnow()
    cutoff = now - timedelta(seconds=after_seconds)
    pending = db.query(Alert).filter(
        Alert.alert_type.in_(list(officer_dispatch.OFFICER_ALERT_TYPES)),
        Alert.acknowledged == False, Alert.dismissed == False,  # noqa: E712
        Alert.review_status != "rejected",
        Alert.escalated_at.is_(None), Alert.timestamp <= cutoff).all()
    for alert in pending:
        officers = officer_dispatch.officers_for_camera(db, alert.camera_id)
        backups = officers[1:]
        sent = []
        if backups:
            text = "ESCALATION (no acknowledgement) | " + officer_dispatch.sms_text(
                alert.alert_type, alert.person_name, None, alert.camera_location, None, None, None)
            sent = await officer_dispatch.sms_officers(backups, text, {"alert_id": alert.id, "camera_id": alert.camera_id})
        alert.escalated_at = now
        log_audit(db, None, "ALERT_ESCALATED", "alert", alert.id,
                  f"backups={[u.username for u in backups]} sms_sent={sent}")
        db.commit()
        await manager.broadcast({"event_type": "ALERT_ESCALATED", "alert_type": "ALERT_ESCALATED", "severity": "high",
                                 "alert_id": alert.id, "camera_id": alert.camera_id,
                                 "message": f"Alert #{alert.id} not acknowledged after {after_seconds}s: escalated"}, "alerts")
    return len(pending)


def escalate_after_seconds() -> int:
    """Seconds an unacknowledged watchlist/weapon alert waits before backups are paged (0 = never)."""
    return int(os.getenv("ESCALATE_AFTER_SECONDS", "120"))


async def escalation_loop() -> None:
    after = escalate_after_seconds()
    if after <= 0:
        return
    while True:
        await asyncio.sleep(15)
        db = SessionLocal()
        try:
            await escalate_unacknowledged(db, after)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Escalation sweep failed: {e}")
            db.rollback()
        finally:
            db.close()


def escalate_notifications(db: Session, now: Optional[datetime] = None) -> int:
    """Notifications past their acknowledgement deadline: tell the next available officer of the
    same area (not yet notified) and the supervisors, once. Returns how many were escalated."""
    import json as _json
    from backend.models.tracking import Notification
    from backend.models.user import User
    from backend.services.jurisdiction import eligible_officers
    from backend.services.notify import notify
    now = now or utcnow()
    due = db.query(Notification).filter(Notification.ack_deadline.isnot(None), Notification.ack_deadline <= now,
                                        Notification.acked_at.is_(None), Notification.escalated_at.is_(None),
                                        Notification.kind != "escalation").all()
    n = 0
    for note in due:
        note.escalated_at = now
        payload = _json.loads(note.payload or "{}")
        already = {uid for (uid,) in db.query(Notification.user_id).filter(Notification.dedup_key == note.dedup_key)} \
            if note.dedup_key else {note.user_id}
        nxt = []
        if payload.get("camera_id"):
            res = eligible_officers(db, camera_id=payload["camera_id"])
            nxt = [o["id"] for o in res["officers"] if o["id"] not in already and o["duty_status"] in ("available", "on_duty")][:1]
        sups = [u.id for u in db.query(User).filter(User.role == "supervisor", User.is_active == True)]  # noqa: E712
        late = db.get(User, note.user_id)
        notify(db, set(nxt) | set(sups), kind="escalation", priority=note.priority,
               title=f"Not acknowledged: {note.title}",
               body=f"{late.username if late else 'Officer'} did not acknowledge within the time limit. {note.body or ''}".strip(),
               incident_id=note.incident_id, alert_id=note.alert_id, payload={**payload, "escalated_from": note.id},
               dedup_key=f"esc:{note.id}", sms=note.priority == "critical")
        log_audit(db, None, "NOTIFICATION_ESCALATED", "notification", note.id,
                  f"to={sorted(set(nxt) | set(sups))}")
        n += 1
    db.flush()
    return n
