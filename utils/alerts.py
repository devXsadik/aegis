import httpx
import json
import os
from typing import Dict, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from backend.db.database import SessionLocal
from backend.models.alert import Alert
from backend.models.evidence import Evidence
from backend.utils.audit import AuditLogger


class SMSProvider:
    def __init__(self, provider: str = "mock"):
        self.provider = provider
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.getenv("TWILIO_FROM_NUMBER", "")

    def send(self, to: str, message: str) -> bool:
        if self.provider == "mock" or not self.account_sid:
            print(f"[SMS mock] To: {to} | Msg: {message}")
            return True
        if self.provider == "twilio":
            try:
                from twilio.rest import Client
                client = Client(self.account_sid, self.auth_token)
                client.messages.create(body=message, from_=self.from_number, to=to)
                return True
            except Exception as e:
                print(f"[SMS twilio error] {e}")
                return False
        print(f"[SMS] unknown provider '{self.provider}'")
        return False


class PushProvider:
    def __init__(self):
        self.webhook_url = os.getenv("PUSH_WEBHOOK_URL", "")

    def send(self, title: str, body: str, data: dict = None) -> bool:
        if not self.webhook_url:
            print(f"[Push mock] Title: {title} | Body: {body}")
            return True
        try:
            httpx.post(self.webhook_url, json={
                "title": title, "body": body, "data": data or {}
            }, timeout=5.0)
            return True
        except Exception as e:
            print(f"[Push error] {e}")
            return False


