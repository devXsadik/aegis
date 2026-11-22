"""Background jobs of the API process.

maintenance_loop (daily, MAINTENANCE_HOUR local time, default 03:00):
    recordings older than DVR_RETENTION_HOURS, capture stills older than CAPTURE_RETENTION_DAYS,
    evidence images older than retention.evidence_days (config.yaml), then a backup.
health_watch_loop (every 30 s):
    a camera that is switched on but has not reported for DETECTION_DOWN_SECONDS raises
    CAMERA_OFFLINE; when no switched-on camera reports at all, DETECTION_DOWN. Once per outage,
    with a *_RESTORED notice when it comes back. Paused or stopped cameras never count.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import yaml

from clock import utcnow

logger = logging.getLogger("HumanAnalysis")


# --------------------------------------------------------------------------- maintenance
def purge_recordings() -> dict:
    from backend.db.database import SessionLocal
    from backend.models.recording import RecordingClip
    from paths import RECORDINGS_DIR
    from utils.media.dvr import purge_old_recordings

    hours = float(os.getenv("DVR_RETENTION_HOURS", "48"))
    files = purge_old_recordings(RECORDINGS_DIR, hours)
    db = SessionLocal()
    try:
        rows = db.query(RecordingClip).filter(RecordingClip.started_at < utcnow() - timedelta(hours=hours)).delete()
        db.commit()
    finally:
        db.close()
    return {"files": files, "rows": rows, "retention_hours": hours}


def purge_captures() -> dict:
    from backend.db.database import SessionLocal
    from backend.models.capture import AlertCapture

    days = int(os.getenv("CAPTURE_RETENTION_DAYS", "7"))
    if days <= 0:
        return {"rows": 0, "retention_days": days}
    db = SessionLocal()
    try:
        rows = db.query(AlertCapture).filter(AlertCapture.timestamp < utcnow() - timedelta(days=days)) \
            .delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    return {"rows": rows, "retention_days": days}


def run_maintenance(backup: bool = True) -> dict:
    """Each step runs even if an earlier one failed; the result says what happened."""
    from backend.services.backup import run_backup
    from utils.data.retention import run_retention

    steps = {"recordings": purge_recordings, "captures": purge_captures, "evidence": run_retention}
    if backup and os.getenv("BACKUP_ENABLED", "true").lower() == "true":
        steps["backup"] = run_backup
    out = {}
    for name, fn in steps.items():
        try:
            out[name] = fn()
        except Exception as e:                       # one failing step must not stop the rest
            logger.error(f"Maintenance step {name} failed: {e}")
            out[name] = {"status": "error", "message": str(e)}
    logger.info(f"Maintenance done: {out}")
    return out


def seconds_until(hour: int, now: Optional[datetime] = None) -> float:
    now = now or datetime.now()
    nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


async def maintenance_loop() -> None:
    hour = int(os.getenv("MAINTENANCE_HOUR", "3"))
    while True:
        await asyncio.sleep(seconds_until(hour))
        await asyncio.to_thread(run_maintenance)


# --------------------------------------------------------------------------- health watch
class HealthWatch:
    """Decides, from heartbeats and the cameras that are switched on, what to raise."""

    def __init__(self, down_after: float = 120.0):
        self.down_after = down_after
        self._on_since: dict = {}          # camera -> when we first saw it switched on
        self._offline: set = set()
        self._all_down = False

    def step(self, switched_on: set, last_seen: dict, now: float) -> list:
        """`last_seen`: camera -> epoch seconds of its last heartbeat. Returns [(type, camera|None)]."""
        for cam in list(self._on_since):
            if cam not in switched_on:
                del self._on_since[cam]
                self._offline.discard(cam)      # stopped on purpose: not an outage
        for cam in switched_on:
            self._on_since.setdefault(cam, now)

        silent = {c for c in switched_on
                  if now - max(last_seen.get(c, 0.0), self._on_since[c]) > self.down_after}
        events = []
        all_down = bool(switched_on) and silent == switched_on
        if all_down and not self._all_down:
            events.append(("DETECTION_DOWN", None))
        elif not all_down and self._all_down:
            events.append(("DETECTION_RESTORED", None))
        self._all_down = all_down
        if not all_down:                        # one system-wide alert covers every camera
            events += [("CAMERA_OFFLINE", c) for c in sorted(silent - self._offline)]
            events += [("CAMERA_RESTORED", c) for c in sorted((self._offline - silent) & switched_on)]
            self._offline = silent
        else:
            self._offline = set()               # after the system alert, a camera still silent gets its own
        return events


def _switched_on() -> set:
    from paths import CAMERAS_YAML
    if not CAMERAS_YAML.exists():
        return set()
    data = yaml.safe_load(CAMERAS_YAML.read_text()) or {}
    return {c["id"] for c in data.get("cameras") or []
            if c.get("id") and c.get("enabled", True) and c.get("started", True)}


def _last_seen() -> dict:
    """camera -> epoch seconds of its last heartbeat (stored as naive UTC ISO text)."""
    from backend.api.system_routes import _pipeline_status
    out = {}
    for cam, meta in _pipeline_status.get("cameras", {}).items():
        try:
            out[cam] = datetime.fromisoformat(meta["last_seen"]).replace(tzinfo=timezone.utc).timestamp()
        except (KeyError, TypeError, ValueError):
            pass
    return out


MESSAGES = {
    "DETECTION_DOWN": ("critical", "Detection is down: no camera has reported for {m} min. Check the pipeline computer (./run.sh)."),
    "DETECTION_RESTORED": ("info", "Detection is back: cameras are reporting again."),
    "CAMERA_OFFLINE": ("high", "Camera {c} stopped reporting {m} min ago while switched on (unplugged, network or crash)."),
    "CAMERA_RESTORED": ("info", "Camera {c} is reporting again."),
}


async def health_watch_loop() -> None:
    from backend.services.alert_dispatcher import dispatch_alert

    down_after = float(os.getenv("DETECTION_DOWN_SECONDS", "120"))
    if down_after <= 0:
        return
    watch = HealthWatch(down_after)
    while True:
        await asyncio.sleep(30)
        try:
            for kind, cam in watch.step(_switched_on(), _last_seen(), time.time()):
                severity, text = MESSAGES[kind]
                await dispatch_alert(alert_type=kind, severity=severity, camera_id=cam, camera_location=cam,
                                     message=text.format(c=cam, m=int(down_after // 60)))
        except Exception as e:
            logger.warning(f"Health watch failed: {e}")
