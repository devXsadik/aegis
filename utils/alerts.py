"""
Alert Orchestration System
Sends alerts to law enforcement, emergency services
"""
import httpx
import json
from typing import Dict, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.models.evidence import Evidence
from backend.utils.audit import AuditLogger
import os


class AlertOrchestrator:
    """Manages alert distribution to external services"""

    def __init__(self):
        self.webhook_urls = {
            'law_enforcement': os.getenv('LAW_ENFORCEMENT_WEBHOOK'),
            'emergency': os.getenv('EMERGENCY_WEBHOOK'),
            'security_team': os.getenv('SECURITY_TEAM_WEBHOOK')
        }
        self.enabled = os.getenv('ALERTS_ENABLED', 'false').lower() == 'true'

    def send_criminal_alert(
        self,
        criminal_name: str,
        camera_location: str,
        track_id: int,
        evidence_id: Optional[int] = None,
        plate_number: Optional[str] = None
    ) -> bool:
        """Send alert for criminal detection"""
        message = self._format_criminal_message(
            criminal_name, camera_location, track_id, evidence_id, plate_number
        )
        return self._send_alert('law_enforcement', message)

    def send_weapon_alert(
        self,
        camera_location: str,
        track_id: int,
        evidence_id: Optional[int] = None
    ) -> bool:
        """Send alert for weapon detection"""
        message = self._format_weapon_message(
            camera_location, track_id, evidence_id
        )
        return self._send_alert('security_team', message)

    def send_suspicious_vehicle_alert(
        self,
        plate_number: str,
        vehicle_type: str,
        camera_location: str,
        reason: str
    ) -> bool:
        """Send alert for suspicious vehicle"""
        message = self._format_vehicle_message(
            plate_number, vehicle_type, camera_location, reason
        )
        return self._send_alert('law_enforcement', message)

    def _send_alert(self, service: str, message: dict) -> bool:
        """Send alert to webhook endpoint"""
        if not self.enabled:
            print(f"Alerts disabled, would send to {service}: {message}")
            return False

        webhook_url = self.webhook_urls.get(service)
        if not webhook_url:
            print(f"No webhook configured for {service}")
            return False

        try:
            response = httpx.post(
                webhook_url,
                json=message,
                timeout=5.0
            )
            success = response.status_code == 200
            if success:
                print(f"Alert sent to {service}")
                # Log to audit
                db = SessionLocal()
                try:
                    audit = AuditLogger(db)
                    audit.log(
                        action="alert_sent",
                        resource="alert",
                        resource_id=service,
                        details=f"Alert sent to {service}"
                    )
                finally:
                    db.close()
            return success
        except Exception as e:
            print(f"Failed to send alert to {service}: {e}")
            return False

    def _format_criminal_message(
        self, name: str, location: str,
        track_id: int, evidence_id: Optional[int],
        plate_number: Optional[str]
    ) -> dict:
        return {
            "alert_type": "CRIMINAL_DETECTED",
            "timestamp": datetime.utcnow().isoformat(),
            "priority": "HIGH",
            "data": {
                "criminal_name": name,
                "camera_location": location,
                "track_id": track_id,
                "evidence_id": evidence_id,
                "license_plate": plate_number
            },
            "instructions": "Dispatch officer to location immediately"
        }

    def _format_weapon_message(
        self, location: str, track_id: int,
        evidence_id: Optional[int]
    ) -> dict:
        return {
            "alert_type": "WEAPON_DETECTED",
            "timestamp": datetime.utcnow().isoformat(),
            "priority": "HIGH",
            "data": {
                "camera_location": location,
                "track_id": track_id,
                "evidence_id": evidence_id
            },
            "instructions": "Armed response team required"
        }

    def _format_vehicle_message(
        self, plate: str, vtype: str,
        location: str, reason: str
    ) -> dict:
        return {
            "alert_type": "SUSPICIOUS_VEHICLE",
            "timestamp": datetime.utcnow().isoformat(),
            "priority": "MEDIUM",
            "data": {
                "license_plate": plate,
                "vehicle_type": vtype,
                "camera_location": location,
                "reason": reason
            },
            "instructions": "Monitor and report suspicious activity"
        }
