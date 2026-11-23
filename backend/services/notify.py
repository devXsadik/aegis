"""Notifications to people (officers, operators): stored rows, live over /ws/notifications
(per-user channel), a phone push to wake their device, SMS for critical ones when configured.
Each one can require acknowledgement by a deadline; services/escalation escalates misses."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from backend.models.tracking import Notification
from backend.models.user import User
from backend.services.matching.common import broadcast_sync, run_async
from clock import utcnow

ACK_SECONDS = {"critical": 60, "high": 120, "medium": 300, "low": None, "info": None}


def ack_seconds(priority: str) -> Optional[int]:
    env = os.getenv(f"ACK_SECONDS_{priority.upper()}")
    if env:
        return int(env) or None
    return ACK_SECONDS.get(priority)


def notify(db: Session, user_ids: Iterable[int], *, kind: str, title: str, body: str = "", priority: str = "high",
           incident_id: Optional[int] = None, alert_id: Optional[int] = None, payload: Optional[dict] = None,
           dedup_key: Optional[str] = None, sms: bool = False) -> List[Notification]:
    """One row per user (skipping users who already got the same dedup_key in the last 10 min)."""
    ids = {int(u) for u in user_ids if u}
    if not ids:
        return []
    now = utcnow()
    if dedup_key:
        recent = {uid for (uid,) in db.query(Notification.user_id).filter(
            Notification.dedup_key == dedup_key, Notification.created_at >= now - timedelta(minutes=10),
            Notification.user_id.in_(ids))}
        ids -= recent
    users = db.query(User).filter(User.id.in_(ids), User.is_active == True).all()  # noqa: E712
    secs = ack_seconds(priority)
    rows = []
    for u in users:
        n = Notification(user_id=u.id, kind=kind, priority=priority, title=title[:200], body=body,
                         payload=json.dumps(payload or {}, default=str, ensure_ascii=False), incident_id=incident_id,
                         alert_id=alert_id, dedup_key=dedup_key, channels="in_app,push" + (",sms" if sms and u.phone else ""),
                         ack_deadline=now + timedelta(seconds=secs) if secs else None)
        db.add(n)
        rows.append(n)
    db.flush()
    for n in rows:
        broadcast_sync({"event_type": "NOTIFICATION", **out(n)}, f"user:{n.user_id}")
    _push(users, priority)
    if sms:
        _sms([u for u in users if u.phone], f"AEGIS {title} | {body}"[:300], {"incident_id": incident_id})
    return rows


def out(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "priority": n.priority, "title": n.title, "body": n.body,
            "payload": json.loads(n.payload or "{}"), "incident_id": n.incident_id, "alert_id": n.alert_id,
            "created_at": n.created_at.isoformat() if n.created_at else utcnow().isoformat(),
            "read_at": n.read_at, "ack_state": n.ack_state, "acked_at": n.acked_at,
            "ack_deadline": n.ack_deadline.isoformat() if n.ack_deadline else None}


def _push(users, priority: str) -> None:
    if os.getenv("WEB_PUSH_ENABLED", "true").lower() == "false" or priority not in ("critical", "high"):
        return
    try:
        from backend.services import web_push
        if hasattr(web_push, "notify_users"):
            run_async(web_push.notify_users, [u.id for u in users])
    except Exception:
        pass


def _sms(users, text: str, payload: dict) -> None:
    try:
        from backend.services.officer_dispatch import sms_officers
        run_async(sms_officers, users, text, payload)
    except Exception:
        pass