class AlertOrchestrator:
    def __init__(self):
        self.webhook_urls = {
            'law_enforcement': os.getenv('LAW_ENFORCEMENT_WEBHOOK'),
            'emergency': os.getenv('EMERGENCY_WEBHOOK'),
            'security_team': os.getenv('SECURITY_TEAM_WEBHOOK')
        }
        self.enabled = os.getenv('ALERTS_ENABLED', 'false').lower() == 'true'
        self.sms = SMSProvider(provider=os.getenv("SMS_PROVIDER", "mock"))
        self.push = PushProvider()
        self.sms_recipients = json.loads(os.getenv("SMS_RECIPIENTS", "[]"))

    # ── Public alert methods ──

    def send_criminal_alert(
        self, criminal_name: str, camera_location: str, track_id: int,
        evidence_id: Optional[int] = None, plate_number: Optional[str] = None
    ) -> bool:
        message = self._format_message('CRIMINAL_DETECTED', {
            "criminal_name": criminal_name, "camera_location": camera_location,
            "track_id": track_id, "evidence_id": evidence_id, "license_plate": plate_number
        })
        alert_id = self._store_alert("CRIMINAL_DETECTED", "high", camera_location,
                                       track_id, criminal_name, plate_number, evidence_id, message)
        self._dispatch("CRIMINAL_DETECTED", message, alert_id, criminal_name, camera_location)
        return alert_id is not None

    def send_weapon_alert(
        self, camera_location: str, track_id: int, evidence_id: Optional[int] = None
    ) -> bool:
        message = self._format_message('WEAPON_DETECTED', {
            "camera_location": camera_location, "track_id": track_id, "evidence_id": evidence_id
        })
        alert_id = self._store_alert("WEAPON_DETECTED", "high", camera_location,
                                       track_id, None, None, evidence_id, message)
        self._dispatch("WEAPON_DETECTED", message, alert_id, None, camera_location)
        return alert_id is not None

    def send_suspicious_vehicle_alert(
        self, plate_number: str, vehicle_type: str,
        camera_location: str, reason: str
    ) -> bool:
        message = self._format_message('SUSPICIOUS_VEHICLE', {
            "license_plate": plate_number, "vehicle_type": vehicle_type,
            "camera_location": camera_location, "reason": reason
        })
        alert_id = self._store_alert("SUSPICIOUS_VEHICLE", "medium", camera_location,
                                       None, None, plate_number, None, message)
        self._dispatch("SUSPICIOUS_VEHICLE", message, alert_id, None, camera_location)
        return alert_id is not None

    def send_suspicious_behavior_alert(
        self, camera_location: str, track_id: int, reasons: list
    ) -> bool:
        message = self._format_message('SUSPICIOUS_BEHAVIOR', {
            "camera_location": camera_location, "track_id": track_id,
            "reasons": ", ".join(reasons)
        })
        alert_id = self._store_alert("SUSPICIOUS_BEHAVIOR", "medium", camera_location,
                                       track_id, None, None, None, message)
        self._dispatch("SUSPICIOUS_BEHAVIOR", message, alert_id, None, camera_location)
        return alert_id is not None

    # ── Internal dispatch ──

    def _dispatch(self, alert_type: str, message: dict, alert_id: int,
                  person_name: Optional[str], camera_location: str):
        channels = []
        if self.enabled:
            service_map = {
                "CRIMINAL_DETECTED": "law_enforcement",
                "WEAPON_DETECTED": "security_team",
                "SUSPICIOUS_VEHICLE": "law_enforcement",
                "SUSPICIOUS_BEHAVIOR": "security_team",
            }
            webhook_target = service_map.get(alert_type, "security_team")
            if self._send_webhook(webhook_target, message):
                channels.append("webhook")

        sms_text = f"[{alert_type}] {camera_location}"
        if person_name:
            sms_text += f" - {person_name}"
        for recipient in self.sms_recipients:
            if self.sms.send(recipient, sms_text):
                channels.append("sms")

        push_title = f"Alert: {alert_type}"
        self.push.send(push_title, sms_text, {"alert_id": alert_id, "type": alert_type})

        if channels:
            db = SessionLocal()
            try:
                db.query(Alert).filter(Alert.id == alert_id).update(
                    {"channels_sent": ",".join(channels)}
                )
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

    def _send_webhook(self, service: str, message: dict) -> bool:
        webhook_url = self.webhook_urls.get(service)
        if not webhook_url:
            print(f"No webhook configured for {service}")
            return False
        try:
            resp = httpx.post(webhook_url, json=message, timeout=5.0)
            if resp.status_code == 200:
                self._audit_log("alert_sent", service, f"Alert sent to {service}")
                return True
        except Exception as e:
            print(f"Webhook error {service}: {e}")
        return False

    # ── DB persistence ──

    def _store_alert(self, alert_type: str, severity: str, camera_location: str,
                     track_id: Optional[int], person_name: Optional[str],
                     plate_number: Optional[str], evidence_id: Optional[int],
                     message: dict) -> Optional[int]:
        db = SessionLocal()
        try:
            alert = Alert(
                alert_type=alert_type, severity=severity,
                camera_location=camera_location, track_id=track_id,
                person_name=person_name, plate_number=plate_number,
                evidence_id=evidence_id, message=json.dumps(message),
                details=message.get("instructions", ""),
                channels_sent="",
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            return alert.id
        except Exception as e:
            print(f"Failed to store alert: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    # ── Formatting ──

    def _format_message(self, alert_type: str, data: dict) -> dict:
        return {
            "alert_type": alert_type,
            "timestamp": datetime.utcnow().isoformat(),
            "priority": "HIGH" if "CRIMINAL" in alert_type or "WEAPON" in alert_type else "MEDIUM",
            "data": data,
            "instructions": self._instructions(alert_type),
        }

    def _instructions(self, alert_type: str) -> str:
        return {
            "CRIMINAL_DETECTED": "Dispatch officer to location immediately",
            "WEAPON_DETECTED": "Armed response team required",
            "SUSPICIOUS_VEHICLE": "Monitor and report suspicious activity",
            "SUSPICIOUS_BEHAVIOR": "Investigate and maintain surveillance",
        }.get(alert_type, "Investigate further")

    def _audit_log(self, action: str, resource: str, details: str):
        try:
            db = SessionLocal()
            audit = AuditLogger(db)
            audit.log(action=action, resource=resource, resource_id=resource, details=details)
            db.close()
        except Exception:
            pass
