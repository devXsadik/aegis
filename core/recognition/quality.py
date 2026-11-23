"""Is a face good enough to match? Blurry, tiny or strongly turned faces make confident-looking
wrong matches, so they are dropped before matching (and counted, so cameras with bad angles show up)."""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

MIN_FACE_PX = int(os.getenv("FACE_MIN_PX", "40"))
MIN_SHARPNESS = float(os.getenv("FACE_MIN_SHARPNESS", "45"))
MAX_YAW_DEG = float(os.getenv("FACE_MAX_YAW", "40"))


def sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def yaw_from_landmarks(row: Optional[np.ndarray]) -> Optional[float]:
    """Rough left/right head turn from YuNet's 5 landmarks (eyes, nose): the nose drifts toward
    the eye on the side the head turns to. 0 = frontal."""
    if row is None or len(row) < 15:
        return None
    rx, lx, nx = row[4], row[6], row[8]
    span = abs(lx - rx)
    if span < 1:
        return 90.0
    offset = (nx - (rx + lx) / 2) / span          # -0.5 … 0.5
    return float(np.clip(offset * 180, -90, 90))


def check(face_bgr: np.ndarray, row: Optional[np.ndarray] = None) -> Tuple[bool, float, List[str]]:
    """(ok, score 0–1, reasons it failed)."""
    reasons = []
    if face_bgr is None or face_bgr.size == 0:
        return False, 0.0, ["empty"]
    h, w = face_bgr.shape[:2]
    if row is not None:
        w, h = int(row[2]), int(row[3])
    if min(w, h) < MIN_FACE_PX:
        reasons.append(f"too small ({min(w, h)} px)")
    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY) if face_bgr.ndim == 3 else face_bgr
    sharp = sharpness(cv2.resize(gray, (112, 112)))
    if sharp < MIN_SHARPNESS:
        reasons.append(f"blurry ({sharp:.0f})")
    yaw = yaw_from_landmarks(row)
    if yaw is not None and abs(yaw) > MAX_YAW_DEG:
        reasons.append(f"turned away ({yaw:.0f}°)")
    score = min(1.0, sharp / (MIN_SHARPNESS * 4)) * (1.0 if yaw is None else max(0.0, 1 - abs(yaw) / 90))
    return not reasons, round(score, 3), reasons
