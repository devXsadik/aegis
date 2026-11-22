from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import timedelta
from backend.db.database import get_db
from backend.models.user import User
from backend.models.evidence import Evidence
from backend.models.alert import Alert
from backend.auth.auth import operator_or_admin
from clock import utcnow

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def analytics_summary(hours: int = 24, db: Session = Depends(get_db),
                      user: User = Depends(operator_or_admin)):
    cutoff = utcnow() - timedelta(hours=hours)
    total_events = db.query(Evidence).filter(Evidence.timestamp >= cutoff).count()
    criminals = db.query(Evidence).filter(Evidence.timestamp >= cutoff, Evidence.is_criminal == True).count()
    weapons = db.query(Evidence).filter(Evidence.timestamp >= cutoff, Evidence.weapon_present == True).count()
    suspicious = db.query(Evidence).filter(Evidence.timestamp >= cutoff, Evidence.is_suspicious == True).count()
    alerts = db.query(Alert).filter(Alert.timestamp >= cutoff).count()
    # Mean time to acknowledge, from real timestamps (None until something has been acknowledged).
    acked = db.query(Alert.timestamp, Alert.acknowledged_at).filter(
        Alert.timestamp >= cutoff, Alert.acknowledged == True, Alert.acknowledged_at.isnot(None)).all()  # noqa: E712
    deltas = []
    for ts, at in acked:
        try:
            deltas.append((at.replace(tzinfo=None) - ts.replace(tzinfo=None)).total_seconds())
        except Exception:  # noqa: BLE001
            continue
    mtta = round(sum(deltas) / len(deltas), 1) if deltas else None
    return {
        "mtta_seconds": mtta,
        "acknowledged_alerts": len(deltas),
        "period_hours": hours,
        "total_events": total_events,
        "criminal_detections": criminals,
        "weapon_detections": weapons,
        "suspicious_activities": suspicious,
        "alerts_triggered": alerts,
    }


@router.get("/trends")
def analytics_trends(days: int = 7, db: Session = Depends(get_db),
                     user: User = Depends(operator_or_admin)):
    cutoff = utcnow() - timedelta(days=days)
    day = func.date(Evidence.timestamp)   # portable: CAST(.. AS DATE) breaks on SQLite
    results = (
        db.query(
            day.label("date"),
            func.count(Evidence.id).label("count"),
        )
        .filter(Evidence.timestamp >= cutoff)
        .group_by(day)
        .order_by("date")
        .all()
    )
    return [{"date": str(r.date), "events": r.count} for r in results]


@router.get("/locations")
def analytics_locations(hours: int = 24, db: Session = Depends(get_db),
                        user: User = Depends(operator_or_admin)):
    cutoff = utcnow() - timedelta(hours=hours)
    results = (
        db.query(
            Evidence.camera_location,
            func.count(Evidence.id).label("count"),
        )
        .filter(Evidence.timestamp >= cutoff)
        .group_by(Evidence.camera_location)
        .all()
    )
    return [{"location": r.camera_location, "events": r.count} for r in results]


@router.get("/live")
def analytics_live(user: User = Depends(operator_or_admin)):
  """Live pipeline analytics (heatmap summary, dwell, traffic) from last heartbeat."""
  from backend.api.system_routes import get_live_analytics
  return get_live_analytics()


# What a high false-detection rate on an alert type points at. Thresholds are system-wide (the
# pipeline reads one value); a step is suggested only for the ones it applies at runtime.
TUNING = {
    "WEAPON_DETECTED": ("weapon_conf_threshold", +0.05, "Weapon hits must be more certain"),
    "CRIMINAL_DETECTED": ("face_tolerance", -0.03, "Face matches must be closer"),
    "SUSPICIOUS_BEHAVIOR": ("loiter_seconds", +10, "People must stand still longer before it counts"),
    "ANOMALY_DETECTED": ("crowd_threshold", +2, "A crowd must be larger"),
}
ADVICE = {
    "INTRUSION": "Check the zone outline, or give the zone active hours (Zones page)",
    "OCCUPANCY_LIMIT": "Raise this zone's max people (Zones page)",
    "CAMERA_TAMPER": "This camera's view fools the tamper check (dark scene, moving camera): raise tamper thresholds in config.yaml",
    "FALL_SUSPECTED": "Raise action.min_confidence in config.yaml",
    "FIRE_SMOKE_DETECTED": "Steam, fog or bright lights in view: consider masking that area",
}
MIN_REVIEWED = 5            # no advice from fewer decisions than this
NOISY = 0.5                 # half or more of the reviewed alerts were false detections


@router.get("/false-alerts")
def false_alerts(days: int = 30, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    """Operators' decisions per camera and alert type: how often the detector was wrong, why,
    and what to change where it is wrong often. Only 'false detection' counts against the
    detector; known people, duplicates and tests are not detector mistakes."""
    from collections import Counter, defaultdict
    from backend.api.config_routes import THRESHOLD_SPECS, _effective_thresholds

    cutoff = utcnow() - timedelta(days=min(max(days, 1), 365))
    rows = (db.query(Alert.camera_id, Alert.camera_location, Alert.alert_type, Alert.review_status, Alert.review_note)
            .filter(Alert.timestamp >= cutoff, Alert.review_status.in_(["confirmed", "rejected"])).all())
    groups = defaultdict(lambda: {"confirmed": 0, "rejected": 0, "reasons": Counter()})
    names = {}
    for cam, loc, typ, status, note in rows:
        g = groups[(cam or loc or "?", typ)]
        names[cam or loc or "?"] = loc or cam
        g[status] += 1
        if status == "rejected":
            g["reasons"][(note or "other").split(":")[0].strip() or "other"] += 1

    current = _effective_thresholds(db)
    out = []
    for (cam, typ), g in groups.items():
        reviewed = g["confirmed"] + g["rejected"]
        false = g["reasons"].get("false_detection", 0)
        rate = false / reviewed if reviewed else 0.0
        item = {"camera_id": cam, "camera": names.get(cam) or cam, "alert_type": typ, "reviewed": reviewed,
                "confirmed": g["confirmed"], "rejected": g["rejected"], "false_detections": false,
                "false_rate": round(rate, 2), "reasons": dict(g["reasons"]), "suggestion": None}
        if reviewed >= MIN_REVIEWED and rate >= NOISY:
            if typ in TUNING:
                key, step, why = TUNING[typ]
                lo, hi, _ = THRESHOLD_SPECS[f"threshold.{key}"]
                now = float(current.get(key, THRESHOLD_SPECS[f"threshold.{key}"][2]))
                new = round(min(hi, max(lo, now + step)), 2)
                if new != now:
                    item["suggestion"] = {"key": key, "from": now, "to": new,
                                          "text": f"{why}: {key} {now} → {new} (applies to every camera)"}
            if not item["suggestion"] and typ in ADVICE:
                item["suggestion"] = {"text": ADVICE[typ]}
        out.append(item)
    out.sort(key=lambda i: (-i["false_rate"], -i["reviewed"]))
    return {"days": days, "min_reviewed": MIN_REVIEWED, "groups": out}
