"""Clothing colours of a person crop (upper and lower body) for searching case evidence.

Colour names follow core/analysis/vehicle_attrs._label (red, maroon, orange, brown, yellow, green,
blue, white, silver/grey, black). Lighting changes colours, so a search is a lead, not proof.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

COLOURS = ("black", "white", "grey", "silver", "red", "maroon", "orange", "brown", "yellow", "green", "blue", "other")


def _vote(region: np.ndarray) -> Tuple[Optional[str], float]:
    from core.analysis.vehicle_attrs import _label
    if region is None or region.size == 0:
        return None, 0.0
    small = cv2.resize(region, (24, 24), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    votes: dict = {}
    for h, s, v in hsv:
        lab = _label(int(h), int(s), int(v))
        votes[lab] = votes.get(lab, 0) + 1
    best = max(votes, key=votes.get)
    return best, votes[best] / len(hsv)


def clothing_colours(person: np.ndarray) -> Tuple[Optional[str], Optional[str]]:
    """(upper, lower) colour of a person crop (head excluded, arms trimmed)."""
    if cv2 is None or person is None or person.ndim != 3 or person.shape[0] < 40:
        return None, None
    h, w = person.shape[:2]
    x0, x1 = int(w * 0.25), int(w * 0.75)
    upper, _ = _vote(person[int(h * 0.18):int(h * 0.50), x0:x1])
    lower, _ = _vote(person[int(h * 0.55):int(h * 0.90), x0:x1])
    return upper, lower
