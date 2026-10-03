"""Apply dashboard-managed thresholds to a running pipeline (no restart)."""

import logging
import threading
import time

from core.analysis.behavior import configure_behavior

logger = logging.getLogger("HumanAnalysis")

# name → (min, max): values outside are ignored, never applied.
LIMITS = {
    "confidence_threshold": (0.30, 0.90),
    "weapon_conf_threshold": (0.20, 0.90),
    "face_tolerance": (0.35, 0.60),
    "loiter_seconds": (5, 120),
    "crowd_threshold": (2, 30),
}


def apply_runtime_config(pipeline, values: dict) -> dict:
    """Set thresholds on the pipeline's stages; return what was actually applied."""
    clean = {k: float(v) for k, v in values.items()
             if k in LIMITS and LIMITS[k][0] <= float(v) <= LIMITS[k][1]}
    for stage in pipeline.stages:
        name = stage.name
        if name == "detection":
            if "confidence_threshold" in clean:
                stage.human_detector.conf_threshold = clean["confidence_threshold"]
                if stage.vehicle_detector is not None:
                    stage.vehicle_detector.conf_threshold = clean["confidence_threshold"]
            if "weapon_conf_threshold" in clean and stage.weapon_detector is not None:
                stage.weapon_detector.conf_threshold = clean["weapon_conf_threshold"]
        elif name == "recognition" and "face_tolerance" in clean:
            stage.face_recognizer.tolerance = clean["face_tolerance"]
        elif name == "behavior" and "crowd_threshold" in clean and stage.anomaly_detector is not None:
            stage.anomaly_detector.crowd_threshold = int(clean["crowd_threshold"])
    if "loiter_seconds" in clean:
        configure_behavior({"loiter_seconds": clean["loiter_seconds"]})
    return clean


class RuntimeConfigSync:
    """Polls the backend every `interval` seconds on a side thread (never blocks the loop)."""

    def __init__(self, pipeline, interval: float = 30.0):
        self.pipeline = pipeline
        self.interval = interval
        self._last = 0.0
        self._busy = False
        self.last_applied: dict = {}

    def maybe_sync(self, now: float = None) -> None:
        now = time.time() if now is None else now
        if self._busy or now - self._last < self.interval:
            return
        self._last = now
        self._busy = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            import httpx

            from utils.alerts.event_publisher import BACKEND_URL, INTERNAL_API_KEY
            r = httpx.get(f"{BACKEND_URL}/api/v1/config/runtime",
                          headers={"X-Internal-Key": INTERNAL_API_KEY}, timeout=3.0)
            if r.status_code == 200:
                applied = apply_runtime_config(self.pipeline, r.json())
                if applied != self.last_applied:
                    logger.info(f"Runtime thresholds applied: {applied}")
                    self.last_applied = applied
        except Exception as e:
            logger.debug(f"Runtime config sync skipped: {e}")
        finally:
            self._busy = False
