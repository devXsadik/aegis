"""
Output Stage
============
Handles evidence saving, alert dispatching, and WebSocket notifications.
"""

import logging
import threading
import time

from core.pipeline.base import PipelineStage, FrameContext
from utils.evidence_db import save_evidence_db

logger = logging.getLogger("HumanAnalysis")


class OutputStage(PipelineStage):
    """Saves evidence and dispatches alerts for detected threats."""

    def __init__(self, alert_orchestrator, camera_location: str = "",
                 evidence_throttle_seconds: float = 10.0,
                 alarm_interval_seconds: float = 5.0,
                 alarm_callback=None, enabled: bool = True):
        super().__init__(name="output", enabled=enabled)
        self.alert_orchestrator = alert_orchestrator
        self.camera_location = camera_location
        self.evidence_throttle = evidence_throttle_seconds
        self.alarm_interval = alarm_interval_seconds
        self.alarm_callback = alarm_callback

        # Throttling state
        self._last_saved: dict = {}       # track_id → timestamp
        self._last_alarm_time: float = 0

    def process(self, ctx: FrameContext) -> FrameContext:
        now = ctx.timestamp
        location = ctx.camera_location or self.camera_location
        fh, fw = ctx.frame.shape[:2]

        for track in ctx.tracks:
            if not track.is_confirmed():
                continue

            track_id = track.track_id
            x1, y1, x2, y2 = map(int, track.to_ltrb())
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(fw, x2), min(fh, y2)

            roi = ctx.frame[y1:y2, x1:x2]
            if roi.size == 0:
                continue

            name = ctx.identities.get(track_id, "Unknown")
            is_criminal = track_id in ctx.criminal_ids
            is_suspicious = track_id in ctx.suspicious_tracks
            reasons = ctx.suspicious_tracks.get(track_id, [])
            alert = is_criminal or ctx.weapon_present or is_suspicious

            # --- Alarm ---
            if is_criminal and now - self._last_alarm_time > self.alarm_interval:
                if self.alarm_callback:
                    self.alarm_callback()
                self._last_alarm_time = now

                # Criminal alert
                try:
                    self.alert_orchestrator.send_criminal_alert(
                        criminal_name=name,
                        camera_location=location,
                        track_id=track_id,
                    )
                except Exception as e:
                    logger.warning(f"Criminal alert failed: {e}")

            # --- Weapon alert ---
            if ctx.weapon_present and now - self._last_alarm_time > self.alarm_interval:
                try:
                    self.alert_orchestrator.send_weapon_alert(
                        camera_location=location,
                        track_id=track_id,
                    )
                except Exception as e:
                    logger.warning(f"Weapon alert failed: {e}")

            # --- Evidence saving (throttled) ---
            if alert and (now - self._last_saved.get(track_id, 0) >= self.evidence_throttle):
                try:
                    evidence_thread = threading.Thread(
                        target=save_evidence_db,
                        args=(
                            location, track_id, name,
                            is_criminal, ctx.weapon_present, is_suspicious,
                            reasons, ctx.frame.copy(), roi.copy(),
                        ),
                        daemon=True,
                    )
                    evidence_thread.start()
                    self._last_saved[track_id] = now
                except Exception as e:
                    logger.warning(f"Evidence save failed: {e}")

        # --- Watchlisted plate alerts ---
        for plate in ctx.watchlisted_plates:
            try:
                # Find associated vehicle type
                vehicle_type = "unknown"
                for v in ctx.vehicle_detections:
                    if v.get("bbox") == plate.get("vehicle_bbox"):
                        vehicle_type = v.get("class_name", "vehicle")
                        break

                self.alert_orchestrator.send_suspicious_vehicle_alert(
                    plate["plate_number"],
                    vehicle_type,
                    location,
                    "Watchlisted plate detected",
                )
            except Exception as e:
                logger.warning(f"Plate alert failed: {e}")

        # --- Compute threat score ---
        ctx.threat_score = min(
            100,
            len(ctx.tracks) * 5
            + (50 if ctx.weapon_present else 0)
            + len(ctx.active_criminals) * 50
            + len(ctx.anomalies) * 10,
        )

        return ctx
