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


_STREAM_ENABLED = os.getenv("PIPELINE_STREAM_ENABLED", "true").lower() == "true"
_stream_busy = threading.Event()


def publish_frame(camera_id: str, jpeg_bytes: bytes) -> None:
    """Push the latest annotated JPEG frame to the backend live-stream buffer.

    Drops frames if a previous upload is still in flight so the CV loop
    never blocks on network I/O.
    """
    if not _STREAM_ENABLED or _stream_busy.is_set():
        return

    def _send():
        _stream_busy.set()
        try:
            import httpx

            httpx.post(
                f"{BACKEND_URL}/api/v1/stream/frame/{camera_id}",
                content=jpeg_bytes,
                headers={
                    "X-Internal-Key": INTERNAL_API_KEY,
                    "Content-Type": "image/jpeg",
                },
                timeout=3.0,
            )
        except Exception:
            pass  # streaming is best-effort; alerts have their own channel
        finally:
            _stream_busy.clear()

    threading.Thread(target=_send, daemon=True).start()


_last_clip: dict = {}
_CLIP_COOLDOWN = float(os.getenv("CLIP_COOLDOWN_SECONDS", "15"))


def publish_event_clip(
    camera_id: str,
    jpeg_bytes: bytes,
    *,
    camera_location: str = "",
    alert_type: str = "EVENT",
) -> None:
    """Upload an event-triggered still to the recordings timeline (VMS slice)."""
    now = __import__("time").time()
    if now - _last_clip.get(camera_id, 0) < _CLIP_COOLDOWN:
        return
    _last_clip[camera_id] = now

    def _send():
        try:
            import httpx
            from datetime import datetime

            files = {"file": ("event.jpg", jpeg_bytes, "image/jpeg")}
            data = {
                "camera_id": camera_id,
                "camera_location": camera_location or "",
                "trigger": "event",
                "alert_type": alert_type,
                "started_at": datetime.utcnow().isoformat(),
                "frame_count": "1",
            }
            httpx.post(
                f"{BACKEND_URL}/api/v1/recordings/ingest",
                data=data,
                files=files,
                headers={"X-Internal-Key": INTERNAL_API_KEY},
                timeout=8.0,
            )
        except Exception as e:
            logger.warning(f"Clip ingest failed: {e}")

    threading.Thread(target=_send, daemon=True).start()


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

