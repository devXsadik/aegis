"""Zone geometry: polygons and counting lines in normalized (0-1) coordinates.

Normalized coordinates keep zone definitions valid across resolutions.
cameras.yaml example:

    zones:
      - {name: door, type: restricted, polygon: [[0.1,0.2],[0.4,0.2],[0.4,0.9],[0.1,0.9]]}
      - {name: lobby, type: monitor, polygon: [[0.4,0.1],[0.9,0.1],[0.9,0.9],[0.4,0.9]]}
    lines:
      - {name: entrance, p1: [0.5,0.0], p2: [0.5,1.0]}
"""

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

Point = Tuple[float, float]

QUADRANT_ZONES = [
    {"name": "top_left", "type": "monitor", "polygon": [[0, 0], [.5, 0], [.5, .5], [0, .5]]},
    {"name": "top_right", "type": "monitor", "polygon": [[.5, 0], [1, 0], [1, .5], [.5, .5]]},
    {"name": "bottom_left", "type": "monitor", "polygon": [[0, .5], [.5, .5], [.5, 1], [0, 1]]},
    {"name": "bottom_right", "type": "monitor", "polygon": [[.5, .5], [1, .5], [1, 1], [.5, 1]]},
]


def point_in_polygon(x: float, y: float, poly: Sequence[Point]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _side(p: Point, a: Point, b: Point) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def crossed(prev: Point, cur: Point, a: Point, b: Point) -> int:
    """+1 / -1 if segment prev→cur crosses line a→b (direction by side), else 0."""
    s0, s1 = _side(prev, a, b), _side(cur, a, b)
    if s0 == 0 or s1 == 0 or (s0 > 0) == (s1 > 0):
        return 0
    # Must also fall within the finite segment a-b.
    dx, dy = cur[0] - prev[0], cur[1] - prev[1]
    denom = dx * (b[1] - a[1]) - dy * (b[0] - a[0])
    if denom == 0:
        return 0
    t = ((a[0] - prev[0]) * (b[1] - a[1]) - (a[1] - prev[1]) * (b[0] - a[0])) / denom
    u = ((a[0] - prev[0]) * dy - (a[1] - prev[1]) * dx) / denom
    if not (0 <= t <= 1 and 0 <= u <= 1):
        return 0
    return 1 if s1 > 0 else -1


@dataclass
class Zone:
    name: str
    type: str = "monitor"            # monitor | restricted
    polygon: List[Point] = field(default_factory=list)

    def contains(self, nx: float, ny: float) -> bool:
        return point_in_polygon(nx, ny, self.polygon)


@dataclass
class Line:
    name: str
    p1: Point
    p2: Point


def parse_zones(raw: Optional[list]) -> List[Zone]:
    out = []
    for z in raw or []:
        poly = [tuple(map(float, p)) for p in z.get("polygon", [])]
        if len(poly) >= 3:
            out.append(Zone(str(z["name"]), z.get("type", "monitor"), poly))
    return out


def parse_lines(raw: Optional[list]) -> List[Line]:
    return [
        Line(str(l["name"]), tuple(map(float, l["p1"])), tuple(map(float, l["p2"])))
        for l in (raw or []) if "p1" in l and "p2" in l
    ]
