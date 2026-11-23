"""Small geometry helpers: GeoJSON point-in-polygon, distance, bearing, compass direction.
No GIS dependency, so it runs the same on SQLite and Postgres."""

from __future__ import annotations

import json
import math
from typing import Iterable, Optional, Sequence, Tuple

EARTH_M = 6_371_000.0
COMPASS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north [0, 360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass8(deg: float) -> str:
    return COMPASS_8[int(((deg % 360) + 22.5) // 45) % 8]


def angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, 0..180."""
    d = abs((a - b) % 360)
    return 360 - d if d > 180 else d


def _ring_contains(ring: Sequence[Sequence[float]], lng: float, lat: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def _polygons(geom: dict) -> Iterable[list]:
    t = geom.get("type")
    if t == "Feature":
        yield from _polygons(geom.get("geometry") or {})
    elif t == "FeatureCollection":
        for f in geom.get("features", []):
            yield from _polygons(f)
    elif t == "Polygon":
        yield geom["coordinates"]
    elif t == "MultiPolygon":
        yield from geom["coordinates"]


def parse(geojson) -> Optional[dict]:
    if not geojson:
        return None
    if isinstance(geojson, dict):
        return geojson
    try:
        return json.loads(geojson)
    except (TypeError, ValueError):
        return None


def contains(geojson, lat: float, lng: float) -> bool:
    """True if (lat, lng) is inside the (Multi)Polygon / Feature(Collection). Holes respected."""
    geom = parse(geojson)
    if not geom or lat is None or lng is None:
        return False
    for poly in _polygons(geom):
        if poly and _ring_contains(poly[0], lng, lat) and not any(_ring_contains(h, lng, lat) for h in poly[1:]):
            return True
    return False


def centroid(geojson) -> Optional[Tuple[float, float]]:
    """Mean of the outer-ring vertices (good enough to measure distance to an area). (lat, lng)."""
    geom = parse(geojson)
    if not geom:
        return None
    pts = [p for poly in _polygons(geom) if poly for p in poly[0][:-1] or poly[0]]
    if not pts:
        return None
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def valid_polygon(geojson) -> bool:
    geom = parse(geojson)
    if not geom:
        return False
    try:
        polys = list(_polygons(geom))
    except (KeyError, TypeError):
        return False
    return bool(polys) and all(
        poly and len(poly[0]) >= 4 and all(len(p) >= 2 and -180 <= p[0] <= 180 and -90 <= p[1] <= 90 for p in poly[0])
        for poly in polys)
