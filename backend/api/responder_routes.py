"""Responder view: the alerts an officer should go to, and their progress on each.

An officer assigned to cameras (camera_officers) sees those cameras' alerts; one with no
assignment sees every critical/high alert. Each step (on my way, on scene, resolved) is
written to the alert's incident timeline (the incident is opened if needed) and announced on
the alerts WebSocket, so the control room follows along. Resolving closes the loop: the
incident is resolved and the alert acknowledged.
"""

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.auth.auth import operator_or_admin
from backend.db.database import get_db
from backend.models.alert import Alert
from backend.models.camera import Camera
from backend.models.camera_officer import CameraOfficer
from backend.models.capture import AlertCapture
from backend.models.incident import Incident, IncidentEvent
from backend.models.user import User
from backend.services.audit import log_audit
from backend.services.incident_service import add_event, create_incident_from_alert
from backend.utils.websocket import manager
from clock import utcnow
from utils.config.camera_registry import maps_url

router = APIRouter(prefix="/responder", tags=["responder"])

STEPS = {"en_route": "On my way", "on_scene": "On scene", "resolved": "Resolved"}
EVENT = {k: f"RESPONDER_{k.upper()}" for k in STEPS}
ACTION_ROLES = {"police", "operator", "supervisor", "admin"}


class StatusBody(BaseModel):
    status: str = Field(pattern="^(en_route|on_scene|resolved)$")
    note: Optional[str] = Field(default=None, max_length=300)


def _progress(db: Session, alert_id: int):
    inc = db.query(Incident).filter(Incident.alert_id == alert_id).first()
    if not inc:
        return None, []
    events = (db.query(IncidentEvent)
              .filter(IncidentEvent.incident_id == inc.id, IncidentEvent.event_type.in_(EVENT.values()))
              .order_by(IncidentEvent.created_at, IncidentEvent.id).all())
    steps = [{"status": next(k for k, v in EVENT.items() if v == e.event_type), "by": e.actor,
              "at": e.created_at.isoformat() if e.created_at else None, "message": e.message} for e in events]
    return inc, steps


@router.get("/alerts")
def my_alerts(hours: int = 24, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    since = utcnow() - timedelta(hours=min(max(hours, 1), 168))
    mine = [c for (c,) in db.query(CameraOfficer.camera_id).filter(CameraOfficer.user_id == user.id)]
    q = db.query(Alert).filter(Alert.timestamp >= since, Alert.dismissed == False,  # noqa: E712
                               Alert.severity.in_(["critical", "high"]))
    if mine:
        q = q.filter(Alert.camera_id.in_(mine))
    alerts = q.order_by(desc(Alert.timestamp)).limit(50).all()
    cams = {c.camera_id: c for c in db.query(Camera).filter(Camera.camera_id.in_({a.camera_id for a in alerts}))}
    out = []
    for a in alerts:
        cam = cams.get(a.camera_id)
        lat, lng = (cam.lat, cam.lng) if cam else (None, None)
        capture = (db.query(AlertCapture.id).filter(AlertCapture.alert_id == a.id)
                   .order_by(desc(AlertCapture.timestamp)).first())
        inc, steps = _progress(db, a.id)
        out.append({
            "id": a.id, "type": a.alert_type, "severity": a.severity,
            "time": a.timestamp.isoformat() if a.timestamp else None,
            "camera_id": a.camera_id, "camera": (cam.name if cam and cam.name else None) or a.camera_location or a.camera_id,
            "location": a.camera_location, "lat": lat, "lng": lng, "maps_url": maps_url(lat, lng),
            "person_name": a.person_name, "message": a.message, "capture_id": capture[0] if capture else None,
            "ticket_id": inc.ticket_id if inc else None, "steps": steps,
            "status": steps[-1]["status"] if steps else None,
        })
    return {"assigned_cameras": mine, "alerts": out}


@router.post("/alerts/{alert_id}/status")
async def set_status(alert_id: int, body: StatusBody, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(operator_or_admin)):
    if user.role not in ACTION_ROLES:
        raise HTTPException(403, "Your role cannot report on a response")
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(404, "Alert not found")
    inc = create_incident_from_alert(db, alert, created_by=user.id, created_by_name=user.username)
    text = f"{user.username}: {STEPS[body.status].lower()}" + (f" — {body.note}" if body.note else "")
    add_event(db, inc, EVENT[body.status], text, actor=user.username)
    if body.status == "resolved":
        inc.status, inc.resolved_at = "resolved", utcnow()
        alert.acknowledged, alert.acknowledged_by, alert.acknowledged_at = True, user.id, utcnow()
        if alert.review_status == "pending":
            alert.review_status, alert.reviewed_by, alert.reviewed_at = "confirmed", user.id, utcnow()
    elif inc.status == "open":
        inc.status = "investigating"
    log_audit(db, user, EVENT[body.status], "alert", str(alert_id), body.note or "", request)
    db.commit()
    # The control room sees it at once (notifications; info severity, so no alarm).
    await manager.broadcast({
        "event_type": "RESPONDER_UPDATE", "alert_type": "RESPONDER_UPDATE", "severity": "info",
        "alert_id": alert_id, "status": body.status, "officer": user.username,
        "camera_id": alert.camera_id, "camera_location": alert.camera_location,
        "message": f"{text} ({inc.ticket_id})", "timestamp": utcnow().isoformat(),
    }, "alerts")
    _, steps = _progress(db, alert_id)
    return {"alert_id": alert_id, "ticket_id": inc.ticket_id, "status": body.status, "steps": steps}
