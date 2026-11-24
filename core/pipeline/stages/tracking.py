"""
Tracking Stage
==============
Runs DeepSORT tracking on detections to assign persistent track IDs.
"""

import logging
from core.pipeline.base import PipelineStage, FrameContext

logger = logging.getLogger("HumanAnalysis")


class TrackingStage(PipelineStage):
    """Updates DeepSORT trackers with current frame detections."""

    def __init__(self, human_tracker, vehicle_tracker=None, enabled: bool = True, person_confirm_conf: float = 0.6):
        super().__init__(name="tracking", enabled=enabled)
        self.human_tracker = human_tracker
        self.vehicle_tracker = vehicle_tracker
        # Detection keeps weak person boxes (0.4) so the tracker holds on to half-hidden people, but a
        # track is only passed on (recognition, behaviour, weapons, alerts) once it has had at least one
        # detection this sure. Coats on a hook, chairs and posters hover around 0.4 and never get there.
        self.person_confirm_conf = person_confirm_conf
        self._best_conf = {}

    def _sure(self, tracks):
        live = set()
        for t in tracks:
            tid = t.track_id
            live.add(tid)
            conf = getattr(t, "det_conf", None)
            if conf is not None and conf > self._best_conf.get(tid, 0.0):
                self._best_conf[tid] = float(conf)
        for tid in [k for k in self._best_conf if k not in live]:
            del self._best_conf[tid]
        return [t for t in tracks if self._best_conf.get(t.track_id, 0.0) >= self.person_confirm_conf]

    def process(self, ctx: FrameContext) -> FrameContext:
        # Track humans
        ctx.tracks = self._sure(self.human_tracker.track(ctx.human_detections, ctx.frame))

        # Track vehicles
        if self.vehicle_tracker is not None and ctx.vehicle_detections:
            try:
                ctx.vehicle_tracks = self.vehicle_tracker.track(
                    ctx.vehicle_detections, ctx.frame
                )
            except Exception as e:
                logger.warning(f"Vehicle tracking error: {e}")

        return ctx
