"""Incident ticket helpers — create from alerts, timeline events."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.incident import Incident, IncidentEvent
from backend.models.alert import Alert


def _next_ticket_id(db: Session) -> str:
    last = db.query(Incident).order_by(Incident.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"INC-{1000 + n}"


# Timeline kinds the dashboard knows how to draw (others still show, with a plain dot).
EVENT_KINDS = ("CREATED", "ALERT", "MATCHED", "VERIFIED", "STATUS", "PRIORITY", "ASSIGNED", "UNASSIGNED",
               "OFFICER_STATE", "NOTE", "HANDOFF", "EVIDENCE", "OVERRIDE", "BOLO", "NOTIFIED")

SOURCE_BY_ALERT = {"CRIMINAL_DETECTED": "face_match", "PERSON_TRACKED": "face_match",
                   "SUSPICIOUS_VEHICLE": "vehicle_match", "VEHICLE_MATCH": "vehicle_match"}


def add_event(
    db: Session,
    incident: Incident,
    event_type: str,
    message: str,
    actor: Optional[str] = None,
    *,
    actor_id: Optional[int] = None,
    camera_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> IncidentEvent:
    ev = IncidentEvent(
        incident_id=incident.id,
        event_type=event_type,
        message=message,
        actor=actor or "SYSTEM",
        actor_id=actor_id,
        camera_id=camera_id,
        payload=json.dumps(payload, default=str) if payload else None,
    )
    db.add(ev)
    return ev


def create_incident_from_alert(
    db: Session,
    alert: Alert,
    *,
    created_by: Optional[int] = None,
    created_by_name: str = "SYSTEM",
) -> Incident:
    """Idempotent: one open incident per alert_id."""
    existing = db.query(Incident).filter(Incident.alert_id == alert.id).first()
    if existing:
        return existing

    lat = lng = None
    if alert.details:
        try:
            import json
            geo = json.loads(alert.details)
            lat, lng = geo.get("lat"), geo.get("lng")
        except (ValueError, TypeError, AttributeError):         # details not a JSON object
            pass
    lat = lat if isinstance(lat, (int, float)) else None
    lng = lng if isinstance(lng, (int, float)) else None

    priority = alert.severity if alert.severity in ("critical", "high", "medium", "low", "info") else "high"
    if priority == "info":
        priority = "low"

    inc = Incident(
        ticket_id=_next_ticket_id(db),
        title=alert.message or alert.alert_type.replace("_", " "),
        description=alert.message,
        incident_type=alert.alert_type,
        priority=priority if priority != "info" else "medium",
        status="new",
        source=SOURCE_BY_ALERT.get(alert.alert_type, "alert"),
        camera_id=alert.camera_id,
        camera_location=alert.camera_location,
        lat=lat,
        lng=lng,
        alert_id=alert.id,
        evidence_id=alert.evidence_id,
        person_name=alert.person_name,
        plate_number=alert.plate_number,
        created_by=created_by,
        created_by_name=created_by_name,
    )
    db.add(inc)
    db.flush()
    try:
        from backend.services.jurisdiction import incident_jurisdiction
        inc.jurisdiction_id = incident_jurisdiction(db, inc)
    except Exception:                       # area lookup must never block opening a case
        inc.jurisdiction_id = None
    add_event(db, inc, "CREATED", f"Incident opened from alert #{alert.id}", created_by_name,
              actor_id=created_by, camera_id=alert.camera_id)
    kind = "MATCHED" if inc.source in ("face_match", "vehicle_match") else "ALERT"
    add_event(db, inc, kind, f"{alert.alert_type}: {alert.message}", "SYSTEM", camera_id=alert.camera_id,
              payload={"alert_id": alert.id, "alert_type": alert.alert_type, "severity": alert.severity})
    return inc
