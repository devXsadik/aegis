"""Scene events beyond people: wrong-way vehicles, unattended bags, crowd surges.

* Wrong way — a zone of type `one_way` has a `direction` (degrees, image coordinates: 0 = right,
  90 = down the picture). A vehicle track moving inside it more than `max_angle` away from that
  direction, over at least `min_travel` of the frame, raises one alert per track.
* Unattended bag — backpacks, handbags and suitcases (COCO classes the person model already
  knows) that stay put for `still_seconds` with nobody within `owner_radius` for
  `alone_seconds`. One alert per bag; a bag that is picked up or hidden for a while is forgotten.
* Crowd surge — the number of people in a zone at least doubles (to `min_people` or more) within
  `window_seconds`: an early warning for crushes at gatherings, not an alarm on a busy street.

All three are heuristics: measure them on your own clips (scripts/evaluate_accuracy.py) before
switching them on for a camera. Inputs are pixel boxes; everything is normalised to the frame.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

BAG_CLASSES = {24: "backpack", 26: "handbag", 28: "suitcase"}


def _centre(b) -> Tuple[float, float]:
    x1, y1, x2, y2 = b
    return (x1 + x2) / 2, (y1 + y2) / 2


def angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


class WrongWayDetector:
    def __init__(self, max_angle: float = 120.0, min_travel: float = 0.06, history: int = 12):
        self.max_angle = max_angle
        self.min_travel = min_travel
        self._hist: Dict[str, deque] = {}
        self._reported: set = set()

    def update(self, vehicle_tracks: Sequence, frame_shape, zones: Sequence) -> List[dict]:
        """vehicle_tracks: objects with track_id, to_ltrb(), is_confirmed(); zones: core.analysis.zones.Zone
        with type 'one_way' and a direction."""
        h, w = frame_shape[:2]
        one_way = [z for z in zones if getattr(z, "type", "") == "one_way" and getattr(z, "direction", None) is not None]
        out, live = [], set()
        for t in vehicle_tracks:
            if hasattr(t, "is_confirmed") and not t.is_confirmed():
                continue
            tid = str(t.track_id)
            live.add(tid)
            x1, y1, x2, y2 = t.to_ltrb()
            p = ((x1 + x2) / 2 / w, y2 / h)               # bottom centre: where the vehicle touches the road
            hist = self._hist.setdefault(tid, deque(maxlen=12))
            hist.append(p)
            if tid in self._reported or len(hist) < 4:
                continue
            (ax, ay), (bx, by) = hist[0], hist[-1]
            dist = math.hypot(bx - ax, by - ay)
            if dist < self.min_travel:
                continue
            heading = math.degrees(math.atan2(by - ay, bx - ax)) % 360
            for z in one_way:
                if z.contains(*p) and z.contains(ax, ay) and angle_diff(heading, z.direction) > self.max_angle:
                    self._reported.add(tid)
                    out.append({"type": "wrong_way", "zone": z.name, "track_id": tid, "severity": "high",
                                "heading": round(heading), "allowed": z.direction,
                                "message": f"Vehicle going the wrong way in {z.name}"})
                    break
        for tid in [k for k in self._hist if k not in live]:
            del self._hist[tid]
            self._reported.discard(tid)
        return out


@dataclass
class _Bag:
    box: Tuple[float, float, float, float]
    first: float
    last_seen: float
    still_since: float
    alone_since: Optional[float] = None
    reported: bool = False
    kind: str = "bag"


class AbandonedObjectDetector:
    def __init__(self, still_seconds: float = 60, alone_seconds: float = 30, owner_radius: float = 0.12,
                 move_tolerance: float = 0.02, forget_seconds: float = 10):
        self.still_seconds = still_seconds
        self.alone_seconds = alone_seconds
        self.owner_radius = owner_radius
        self.move_tolerance = move_tolerance
        self.forget_seconds = forget_seconds
        self._bags: List[_Bag] = []

    def update(self, bags: Sequence[dict], people: Sequence, frame_shape, now: float) -> List[dict]:
        """bags: [{"bbox": (x1,y1,x2,y2), "class_name": ...}]; people: [([x1,y1,x2,y2], conf, cls)]."""
        h, w = frame_shape[:2]
        norm = lambda b: (b[0] / w, b[1] / h, b[2] / w, b[3] / h)   # noqa: E731
        persons = [_centre(norm(p[0])) for p in people]
        matched = set()
        out = []
        for det in bags:
            box = norm(det["bbox"])
            c = _centre(box)
            best, best_d = None, 1e9
            for i, b in enumerate(self._bags):
                if i in matched:
                    continue
                d = math.dist(c, _centre(b.box))
                if d < best_d:
                    best, best_d = i, d
            if best is not None and best_d <= 0.06:
                bag = self._bags[best]
                matched.add(best)
                if best_d > self.move_tolerance:            # carried: start over
                    bag.still_since, bag.alone_since = now, None
                bag.box, bag.last_seen, bag.kind = box, now, det.get("class_name", bag.kind)
            else:
                self._bags.append(_Bag(box, now, now, now, kind=det.get("class_name", "bag")))
                matched.add(len(self._bags) - 1)
                bag = self._bags[-1]
            near = any(math.dist(_centre(bag.box), p) <= self.owner_radius for p in persons)
            if near:
                bag.alone_since = None
            elif bag.alone_since is None:
                bag.alone_since = now
            if (not bag.reported and now - bag.still_since >= self.still_seconds
                    and bag.alone_since is not None and now - bag.alone_since >= self.alone_seconds):
                bag.reported = True
                out.append({"type": "abandoned_object", "severity": "high", "object": bag.kind,
                            "still_seconds": int(now - bag.still_since),
                            "bbox_norm": [round(v, 3) for v in bag.box],
                            "message": f"Unattended {bag.kind} for {int(now - bag.alone_since)} s"})
        self._bags = [b for b in self._bags if now - b.last_seen <= self.forget_seconds]
        return out


@dataclass
class CrowdSurgeDetector:
    window_seconds: float = 60
    min_people: int = 10
    factor: float = 2.0
    _hist: Dict[str, deque] = field(default_factory=dict)
    _alerted: Dict[str, float] = field(default_factory=dict)

    def update(self, zone_counts: Dict[str, int], now: float) -> List[dict]:
        out = []
        for zone, n in zone_counts.items():
            h = self._hist.setdefault(zone, deque())
            h.append((now, n))
            while h and now - h[0][0] > self.window_seconds:
                h.popleft()
            low = min(c for _, c in h)
            if n >= self.min_people and n >= self.factor * max(low, 1):
                if now - self._alerted.get(zone, -1e9) > self.window_seconds:
                    self._alerted[zone] = now
                    out.append({"type": "crowd_surge", "zone": zone, "count": n, "from": low, "severity": "high",
                                "message": f"Crowd surge in {zone}: {low} → {n} people within {int(self.window_seconds)} s"})
        return out
