from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from backend.db.database import get_db
from backend.models.user import User
from backend.models.evidence import Evidence
from backend.models.alert import Alert
from backend.auth.auth import operator_or_admin

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def analytics_summary(hours: int = 24, db: Session = Depends(get_db),
                      user: User = Depends(operator_or_admin)):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    total_events = db.query(Evidence).filter(Evidence.timestamp >= cutoff).count()
    criminals = db.query(Evidence).filter(Evidence.timestamp >= cutoff, Evidence.is_criminal == True).count()
    weapons = db.query(Evidence).filter(Evidence.timestamp >= cutoff, Evidence.weapon_present == True).count()
    suspicious = db.query(Evidence).filter(Evidence.timestamp >= cutoff, Evidence.is_suspicious == True).count()
    alerts = db.query(Alert).filter(Alert.timestamp >= cutoff).count()
    return {
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
    cutoff = datetime.utcnow() - timedelta(days=days)
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
    cutoff = datetime.utcnow() - timedelta(hours=hours)
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
