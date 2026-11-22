"""Possible fight: two people close together, both moving their arms fast, for a while.

A pose heuristic, not a trained model. The models tried before (ST-GCN fighting/pushing
classes, public VideoMAE fight models) missed real CCTV fights and could not tell staged
fights from normal clips (see AGENTS.md), so this ships OFF (`fight.enabled: false`) and is
meant to be turned on only after scripts/evaluate_accuracy.py shows it stays inside an
acceptable false-alert rate on your cameras.

Per pair of people, on every fresh pose pass:
  close   — box centres within `near` box-widths of each other and heights alike (same depth)
  violent — both people's fastest wrist moved more than `arm_speed` body-heights per second
A pair that is close and violent in at least `min_hits` of the last `window` passes is flagged:
one hand wave is not a fight; a sustained exchange is.
"""

from collections import defaultdict, deque
from itertools import combinations
from typing import Dict, Optional, Set, Tuple

WRISTS = ("left_wrist", "right_wrist")


def _centre(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


class FightDetector:
    def __init__(self, near: float = 1.3, arm_speed: float = 1.6, window: int = 6, min_hits: int = 4,
                 min_conf: float = 0.3):
        self.near, self.arm_speed = near, arm_speed
        self.window, self.min_hits, self.min_conf = window, min_hits, min_conf
        self._last: Dict[int, Tuple[float, dict, float]] = {}          # tid -> (t, wrists, body height)
        self._pairs = defaultdict(lambda: deque(maxlen=window))

    @classmethod
    def from_config(cls, cfg: Optional[dict]) -> Optional["FightDetector"]:
        cfg = cfg or {}
        if not cfg.get("enabled", False):
            return None
        keys = ("near", "arm_speed", "window", "min_hits", "min_conf")
        return cls(**{k: cfg[k] for k in keys if k in cfg})

    def _arm_speed(self, tid: int, pose: dict, now: float) -> Optional[float]:
        """Fastest wrist speed in body-heights per second since this person's previous pose."""
        x1, y1, x2, y2 = pose["bbox"]
        height = max(1.0, y2 - y1)
        wrists = {w: pose["kpts"][w][:2] for w in WRISTS
                  if w in pose["kpts"] and pose["kpts"][w][2] >= self.min_conf}
        prev = self._last.get(tid)
        self._last[tid] = (now, wrists, height)
        if not prev or now <= prev[0]:
            return None
        t0, before, h0 = prev
        moves = [((wrists[w][0] - before[w][0]) ** 2 + (wrists[w][1] - before[w][1]) ** 2) ** 0.5
                 for w in wrists if w in before]
        if not moves:
            return None
        return max(moves) / ((height + h0) / 2) / (now - t0)

    def update(self, now: float, poses: Dict[int, dict]) -> Set[int]:
        """`poses`: track_id -> {'bbox', 'kpts'} from this pose pass. Returns tracks in a likely fight."""
        speeds = {tid: self._arm_speed(tid, p, now) for tid, p in poses.items()}
        for tid in [t for t in self._last if t not in poses]:
            del self._last[tid]
        flagged: Set[int] = set()
        seen = set()
        for a, b in combinations(sorted(poses), 2):
            pa, pb = poses[a]["bbox"], poses[b]["bbox"]
            wa, wb = pa[2] - pa[0], pb[2] - pb[0]
            ha, hb = pa[3] - pa[1], pb[3] - pb[1]
            (ax, ay), (bx, by) = _centre(pa), _centre(pb)
            close = (abs(ax - bx) <= self.near * (wa + wb) / 2 and abs(ay - by) <= 0.5 * (ha + hb) / 2
                     and min(ha, hb) / max(ha, hb, 1) >= 0.6)
            violent = all(s is not None and s >= self.arm_speed for s in (speeds[a], speeds[b]))
            key = (a, b)
            seen.add(key)
            self._pairs[key].append(close and violent)
            if sum(self._pairs[key]) >= self.min_hits:
                flagged |= {a, b}
        for key in [k for k in self._pairs if k not in seen]:
            del self._pairs[key]
        return flagged
