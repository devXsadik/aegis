import os
import json
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.models.alert import Alert
from utils import logger


class AlertOrchestrator:
    def __init__(self):
        self.law_enforcement_webhook = os.getenv("LAW_ENFORCEMENT_WEBHOOK", "")
        self.emergency_webhook = os.getenv("EMERGENCY_WEBHOOK", "")
        self.security_webhook = os.getenv("SECURITY_TEAM_WEBHOOK", "")
        self.enabled = os.getenv("ALERTS_ENABLED", "false").lower() == "true"

    def _save_alert(self, alert_type: str, severity: str, **kwargs):
        db: Session = SessionLocal()
        try:
            alert = Alert(
                alert_type=alert_type,
                severity=severity,
                camera_location=kwargs.get("camera_location"),
                track_id=kwargs.get("track_id"),
                person_name=kwargs.get("person_name"),
                plate_number=kwargs.get("plate_number"),
                message=kwargs.get("message"),
                channels_sent=kwargs.get("channels", ""),
            )
            db.add(alert)
            db.commit()
        except Exception as e:
            logger.error(f"Alert save failed: {e}")
            db.rollback()
        finally:
            db.close()

    def _send_webhook(self, url: str, payload: dict):
        if not url:
            return
        try:
            httpx.post(url, json=payload, timeout=10.0)
        except Exception as e:
            logger.warning(f"Webhook {url} failed: {e}")

    def send_criminal_alert(self, criminal_name: str, camera_location: str, track_id: int):
        payload = {
            "alert_type": "CRIMINAL_DETECTED",
            "severity": "critical",
            "criminal_name": criminal_name,
            "camera_location": camera_location,
            "track_id": track_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._send_webhook(self.law_enforcement_webhook, payload)
        self._send_webhook(self.security_webhook, payload)
        self._save_alert("CRIMINAL_DETECTED", "critical",
                         camera_location=camera_location, track_id=track_id,
                         person_name=criminal_name, channels="law_enforcement,security",
                         message=f"Criminal detected: {criminal_name} at {camera_location}")

    def send_weapon_alert(self, camera_location: str, track_id: int):
        payload = {
            "alert_type": "WEAPON_DETECTED",
            "severity": "critical",
            "camera_location": camera_location,
            "track_id": track_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._send_webhook(self.emergency_webhook, payload)
        self._send_webhook(self.security_webhook, payload)
        self._save_alert("WEAPON_DETECTED", "critical",
                         camera_location=camera_location, track_id=track_id,
                         channels="emergency,security",
                         message=f"Weapon detected at {camera_location}")

    def send_suspicious_vehicle_alert(self, plate_number: str, vehicle_type: str,
                                      camera_location: str, reason: str = ""):
        payload = {
            "alert_type": "SUSPICIOUS_VEHICLE",
            "severity": "high",
            "plate_number": plate_number,
            "vehicle_type": vehicle_type,
            "camera_location": camera_location,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._send_webhook(self.law_enforcement_webhook, payload)
        self._save_alert("SUSPICIOUS_VEHICLE", "high",
                         camera_location=camera_location, plate_number=plate_number,
                         channels="law_enforcement",
                         message=f"Suspicious vehicle {plate_number} ({vehicle_type}) at {camera_location}")
