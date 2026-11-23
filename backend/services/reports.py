"""Command reports: how fast incidents are answered, where and when they happen, camera uptime.

All three read only what the system already records (incident timeline events, alerts), so they
are correct for past data too. Times of day are in REPORT_TZ (default Asia/Dhaka).
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.models.alert import Alert
from backend.models.camera import Camera
from backend.models.incident import Incident, IncidentEvent
from backend.models.jurisdiction import Jurisdiction
from clock import utcnow

ACK_STATES = {"acknowledged", "en_route", "on_scene", "located"}
ARRIVE_STATES = {"on_scene", "located"}
STAGES = ("dispatch", "acknowledge", "arrive", "resolve")


def _tz():
    return ZoneInfo(os.getenv("REPORT_TZ", "Asia/Dhaka"))


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _pct(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def _summ(values: List[float]) -> dict:
    return {"n": len(values), "median_s": round(median(values), 1) if values else None, "p90_s": _pct(values, 0.9)}


def _incidents(db: Session, since: datetime, jurisdiction_ids: Optional[Iterable[int]]):
    q = db.query(Incident).filter(Incident.created_at >= since)
    if jurisdiction_ids is not None:
        q = q.filter(Incident.jurisdiction_id.in_(list(jurisdiction_ids)))
    return q.all()


def _names(db: Session) -> Dict[int, str]:
    return {j.id: j.name_en for j in db.query(Jurisdiction.id, Jurisdiction.name_en)}


def stage_times(inc: Incident, events: List[IncidentEvent]) -> Dict[str, Optional[float]]:
    """Seconds from the incident opening to: first dispatch, first officer acknowledgement, first
    officer on scene, resolution. None when that step has not happened."""
    t0 = _aware(inc.created_at)
    first: Dict[str, datetime] = {}
    for ev in sorted(events, key=lambda e: _aware(e.created_at) or t0):
        at = _aware(ev.created_at)
        if at is None:
            continue
        state = None
        if ev.event_type == "OFFICER_STATE" and ev.payload:
            try:
                state = json.loads(ev.payload).get("state")
            except ValueError:
                state = None
        elif ev.event_type.startswith("RESPONDER_"):
            state = ev.event_type[len("RESPONDER_"):].lower()
        if ev.event_type == "ASSIGNED" and "Case owner" not in (ev.message or ""):
            first.setdefault("dispatch", at)
        if state in ACK_STATES:
            first.setdefault("acknowledge", at)
        if state in ARRIVE_STATES:
            first.setdefault("arrive", at)
    if inc.resolved_at:
        first["resolve"] = _aware(inc.resolved_at)
    return {s: (max(0.0, (first[s] - t0).total_seconds()) if s in first and t0 else None) for s in STAGES}


def response_times(db: Session, days: int = 30, jurisdiction_ids: Optional[Iterable[int]] = None) -> dict:
    since = utcnow() - timedelta(days=days)
    incs = _incidents(db, since, jurisdiction_ids)
    by_inc: Dict[int, List[IncidentEvent]] = defaultdict(list)
    if incs:
        for ev in db.query(IncidentEvent).filter(IncidentEvent.incident_id.in_([i.id for i in incs])):
            by_inc[ev.incident_id].append(ev)
    overall: Dict[str, List[float]] = defaultdict(list)
    by_area: Dict[Optional[int], Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    by_prio: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    counts: Dict[Optional[int], int] = Counter()
    for inc in incs:
        counts[inc.jurisdiction_id] += 1
        for stage, sec in stage_times(inc, by_inc[inc.id]).items():
            if sec is None:
                continue
            overall[stage].append(sec)
            by_area[inc.jurisdiction_id][stage].append(sec)
            by_prio[inc.priority or "medium"][stage].append(sec)
    names = _names(db)
    areas = [{"jurisdiction_id": jid, "name": names.get(jid, "Not mapped") if jid else "Not mapped",
              "incidents": counts[jid], **{s: _summ(by_area[jid][s]) for s in STAGES}}
             for jid in counts]
    areas.sort(key=lambda a: (a["arrive"]["median_s"] is None, -(a["arrive"]["median_s"] or 0)))
    return {"days": days, "incidents": len(incs), "overall": {s: _summ(overall[s]) for s in STAGES},
            "by_priority": {p: {s: _summ(v[s]) for s in STAGES} for p, v in by_prio.items()},
            "by_area": areas}


def patterns(db: Session, days: int = 30, jurisdiction_ids: Optional[Iterable[int]] = None) -> dict:
    """Incidents by weekday × hour (local time), per area with the change against the previous
    period of the same length, and the most common incident types."""
    now = utcnow()
    since, prev_since = now - timedelta(days=days), now - timedelta(days=2 * days)
    tz = _tz()
    cur = _incidents(db, since, jurisdiction_ids)
    prev = [i for i in _incidents(db, prev_since, jurisdiction_ids) if _aware(i.created_at) < _aware(since)]
    grid = [[0] * 24 for _ in range(7)]                     # [weekday Mon=0][hour]
    for inc in cur:
        local = _aware(inc.created_at).astimezone(tz)
        grid[local.weekday()][local.hour] += 1
    names = _names(db)
    c_now, c_prev = Counter(i.jurisdiction_id for i in cur), Counter(i.jurisdiction_id for i in prev)
    areas = [{"jurisdiction_id": jid, "name": names.get(jid, "Not mapped") if jid else "Not mapped",
              "incidents": c_now[jid], "previous": c_prev[jid],
              "change_pct": round((c_now[jid] - c_prev[jid]) / c_prev[jid] * 100) if c_prev[jid] else None}
             for jid in set(c_now) | set(c_prev)]
    areas.sort(key=lambda a: -a["incidents"])
    peak = max(((d, h, grid[d][h]) for d in range(7) for h in range(24)), key=lambda t: t[2], default=(0, 0, 0))
    return {"days": days, "timezone": str(tz), "incidents": len(cur), "previous": len(prev), "grid": grid,
            "peak": {"weekday": peak[0], "hour": peak[1], "count": peak[2]} if peak[2] else None,
            "by_area": areas,
            "by_type": [{"type": t, "count": n} for t, n in Counter(i.incident_type for i in cur).most_common(8)]}


def camera_uptime(db: Session, days: int = 7, jurisdiction_ids: Optional[Iterable[int]] = None) -> dict:
    """Per camera: share of the period it was reporting, from the CAMERA_OFFLINE / CAMERA_RESTORED
    alerts the health watch raises (an outage still open counts until now)."""
    now = utcnow()
    since = now - timedelta(days=days)
    period = (now - since).total_seconds()
    rows = (db.query(Alert.camera_id, Alert.alert_type, Alert.timestamp)
            .filter(Alert.alert_type.in_(("CAMERA_OFFLINE", "CAMERA_RESTORED")), Alert.timestamp >= since - timedelta(days=1))
            .order_by(Alert.timestamp).all())
    events: Dict[str, list] = defaultdict(list)
    for cam, kind, ts in rows:
        if cam:
            events[cam].append((kind, _aware(ts)))
    cq = db.query(Camera.camera_id, Camera.name, Camera.location, Camera.active)
    if jurisdiction_ids is not None:
        cq = cq.filter(Camera.jurisdiction_id.in_(list(jurisdiction_ids)))
    cams = cq.all()
    out = []
    since_a, now_a = _aware(since), _aware(now)
    for cam_id, name, location, active in cams:
        down, started, outages, longest = 0.0, None, 0, 0.0
        for kind, ts in events.get(cam_id, []):
            if kind == "CAMERA_OFFLINE" and started is None:
                started = ts
            elif kind == "CAMERA_RESTORED" and started is not None:
                a, b = max(started, since_a), min(ts, now_a)
                if b > a:
                    down += (b - a).total_seconds()
                    outages += 1
                    longest = max(longest, (b - started).total_seconds())
                started = None
        open_now = started is not None
        if open_now:
            a = max(started, since_a)
            down += (now_a - a).total_seconds()
            outages += 1
            longest = max(longest, (now_a - started).total_seconds())
        out.append({"camera_id": cam_id, "name": name or cam_id, "location": location, "active": bool(active),
                    "uptime_pct": round(max(0.0, 100 * (1 - down / period)), 2), "outages": outages,
                    "downtime_s": round(down), "longest_outage_s": round(longest), "down_now": open_now})
    out.sort(key=lambda c: c["uptime_pct"])
    fleet = [c["uptime_pct"] for c in out if c["active"]]
    return {"days": days, "cameras": out, "fleet_uptime_pct": round(sum(fleet) / len(fleet), 2) if fleet else None}
