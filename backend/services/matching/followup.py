"""After a matcher raised an identification alert: attach it to the target's running incident
(if it is already being followed) and record the sighting for cross-camera tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.incident import Incident
from backend.services import tracking
from backend.services.matching.common import dispatch_sync


def dispatch_and_track(db: Session, *, kind: str, target_ref: str, target: dict, ts: str, direction: Optional[str],
                       method: str, detection_id: Optional[int], alert: dict) -> dict:
    """`alert` = the dispatch_alert keyword arguments (camera_id, severity, message, ...)."""
    track = tracking.active_track(db, kind, target_ref)
    res = dispatch_sync(db=db, attach_incident_id=track.incident_id if track and track.incident_id else None, **alert)
    alert_id = res.get("alert_id")
    incident_id = res.get("incident_id")
    if incident_id is None and alert_id:
        inc = db.query(Incident).filter(Incident.alert_id == alert_id).first()
        incident_id = inc.id if inc else None
    if res.get("status") in ("dispatched", "deduplicated"):
        tracking.on_sighting(db, kind=kind, target_ref=target_ref, target=target, camera_id=alert["camera_id"],
                             ts=datetime.fromisoformat(ts), direction=direction, method=method,
                             confidence=alert.get("confidence"),
                             detection_id=detection_id, alert_id=alert_id if res.get("status") == "dispatched" else None,
                             incident_id=incident_id)
    return res
