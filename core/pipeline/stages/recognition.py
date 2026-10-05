"""
Recognition Stage
=================
Face recognition + identity management for tracked persons.
"""

import cv2
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from core.pipeline.base import PipelineStage, FrameContext
from core.recognition.voting import IdentityVoter

logger = logging.getLogger("HumanAnalysis")


class RecognitionStage(PipelineStage):
    """Runs face recognition on tracked person ROIs in the background."""

    def __init__(self, face_recognizer, criminal_names: set,
                 rerecognize_every: int = 30, retry_every: int = 5,
                 voter: IdentityVoter = None, enabled: bool = True):
        super().__init__(name="recognition", enabled=enabled)
        self.face_recognizer = face_recognizer
        self.criminal_names = criminal_names
        self.rerecognize_every = rerecognize_every
        self.retry_every = retry_every          # faster retries until a name is confirmed
        self.voter = voter or IdentityVoter(window=5, min_votes=2)

        # Per-track state (persists across frames)
        self._id_name_map: dict = {}           # track_id → name
        self._id_conf: dict = {}               # track_id → latest real match confidence
        self._id_frame_count = defaultdict(int) # track_id → frames seen
        
        # Async state
        self._pending_tasks = set()
        self.executor = ThreadPoolExecutor(max_workers=2)

    def _run_recognition(self, track_id, proc_roi):
        try:
            detail = self.face_recognizer.recognize_detail(proc_roi)
            name = detail["name"] if detail else None
            if detail:
                self._id_conf[track_id] = self.face_recognizer.confidence(
                    detail["distance"], self.face_recognizer.tolerance)
            self.voter.add(track_id, name)
            confirmed = self.voter.confirmed(track_id)
            if confirmed:
                if self._id_name_map.get(track_id) != confirmed and confirmed in self.criminal_names:
                    logger.info(f"WATCHLIST MATCH confirmed: {confirmed} | ID:{track_id}")
                self._id_name_map[track_id] = confirmed
            else:
                self._id_name_map[track_id] = "Unknown"      # votes decayed: never keep a stale name
        except Exception as e:
            logger.warning(f"Face recog failed ID {track_id}: {e}")
        finally:
            self._pending_tasks.discard(track_id)

    def process(self, ctx: FrameContext) -> FrameContext:
        fh, fw = ctx.frame.shape[:2]

        live = {t.track_id for t in ctx.tracks}
        self.voter.prune(live)
        for tid in [k for k in self._id_name_map if k not in live]:
            self._id_name_map.pop(tid, None)
            self._id_frame_count.pop(tid, None)
            self._id_conf.pop(tid, None)

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
            n = self._id_frame_count[track_id]
            unconfirmed = self.voter.confirmed(track_id) is None
            should_recognize = (
                (track_id not in self._id_name_map
                 or n % self.rerecognize_every == 0
                 or (unconfirmed and n % self.retry_every == 0))
                and track_id not in self._pending_tasks
            )

            if should_recognize:
                # Resize ROI if it's too large to prevent CPU bottleneck in HOG
                MAX_ROI_HEIGHT = 400
                h, w = roi.shape[:2]
                if h > MAX_ROI_HEIGHT:
                    scale = MAX_ROI_HEIGHT / h
                    proc_roi = cv2.resize(roi, (int(w * scale), MAX_ROI_HEIGHT))
                else:
                    proc_roi = roi.copy()

                self._pending_tasks.add(track_id)
                self.executor.submit(self._run_recognition, track_id, proc_roi)

            name = self._id_name_map.get(track_id, "Unknown")
            ctx.identities[track_id] = name
            if name in self._id_conf or track_id in self._id_conf:
                ctx.identity_conf[track_id] = self._id_conf.get(track_id, 0.0)

            if name in self.criminal_names:
                ctx.criminal_ids.add(track_id)
                if name not in ctx.active_criminals:
                    ctx.active_criminals.append(name)

        return ctx
