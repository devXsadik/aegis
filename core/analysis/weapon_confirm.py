"""Associate weapon detections with person tracks and confirm over time.

A single frame is never treated as certain: a weapon alert fires only when the
same track (or the unassigned bucket) has a weapon hit in at least `min_hits`
of the last `window` processed frames. Before that, WeaponScreen drops hits that
are tiny, or not in anyone's hand and not confident enough.
"""

from collections import defaultdict, deque
from typing import Iterable, Optional

UNASSIGNED = -1


def overlap_ratio(weapon_bbox, person_bbox) -> float:
    """Fraction of the weapon box that lies inside the person box."""
    wx1, wy1, wx2, wy2 = weapon_bbox
    px1, py1, px2, py2 = person_bbox
    iw = min(wx2, px2) - max(wx1, px1)
    ih = min(wy2, py2) - max(wy1, py1)
    area = max(1, (wx2 - wx1) * (wy2 - wy1))
    return max(0, iw) * max(0, ih) / area


def associate(weapon_detections: Iterable[dict], tracks, min_overlap: float = 0.3) -> dict:
    """Map track_id -> best weapon detection. Unmatched weapons go to UNASSIGNED."""
    boxes = {}
    for t in tracks:
        if t.is_confirmed():
            boxes[t.track_id] = tuple(map(int, t.to_ltrb()))

    out: dict = {}
    for w in weapon_detections:
        best_id: Optional[int] = None
        best = min_overlap
        for tid, pb in boxes.items():
            r = overlap_ratio(w["bbox"], pb)
            if r >= best:
                best, best_id = r, tid
        key = UNASSIGNED if best_id is None else best_id
        if key not in out or w["score"] > out[key]["score"]:
            out[key] = w
    return out


class WeaponConfirmer:
    def __init__(self, window: int = 5, min_hits: int = 3):
        self.window = window
        self.min_hits = min_hits
        self._hist = defaultdict(lambda: deque(maxlen=window))

    def update(self, assigned: dict) -> set:
        """Feed one processed frame; return keys confirmed on this frame."""
        for key in set(self._hist) | set(assigned):
            self._hist[key].append(key in assigned)
        confirmed = {
            k for k, h in self._hist.items()
            if k in assigned and sum(h) >= self.min_hits
        }
        for k in [k for k, h in self._hist.items() if not any(h)]:
            del self._hist[k]
        return confirmed


WRISTS = ("left_wrist", "right_wrist")


def _gap(point, box) -> float:
    """Distance from a point to a box (0 when inside)."""
    x, y = point
    x1, y1, x2, y2 = box
    dx = max(x1 - x, 0, x - x2)
    dy = max(y1 - y, 0, y - y2)
    return (dx * dx + dy * dy) ** 0.5


def held_in_hand(weapon_bbox, person_bbox, kpts: Optional[dict], reach: float = 0.25) -> Optional[bool]:
    """True: a wrist is on or next to the weapon. False: wrists are visible but away from it.
    None: no visible wrist (no pose, hands hidden), so it cannot be told."""
    wrists = [kpts[w][:2] for w in WRISTS if kpts and w in kpts]
    if not wrists:
        return None
    limit = reach * max(1, person_bbox[3] - person_bbox[1])     # a fraction of the person's height
    return any(_gap(p, weapon_bbox) <= limit for p in wrists)


def _area(b) -> float:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


class WeaponScreen:
    """Per-frame checks before a weapon hit counts towards confirmation.

    Phones, tools, umbrellas, clothing and whole bodies are the usual false weapons. Cheap cues:
    - tiny boxes: below `min_side_px` the model mostly guesses;
    - huge boxes: a weapon is a hand-held object. A box over `max_frame_frac` of the frame, over
      `max_person_frac` of the person it is on, or nearly the same box as that person (IoU over
      `max_person_iou`) is the model mistaking a body, a coat or a door for a blade;
    - per class: `class_min_score` raises the bar for classes the model confuses most;
    - not in a hand: if the person's wrists are visible but away from the box (or there is no
      person), the hit must reach `unheld_min_score`; if the hands cannot be seen, `unknown_min_score`.
    Each kept detection gets `held` (True / False / None) for the alert text.
    """

    def __init__(self, min_side_px: int = 14, unheld_min_score: float = 0.65, reach: float = 0.25,
                 unknown_min_score: float = 0.55, max_frame_frac: float = 0.25, max_person_frac: float = 0.45,
                 max_person_iou: float = 0.5, class_min_score: Optional[dict] = None):
        self.min_side_px = min_side_px
        self.unheld_min_score = unheld_min_score
        self.unknown_min_score = unknown_min_score
        self.reach = reach
        self.max_frame_frac = max_frame_frac
        self.max_person_frac = max_person_frac
        self.max_person_iou = max_person_iou
        self.class_min_score = {str(k): float(v) for k, v in (class_min_score or {}).items()}

    def big_enough(self, w: dict) -> bool:
        x1, y1, x2, y2 = w["bbox"]
        return min(x2 - x1, y2 - y1) >= self.min_side_px

    def fits_frame(self, w: dict, frame_shape) -> bool:
        """Not a box covering a large part of the picture, and sure enough for its class."""
        if w["score"] < self.class_min_score.get(str(w.get("class_name")), 0.0):
            return False
        if frame_shape is None:
            return True
        return _area(w["bbox"]) <= self.max_frame_frac * frame_shape[0] * frame_shape[1]

    def fits_person(self, w: dict, person_box) -> bool:
        """A hand-held object is a small part of the person holding it."""
        p = _area(person_box)
        if p <= 0:
            return True
        a = _area(w["bbox"])
        x1, y1 = max(w["bbox"][0], person_box[0]), max(w["bbox"][1], person_box[1])
        x2, y2 = min(w["bbox"][2], person_box[2]), min(w["bbox"][3], person_box[3])
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        iou = inter / (a + p - inter) if a + p - inter > 0 else 0.0
        return a <= self.max_person_frac * p and iou <= self.max_person_iou

    def screen(self, assigned: dict, tracks, poses: Optional[dict] = None) -> dict:
        """`assigned` from associate() → the hits that count this frame, each with `held`."""
        boxes = {t.track_id: tuple(map(int, t.to_ltrb())) for t in tracks if t.is_confirmed()}
        kept = {}
        for key, w in assigned.items():
            if key != UNASSIGNED and not self.fits_person(w, boxes[key]):
                continue
            held = (None if key == UNASSIGNED
                    else held_in_hand(w["bbox"], boxes[key], (poses or {}).get(key, {}).get("kpts"), self.reach))
            need = (0.0 if held is True
                    else self.unknown_min_score if (held is None and key != UNASSIGNED)
                    else self.unheld_min_score)
            if w["score"] >= need:
                kept[key] = {**w, "held": held}
        return kept
