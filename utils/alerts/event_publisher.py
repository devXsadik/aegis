"""Push alerts and events from the CV pipeline to the FastAPI backend."""

import os
import logging
import threading
from typing import Optional

logger = logging.getLogger("HumanAnalysis")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "pipeline-internal-key-change-me")
EVENTS_ENABLED = os.getenv("PIPELINE_EVENTS_ENABLED", "true").lower() == "true"
AUTO_ALERTS_ENABLED = os.getenv("AUTO_ALERTS_ENABLED", "true").lower() == "true"


def _headers() -> dict:
    return {"X-Internal-Key": INTERNAL_API_KEY, "Content-Type": "application/json"}


def _post_async(path: str, payload: dict) -> None:
    def _send():
        try:
            import httpx

            resp = httpx.post(
                f"{BACKEND_URL}{path}",
                json=payload,
                headers=_headers(),
                timeout=5.0,
            )
            if resp.status_code >= 400:
                logger.warning(f"Backend {path} returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Backend publish failed ({path}): {e}")

    threading.Thread(target=_send, daemon=True).start()


def dispatch_alert(
    alert_type: str,
    severity: str = "critical",
    camera_location: Optional[str] = None,
    camera_id: Optional[str] = None,
    track_id: Optional[int] = None,
    person_name: Optional[str] = None,
    plate_number: Optional[str] = None,
    message: Optional[str] = None,
    camera_name: Optional[str] = None,
    camera_lat: Optional[float] = None,
    camera_lng: Optional[float] = None,
) -> None:
    """One call → DB + audit + WebSocket + webhooks + dashboard (all cameras)."""
    if not AUTO_ALERTS_ENABLED:
        return
    _post_async(
        "/api/v1/alerts/dispatch",
        {
            "alert_type": alert_type,
            "severity": severity,
            "camera_location": camera_location,
            "camera_id": camera_id,
            "track_id": track_id,
            "person_name": person_name,
            "plate_number": plate_number,
            "message": message,
            "camera_name": camera_name,
            "camera_lat": camera_lat,
            "camera_lng": camera_lng,
        },
    )


def publish_live_event(
    event_type: str,
    severity: str = "info",
    camera_location: Optional[str] = None,
    camera_id: Optional[str] = None,
    track_id: Optional[int] = None,
    person_name: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    if not EVENTS_ENABLED:
        return
    _post_async(
        "/api/v1/events/internal",
        {
            "event_type": event_type,
            "severity": severity,
            "camera_location": camera_location,
            "camera_id": camera_id,
            "track_id": track_id,
            "person_name": person_name,
            "message": message,
        },
    )


def publish_heartbeat(
    camera_id: str,
    camera_location: str = "",
    fps: Optional[float] = None,
    threat_score: Optional[int] = None,
    frame_number: Optional[int] = None,
) -> None:
    if not EVENTS_ENABLED:
        return
    _post_async(
        "/api/v1/system/heartbeat",
        {
            "camera_id": camera_id,
            "camera_location": camera_location,
            "fps": fps,
            "threat_score": threat_score,
            "frame_number": frame_number,
        },
    )
