"""Zone geometry: polygons and counting lines in normalized (0-1) coordinates.

Normalized coordinates keep zone definitions valid across resolutions.
cameras.yaml example:

    zones:
      - {name: door, type: restricted, polygon: [[0.1,0.2],[0.4,0.2],[0.4,0.9],[0.1,0.9]],
         schedule: {days: [0,1,2,3,4], start: "19:00", end: "07:00"}}   # armed weeknights only
      - {name: lobby, type: monitor, polygon: [[0.4,0.1],[0.9,0.1],[0.9,0.9],[0.4,0.9]],
         max_people: 12}                                                 # occupancy limit

`schedule` (optional): when the zone raises alerts — days 0=Monday..6=Sunday, local time of
the pipeline computer, `end` before `start` runs past midnight (the night belongs to the day it
started). Without it the zone is always armed. People are counted either way.
    lines:
      - {name: entrance, p1: [0.5,0.0], p2: [0.5,1.0]}
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
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


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def schedule_active(schedule: Optional[dict], when: datetime) -> bool:
    """Is `when` (local time) inside the schedule? No schedule = always."""
    if not schedule:
        return True
    days = set(schedule.get("days", range(7)))
    start, end = _minutes(schedule["start"]), _minutes(schedule["end"])
    now = when.hour * 60 + when.minute
    today = when.weekday()
    if start < end:                                   # same-day window, e.g. 09:00-17:00
        return today in days and start <= now < end
    # Overnight, e.g. 19:00-07:00: the evening part belongs to today, the morning to yesterday.
    return (today in days and now >= start) or ((today - 1) % 7 in days and now < end)


@dataclass
class Zone:
    name: str
    type: str = "monitor"            # monitor | restricted
    polygon: List[Point] = field(default_factory=list)
    schedule: Optional[dict] = None  # when the zone raises alerts (see module docstring)
    max_people: Optional[int] = None # occupancy limit: an alert when more people are inside

    def contains(self, nx: float, ny: float) -> bool:
        return point_in_polygon(nx, ny, self.polygon)

    def armed(self, ts: float) -> bool:
        return schedule_active(self.schedule, datetime.fromtimestamp(ts))


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
            out.append(Zone(str(z["name"]), z.get("type", "monitor"), poly,
                            z.get("schedule") or None, z.get("max_people") or None))
    return out


def parse_lines(raw: Optional[list]) -> List[Line]:
    return [
        Line(str(l["name"]), tuple(map(float, l["p1"])), tuple(map(float, l["p2"])))
        for l in (raw or []) if "p1" in l and "p2" in l
    ]


MAX_ZONES = 20
MAX_LINES = 10
MAX_POINTS = 40
ZONE_TYPES = ("monitor", "restricted")


def _point(p, where: str):
    try:
        x, y = float(p[0]), float(p[1])
    except (TypeError, ValueError, IndexError):
        raise ValueError(f"{where}: points must be [x, y] numbers")
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError(f"{where}: coordinates must be between 0 and 1")
    return [round(x, 4), round(y, 4)]


def _polygon_area(poly) -> float:
    a = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _schedule(raw, name: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"{name}: schedule must have days, start and end")
    days = raw.get("days")
    if not isinstance(days, list) or not days or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
        raise ValueError(f"{name}: pick at least one day for the active hours")
    start, end = str(raw.get("start", "")), str(raw.get("end", ""))
    if not (_HHMM.match(start) and _HHMM.match(end)):
        raise ValueError(f"{name}: active hours must be times like 19:00")
    if start == end:
        raise ValueError(f"{name}: active hours start and end at the same time")
    return {"days": sorted(set(days)), "start": start, "end": end}


def validate_geometry(zones, lines) -> dict:
    """Return a cleaned {zones, lines} dict or raise ValueError with a readable message."""
    zones = zones or []
    lines = lines or []
    if len(zones) > MAX_ZONES:
        raise ValueError(f"At most {MAX_ZONES} zones per camera")
    if len(lines) > MAX_LINES:
        raise ValueError(f"At most {MAX_LINES} lines per camera")

    names = set()
    out_zones = []
    for z in zones:
        name = str(z.get("name", "")).strip()
        if not name or len(name) > 50:
            raise ValueError("Every zone needs a name (1-50 characters)")
        if name.lower() in names:
            raise ValueError(f"Duplicate name: {name}")
        names.add(name.lower())
        ztype = z.get("type", "monitor")
        if ztype not in ZONE_TYPES:
            raise ValueError(f"{name}: type must be one of {', '.join(ZONE_TYPES)}")
        pts = z.get("polygon") or []
        if not 3 <= len(pts) <= MAX_POINTS:
            raise ValueError(f"{name}: a zone needs 3-{MAX_POINTS} points")
        poly = [_point(p, name) for p in pts]
        if _polygon_area(poly) < 0.0005:
            raise ValueError(f"{name}: zone is too small or its points are in a straight line")
        zone = {"name": name, "type": ztype, "polygon": poly}
        if z.get("schedule"):
            zone["schedule"] = _schedule(z["schedule"], name)
        if z.get("max_people") not in (None, "", 0):
            try:
                limit = int(z["max_people"])
            except (TypeError, ValueError):
                raise ValueError(f"{name}: max people must be a whole number")
            if not 1 <= limit <= 500:
                raise ValueError(f"{name}: max people must be between 1 and 500")
            zone["max_people"] = limit
        out_zones.append(zone)

    out_lines = []
    for l in lines:
        name = str(l.get("name", "")).strip()
        if not name or len(name) > 50:
            raise ValueError("Every line needs a name (1-50 characters)")
        if name.lower() in names:
            raise ValueError(f"Duplicate name: {name}")
        names.add(name.lower())
        p1, p2 = _point(l.get("p1"), name), _point(l.get("p2"), name)
        if p1 == p2:
            raise ValueError(f"{name}: line start and end are the same point")
        out_lines.append({"name": name, "p1": p1, "p2": p2})
    return {"zones": out_zones, "lines": out_lines}
