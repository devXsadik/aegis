"""Travel time from officers to an incident.

OSRM_URL (e.g. http://osrm:5000, an OSRM server built from OpenStreetMap Bangladesh) gives real
road times: one /table request for all officers. Without it, or if it does not answer within
OSRM_TIMEOUT seconds, the estimate is straight-line distance × ROUTE_DETOUR (1.4: city roads are
rarely straight) at ROUTE_SPEED_KMH (20: Dhaka traffic). Both say which one they are.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Optional, Tuple

from backend.services import geo

logger = logging.getLogger(__name__)
Point = Tuple[float, float]          # (lat, lng)


def estimate_s(meters: float) -> float:
    detour = float(os.getenv("ROUTE_DETOUR", "1.4"))
    speed = float(os.getenv("ROUTE_SPEED_KMH", "20")) / 3.6
    return meters * detour / max(speed, 0.1)


def _osrm(dest: Point, origins: Dict[int, Point]) -> Optional[Dict[int, Tuple[float, float]]]:
    base = os.getenv("OSRM_URL", "").rstrip("/")
    if not base or not origins:
        return None
    import requests
    ids = list(origins)
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in [dest, *(origins[i] for i in ids)])
    try:
        r = requests.get(f"{base}/table/v1/driving/{coords}",
                         params={"destinations": "0", "sources": ";".join(str(k + 1) for k in range(len(ids))),
                                 "annotations": "duration,distance"},
                         timeout=float(os.getenv("OSRM_TIMEOUT", "2")))
        r.raise_for_status()
        body = r.json()
        if body.get("code") != "Ok":
            raise ValueError(body.get("code"))
    except Exception as e:  # noqa: BLE001 - fall back to the estimate
        logger.warning("OSRM unavailable, using straight-line estimates: %s", e)
        return None
    out = {}
    for i, uid in enumerate(ids):
        dur, dist = body["durations"][i][0], (body.get("distances") or [[None]] * len(ids))[i][0]
        if dur is not None:
            out[uid] = (float(dur), float(dist) if dist is not None else None)
    return out


def etas(dest: Point, origins: Dict[int, Point]) -> Dict[int, dict]:
    """user id → {eta_s, route_m, eta_source: road | estimate}."""
    road = _osrm(dest, origins) or {}
    out = {}
    for uid, (lat, lng) in origins.items():
        if uid in road:
            dur, dist = road[uid]
            out[uid] = {"eta_s": round(dur), "route_m": round(dist) if dist is not None else None, "eta_source": "road"}
        else:
            out[uid] = {"eta_s": round(estimate_s(geo.haversine_m(dest[0], dest[1], lat, lng))), "route_m": None,
                        "eta_source": "estimate"}
    return out
