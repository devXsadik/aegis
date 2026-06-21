"""
Recognition Stage
=================
Face recognition + identity management for tracked persons.
"""

import cv2
import logging
from collections import defaultdict
from core.pipeline.base import PipelineStage, FrameContext

logger = logging.getLogger("HumanAnalysis")


class RecognitionStage(PipelineStage):
    """Runs face recognition on tracked person ROIs."""

    def __init__(self, face_recognizer, criminal_names: set,
                 rerecognize_every: int = 30, enabled: bool = True):
        super().__init__(name="recognition", enabled=enabled)
        self.face_recognizer = face_recognizer
        self.criminal_names = criminal_names
        self.rerecognize_every = rerecognize_every

        # Per-track state (persists across frames)
        self._id_name_map: dict = {}           # track_id → name
        self._id_frame_count = defaultdict(int) # track_id → frames seen

    def process(self, ctx: FrameContext) -> FrameContext:
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

            # Decide whether to run face recognition
            self._id_frame_count[track_id] += 1
            should_recognize = (
                track_id not in self._id_name_map
                or self._id_frame_count[track_id] % self.rerecognize_every == 0
            )

            if should_recognize:
                try:
                    # Resize ROI if it's too large to prevent CPU bottleneck in HOG
                    MAX_ROI_HEIGHT = 400
                    h, w = roi.shape[:2]
                    if h > MAX_ROI_HEIGHT:
                        scale = MAX_ROI_HEIGHT / h
                        proc_roi = cv2.resize(roi, (int(w * scale), MAX_ROI_HEIGHT))
                    else:
                        proc_roi = roi

                    name = self.face_recognizer.recognize_person(proc_roi)
                except Exception as e:
                    logger.warning(f"Face recog failed ID {track_id}: {e}")
                    name = None

                if name:
                    self._id_name_map[track_id] = name
                    if name in self.criminal_names:
                        logger.info(f"CRIMINAL DETECTED: {name} | ID:{track_id}")
                elif track_id not in self._id_name_map:
                    self._id_name_map[track_id] = "Unknown"

            name = self._id_name_map.get(track_id, "Unknown")
            ctx.identities[track_id] = name

            if name in self.criminal_names:
                ctx.criminal_ids.add(track_id)
                if name not in ctx.active_criminals:
                    ctx.active_criminals.append(name)

        return ctx
