"""Camera tamper detection from the picture alone: covered, blurred, moved, frozen.

Blinding or turning a camera is the first thing an intruder does, and to the rest of the
pipeline it only looks like "nothing detected". These checks run on the raw camera frames
(once a second, on a small grey copy: well under a millisecond) and report a condition once
it has held for a few seconds:

- covered: picture almost black or almost uniform (hand, tape, spray, bag over the lens)
- blurred: sharpness far below what this camera normally has (smeared lens, knocked focus)
- moved:   a steady view that no longer matches the learned one (camera turned or knocked).
           Only the background counts: areas where people are (boxes from the detector) are
           left out, and with too little background in view the check waits. A person walking
           past changes the picture but not steadily, so it does not count either.
- frozen:  exactly the same picture for a long time (a stuck encoder or a looped image)

Limits: a very dark night scene can read as covered; a perfectly static, heavily compressed
scene can read as frozen. Thresholds are in config.yaml under `tamper:`.
"""

from collections import deque
from typing import Optional

import cv2
import numpy as np

MESSAGES = {
    "covered": "Camera view blocked: the picture is dark or uniform (covered, sprayed or pointed at a wall)",
    "blurred": "Camera picture blurred: much less sharp than usual (lens smeared or focus knocked)",
    "moved": "Camera moved: the view no longer matches what this camera normally sees",
    "frozen": "Camera picture frozen: the image has not changed at all",
}


def _corr(a: np.ndarray, b: np.ndarray, mask: Optional[np.ndarray] = None) -> float:
    if mask is not None:
        a, b = a[mask], b[mask]
    a = a - a.mean()
    b = b - b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den > 1e-6 else 1.0


def _background(shape_hw, frame_hw, people) -> np.ndarray:
    """True where no person is, on the small grid (boxes grown 15 % to cover arms and shadow)."""
    h, w = shape_hw
    fh, fw = frame_hw
    mask = np.ones((h, w), bool)
    for x1, y1, x2, y2 in people or ():
        gx, gy = (x2 - x1) * 0.15, (y2 - y1) * 0.15
        c1, c2 = int(max(0, (x1 - gx) * w / fw)), int(min(w, np.ceil((x2 + gx) * w / fw)))
        r1, r2 = int(max(0, (y1 - gy) * h / fh)), int(min(h, np.ceil((y2 + gy) * h / fh)))
        mask[r1:r2, c1:c2] = False
    return mask


class TamperDetector:
    def __init__(self, every: float = 1.0, persist: float = 5.0, warmup: int = 10,
                 dark_level: float = 18.0, flat_std: float = 6.0,
                 blur_ratio: float = 0.25, min_sharpness: float = 15.0,
                 moved_corr: float = 0.35, steady_corr: float = 0.85, moved_persist: float = 10.0,
                 frozen_seconds: float = 60.0, cooldown: float = 300.0, min_background: float = 0.35,
                 checks=("covered", "blurred", "moved", "frozen")):
        self.every, self.persist, self.warmup = every, persist, warmup
        self.dark_level, self.flat_std = dark_level, flat_std
        self.blur_ratio, self.min_sharpness = blur_ratio, min_sharpness
        self.moved_corr, self.steady_corr, self.moved_persist = moved_corr, steady_corr, moved_persist
        self.frozen_seconds, self.cooldown = frozen_seconds, cooldown
        self.min_background = min_background
        self.checks = set(checks)
        self._last_sample = -1e9
        self._samples = 0
        self._sharp = deque(maxlen=120)        # sharpness of healthy samples: this camera's normal
        self._ref = None                       # the learned view (small grey image)
        self._prev = None
        self._prev_fine = None
        self._since: dict = {}                 # kind -> when the condition started
        self._fired: dict = {}                 # kind -> when it was last reported

    @classmethod
    def from_config(cls, cfg: Optional[dict]) -> Optional["TamperDetector"]:
        cfg = cfg or {}
        if not cfg.get("enabled", True):
            return None
        keys = ("every", "persist", "warmup", "dark_level", "flat_std", "blur_ratio", "min_sharpness",
                "moved_corr", "steady_corr", "moved_persist", "frozen_seconds", "cooldown", "min_background", "checks")
        return cls(**{k: cfg[k] for k in keys if k in cfg})

    def _held(self, kind: str, active: bool, now: float, needed: float) -> bool:
        if not active or kind not in self.checks:
            self._since.pop(kind, None)
            return False
        start = self._since.setdefault(kind, now)
        return now - start >= needed

    def check(self, frame: np.ndarray, now: float, people=None) -> Optional[str]:
        """Feed every frame; returns a condition ('covered', 'blurred', 'moved', 'frozen') the
        moment it has held long enough, at most once per `cooldown` per condition.
        `people`: person boxes (x1, y1, x2, y2) in frame pixels, left out of the move check."""
        if now - self._last_sample < self.every:
            return None
        self._last_sample = now
        self._samples += 1

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        fine = cv2.resize(gray, (320, 180), interpolation=cv2.INTER_AREA)
        small8 = cv2.resize(fine, (64, 36), interpolation=cv2.INTER_AREA)
        small = small8.astype(np.float32)
        mean, std = float(small.mean()), float(small.std())
        # The move check compares contrast-equalised views: auto-exposure settling or lights
        # switching change brightness non-linearly, which is not a move.
        view = cv2.equalizeHist(small8).astype(np.float32)
        sharp = float(cv2.Laplacian(fine, cv2.CV_64F).var())

        covered = mean < self.dark_level or std < self.flat_std
        frozen = self._prev_fine is not None and not covered and \
            float(np.abs(fine.astype(np.int16) - self._prev_fine).mean()) < 0.02
        self._prev_fine = fine.astype(np.int16)

        learned = self._samples > self.warmup
        normal = float(np.median(self._sharp)) if self._sharp else 0.0
        blurred = learned and not covered and normal >= self.min_sharpness and sharp < self.blur_ratio * normal

        moved = False
        bg = _background(small.shape, gray.shape, people)
        if not covered and bg.mean() >= self.min_background:
            if self._ref is None or not learned:
                self._ref = view                    # through warm-up: exposure is still settling
            else:
                to_ref = _corr(view, self._ref, bg)
                steady = self._prev is not None and _corr(view, self._prev, bg) >= self.steady_corr
                moved = to_ref < self.moved_corr and steady
                if to_ref > 0.8:
                    # Follow slow light changes, on the background only (people must not become "normal").
                    self._ref = np.where(bg, 0.9 * self._ref + 0.1 * view, self._ref)
        self._prev = view

        if not (covered or blurred):
            self._sharp.append(sharp)

        found = None
        for kind, active, needed in (("covered", covered, self.persist), ("moved", moved, self.moved_persist),
                                     ("blurred", blurred, self.persist), ("frozen", frozen, self.frozen_seconds)):
            if self._held(kind, active, now, needed) and now - self._fired.get(kind, -1e9) >= self.cooldown:
                self._fired[kind] = now
                found = found or kind
                if kind == "moved":
                    self._ref = view                  # the new view becomes the normal one
                    self._since.pop("moved", None)
        return found
