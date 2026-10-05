import threading
import time
from typing import Callable, List, Optional, Tuple

import cv2
import face_recognition
import numpy as np

from utils.face_detect import locate_faces

# dlib's HOG detector / shape predictor / encoder are shared module-level objects and
# are not thread-safe: concurrent calls from several camera threads segfault the process.
_DLIB_LOCK = threading.Lock()

Loader = Callable[[], Tuple[List[np.ndarray], List[str]]]


class FaceRecognizerDB:
    """dlib face matcher with quality gating and a best-vs-second-best margin.

    Encodings come from an injected `loader` (the composition root supplies the DB
    one) and are refreshed every `cache_ttl` seconds so watchlist edits reach a
    running pipeline without a restart.
    """

    def __init__(self, tolerance: float = 0.45, loader: Optional[Loader] = None,
                 cache_ttl: float = 60.0, min_face_px: int = 40,
                 min_sharpness: float = 25.0, min_margin: float = 0.04,
                 solo_slack: float = 0.0, cnn_cooldown: float = 3.0):
        self.tolerance = tolerance
        self.loader = loader or (lambda: ([], []))
        self.cache_ttl = cache_ttl
        self.min_face_px = min_face_px
        self.min_sharpness = min_sharpness
        self.min_margin = min_margin
        self.solo_slack = solo_slack            # extra strictness when no rival identity exists to compare
        self.cnn_cooldown = cnn_cooldown        # seconds between slow CNN fallbacks (all cameras)
        self._last_cnn = 0.0
        self._cache = None
        self._loaded_at = 0.0

    def _load_encodings(self):
        if self._cache is None or time.time() - self._loaded_at > self.cache_ttl:
            self._cache = self.loader()
            self._loaded_at = time.time()
        return self._cache

    def _quality_ok(self, rgb, box) -> bool:
        top, right, bottom, left = box
        if min(bottom - top, right - left) < self.min_face_px:
            return False
        crop = cv2.cvtColor(rgb[top:bottom, left:right], cv2.COLOR_RGB2GRAY)
        return cv2.Laplacian(crop, cv2.CV_64F).var() >= self.min_sharpness

    def match(self, distances: np.ndarray, names: List[str]) -> Optional[Tuple[str, float, float]]:
        """Pure matching logic: (person, distance, margin) or None."""
        best = {}
        for d, n in zip(distances, names):
            if n not in best or d < best[n]:
                best[n] = float(d)
        ranked = sorted(best.items(), key=lambda kv: kv[1])
        if not ranked or ranked[0][1] > self.tolerance:
            return None
        if len(ranked) > 1:
            margin = ranked[1][1] - ranked[0][1]
            if margin < self.min_margin:
                return None
        else:
            # Single enrolled identity: no rival to rank against. `solo_slack` (default 0) can demand a
            # tighter match, but real webcam distances for the true person are ~0.40-0.45, so keep it small.
            if ranked[0][1] > self.tolerance - self.solo_slack:
                return None
            margin = self.tolerance - ranked[0][1]
        return ranked[0][0], ranked[0][1], margin

    def recognize_detail(self, face_roi) -> Optional[dict]:
        rgb = cv2.cvtColor(face_roi, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        upsample = 3 if (h < 120 or w < 120) else 2 if (h < 300 or w < 300) else 1

        with _DLIB_LOCK:
            now = time.time()
            use_cnn = now - self._last_cnn >= self.cnn_cooldown
            boxes = locate_faces(rgb, face_recognition, upsample=upsample, cnn_fallback=use_cnn)
            if use_cnn and not boxes:
                self._last_cnn = now            # HOG missed and CNN ran: wait before the next one
            boxes = [b for b in boxes if self._quality_ok(rgb, b)]
            if not boxes:
                return None
            boxes = [max(boxes, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]))]   # largest face only
            encodings = face_recognition.face_encodings(rgb, boxes)
        if not encodings:
            return None
        known_encodings, known_names = self._load_encodings()
        if not known_encodings:
            return None
        distances = face_recognition.face_distance(known_encodings, encodings[0])
        res = self.match(distances, known_names)
        if res is None:
            return None
        return {"name": res[0], "distance": res[1], "margin": res[2]}

    def recognize_person(self, face_roi) -> Optional[str]:
        res = self.recognize_detail(face_roi)
        return res["name"] if res else None

    @staticmethod
    def confidence(distance: float, tolerance: float) -> float:
        """0-1 heuristic: 1.0 at distance 0, 0.5 at the tolerance (same as the registry's verify)."""
        return round(max(0.0, min(1.0, 1.0 - distance / (2 * tolerance))), 3)

    def invalidate_cache(self):
        self._cache = None
