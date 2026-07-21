"""Central alert dispatcher — one detection triggers all notification channels."""

import json
import os
import logging
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from backend.db.database import SessionLocal
from backend.models.alert import Alert
from backend.models.audit_log import AuditLog
from backend.models.camera import Camera
from backend.utils.events import broadcast_live_event
from backend.utils.websocket import manager

logger = logging.getLogger(__name__)


def _webhook_urls() -> dict:
    return {
        "law_enforcement": os.getenv("LAW_ENFORCEMENT_WEBHOOK", ""),
        "emergency": os.getenv("EMERGENCY_WEBHOOK", ""),
        "security": os.getenv("SECURITY_TEAM_WEBHOOK", ""),
    }


def _resolve_camera_geo(
    db: Session,
    camera_id: Optional[str],
    camera_lat: Optional[float],
    camera_lng: Optional[float],
    camera_name: Optional[str],
) -> tuple:
    """Fill missing GPS from cameras database table."""
    if camera_lat is not None and camera_lng is not None:
        return camera_lat, camera_lng, camera_name

    if not camera_id:
        return camera_lat, camera_lng, camera_name

    cam = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if cam:
        return cam.lat or camera_lat, cam.lng or camera_lng, cam.name or camera_name
    return camera_lat, camera_lng, camera_name


def _geo_details(lat, lng, camera_name, camera_id) -> Optional[str]:
    if lat is None or lng is None:
        return None
    return json.dumps({
        "lat": lat,
        "lng": lng,
        "camera_name": camera_name,
        "camera_id": camera_id,
        "maps_url": f"https://www.google.com/maps?q={lat},{lng}",
    })


def _send_webhooks(alert_type: str, payload: dict) -> str:
    if os.getenv("ALERTS_ENABLED", "false").lower() != "true":
        return ""
    urls = _webhook_urls()
    sent = []
    if alert_type == "CRIMINAL_DETECTED":
        for key in ("law_enforcement", "security"):
            if urls[key]:
                _post_webhook(urls[key], payload)
                sent.append(key)
    elif alert_type == "WEAPON_DETECTED":
        for key in ("emergency", "security"):
            if urls[key]:
                _post_webhook(urls[key], payload)
                sent.append(key)
    elif alert_type == "SUSPICIOUS_VEHICLE":
        if urls["law_enforcement"]:
            _post_webhook(urls["law_enforcement"], payload)
            sent.append("law_enforcement")
    return ",".join(sent)


def _post_webhook(url: str, payload: dict) -> None:
    try:
        httpx.post(url, json=payload, timeout=5.0)
    except Exception as e:
        logger.warning(f"Webhook failed ({url}): {e}")


async def dispatch_alert(
    alert_type: str,
    severity: str = "info",
    camera_location: Optional[str] = None,
    camera_id: Optional[str] = None,
    track_id: Optional[int] = None,
    person_name: Optional[str] = None,
    plate_number: Optional[str] = None,
    message: Optional[str] = None,
    camera_name: Optional[str] = None,
    camera_lat: Optional[float] = None,
    camera_lng: Optional[float] = None,
    db: Optional[Session] = None,
) -> dict:
    """Fully automated alert dispatch with pinpoint camera GPS."""
    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        camera_lat, camera_lng, camera_name = _resolve_camera_geo(
            db, camera_id, camera_lat, camera_lng, camera_name,
        )

        if not message:
            if alert_type == "CRIMINAL_DETECTED":
                message = f"CRIMINAL DETECTED: {person_name} at {camera_location}"
            else:
                message = alert_type.replace("_", " ").title()

        if camera_lat is not None and camera_lng is not None:
            message += f" | GPS: {camera_lat:.5f}, {camera_lng:.5f}"

        webhook_payload = {
            "alert_type": alert_type,
            "severity": severity,
            "criminal_name": person_name,
            "person_name": person_name,
            "camera_location": camera_location,
            "camera_id": camera_id,
            "camera_name": camera_name,
            "camera_lat": camera_lat,
            "camera_lng": camera_lng,
            "maps_url": f"https://www.google.com/maps?q={camera_lat},{camera_lng}" if camera_lat else None,
            "track_id": track_id,
            "plate_number": plate_number,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        channels = _send_webhooks(alert_type, webhook_payload)

        alert = Alert(
            alert_type=alert_type,
            severity=severity,
            camera_location=camera_location,
            camera_id=camera_id,
            track_id=track_id,
            person_name=person_name,
            plate_number=plate_number,
            message=message,
            details=_geo_details(camera_lat, camera_lng, camera_name, camera_id),
            channels_sent=channels or "websocket,dashboard,map",
        )
        db.add(alert)
        db.flush()

        geo_note = ""
        if camera_lat is not None and camera_lng is not None:
            geo_note = f" @ GPS({camera_lat:.5f},{camera_lng:.5f})"

        audit = AuditLog(
            user_id=None,
            username="SYSTEM",
            action="AUTO_ALERT",
            resource="alert",
            resource_id=str(alert.id),
            details=f"{alert_type}: {message} [camera={camera_id}]{geo_note}",
        )
        db.add(audit)
        db.commit()
        db.refresh(alert)

        # Auto-open a server-side incident ticket for critical/high threats
        if severity in ("critical", "high"):
            try:
                from backend.services.incident_service import create_incident_from_alert
                create_incident_from_alert(db, alert, created_by_name="SYSTEM")
                db.commit()
            except Exception as ie:
                logger.warning(f"Auto-incident create failed: {ie}")
                db.rollback()

        payload = await broadcast_live_event(
            event_type=alert_type,
            severity=severity,
            camera_location=camera_location,
            camera_id=camera_id,
            track_id=track_id,
            person_name=person_name,
            message=message,
            camera_name=camera_name,
            camera_lat=camera_lat,
            camera_lng=camera_lng,
        )
        payload["alert_id"] = alert.id
        payload["auto_dispatched"] = True

        await manager.broadcast(payload, "status")

        logger.info(
            f"AUTO ALERT: {alert_type} @ {camera_location} ({camera_id}) "
            f"GPS=({camera_lat},{camera_lng})"
        )
        return {"status": "dispatched", "alert_id": alert.id, "payload": payload}

    except Exception as e:
        logger.error(f"Alert dispatch failed: {e}")
        if own_session:
            db.rollback()
        raise
    finally:
        if own_session:
            db.close()

