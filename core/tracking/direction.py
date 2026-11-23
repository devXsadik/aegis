"""Direction of travel from a track inside one camera, using the camera's compass heading.

Image → world (ground plane, camera looking roughly along the road):
    moving up the frame (away from the camera)    → the heading the camera faces
    moving down (toward the camera)               → heading + 180°
    moving right / left across the frame          → heading + 90° / − 90°
so bearing = heading + atan2(dx, −dy) with dx → right and dy → down in image coordinates.
Example from the spec: a north-facing camera (0°), target leaves frame-left → 270° → W."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

COMPASS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
EDGE = 0.08          # within 8 % of a border counts as "at the edge"


def compass8(deg: float) -> str:
    return COMPASS_8[int(((deg % 360) + 22.5) // 45) % 8]


def side(x: float, y: float) -> Optional[str]:
    """Which border a normalised point (0–1) is at, if any."""
    d = {"left": x, "right": 1 - x, "top": y, "bottom": 1 - y}
    k = min(d, key=d.get)
    return k if d[k] <= EDGE else None


@dataclass
class TrackDirection:
    entry_side: Optional[str]
    exit_side: Optional[str]
    bearing: Optional[float]          # degrees clockwise from north
    direction: Optional[str]          # N … NW
    moved: float                      # normalised distance travelled in the frame

    def as_dict(self):
        return {"entry_side": self.entry_side, "exit_side": self.exit_side,
                "bearing": round(self.bearing, 1) if self.bearing is not None else None,
                "direction": self.direction, "moved": round(self.moved, 3)}


def from_points(points: Sequence[Tuple[float, float]], heading: Optional[float],
                min_move: float = 0.08) -> TrackDirection:
    """points: normalised (x, y) centres (or foot points) in time order."""
    if not points:
        return TrackDirection(None, None, None, None, 0.0)
    (x0, y0), (x1, y1) = points[0], points[-1]
    # Smooth: average the first and last few points so a jittery box does not flip the direction.
    k = max(1, min(5, len(points) // 4))
    sx = sum(p[0] for p in points[:k]) / k
    sy = sum(p[1] for p in points[:k]) / k
    ex = sum(p[0] for p in points[-k:]) / k
    ey = sum(p[1] for p in points[-k:]) / k
    dx, dy = ex - sx, ey - sy
    moved = math.hypot(dx, dy)
    entry, exit_ = side(x0, y0), side(x1, y1)
    if moved < min_move or heading is None:
        return TrackDirection(entry, exit_, None, None, moved)
    bearing = (heading + math.degrees(math.atan2(dx, -dy))) % 360
    return TrackDirection(entry, exit_, bearing, compass8(bearing), moved)


def exit_bearing(heading: float, exit_side: str) -> float:
    """Bearing implied by the border a target left through (when only the exit is known)."""
    off = {"top": 0, "right": 90, "bottom": 180, "left": 270}[exit_side]
    return (heading + off) % 360


def summarize(points: List[Tuple[float, float]], heading: Optional[float]) -> dict:
    return from_points(points, heading).as_dict()
