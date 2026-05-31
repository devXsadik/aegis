from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.auth.auth import operator_or_admin, admin_only
from backend.models.user import User
from backend.models.evidence import Evidence
from backend.models.vehicle import VehicleDetection
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import json

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def get_analytics_summary(
    days: int = 7,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    evidence_query = db.query(Evidence).filter(Evidence.timestamp >= cutoff)
    total = evidence_query.count()
    criminals = evidence_query.filter(Evidence.is_criminal == True).count()
    weapons = evidence_query.filter(Evidence.weapon_present == True).count()
    suspicious = evidence_query.filter(Evidence.is_suspicious == True).count()

    vehicle_query = db.query(VehicleDetection).filter(VehicleDetection.timestamp >= cutoff)
    total_vehicles = vehicle_query.count()
    suspicious_vehicles = vehicle_query.filter(VehicleDetection.is_suspicious == True).count()

    # Alert stats from the alerts table
    from backend.models.alert import Alert
    total_alerts = db.query(Alert).filter(Alert.timestamp >= cutoff).count()
    unack_alerts = db.query(Alert).filter(
        Alert.timestamp >= cutoff, Alert.acknowledged == False, Alert.dismissed == False
    ).count()

    return {
        "period_days": days,
        "total_detections": total,
        "criminals_detected": criminals,
        "weapons_detected": weapons,
        "suspicious_activities": suspicious,
        "vehicles_detected": total_vehicles,
        "suspicious_vehicles": suspicious_vehicles,
        "alerts_sent": total_alerts,
        "alerts_unacknowledged": unack_alerts,
    }


@router.get("/hotspots/{camera_location}")
def get_hotspots(
    camera_location: str,
    hours: int = 24,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    detections = (
        db.query(Evidence)
        .filter(
            Evidence.camera_location == camera_location,
            Evidence.timestamp >= cutoff,
        )
        .all()
    )
    total = len(detections)
    location_counts: Dict[str, int] = {}
    for d in detections:
        loc = d.camera_location
        location_counts[loc] = location_counts.get(loc, 0) + 1

    hotspots = [
        {"location": loc, "count": count, "intensity": round(count / max(1, total), 2)}
        for loc, count in sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]
    return {"camera_location": camera_location, "period_hours": hours, "total_detections": total, "hotspots": hotspots}


@router.get("/timeline/{camera_location}")
def get_timeline(
    camera_location: str,
    hours: int = 24,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    detections = (
        db.query(Evidence)
        .filter(
            Evidence.camera_location == camera_location,
            Evidence.timestamp >= cutoff,
        )
        .order_by(Evidence.timestamp.asc())
        .all()
    )
    return [
        {
            "id": e.id,
            "timestamp": e.timestamp.isoformat(),
            "person_name": e.person_name,
            "is_criminal": e.is_criminal,
            "weapon_present": e.weapon_present,
            "is_suspicious": e.is_suspicious,
            "category": e.category,
        }
        for e in detections
    ]


@router.get("/trends")
def get_trends(
    days: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    detections = (
        db.query(Evidence)
        .filter(Evidence.timestamp >= cutoff)
        .order_by(Evidence.timestamp.asc())
        .all()
    )
    daily: Dict[str, dict] = {}
    for e in detections:
        day = e.timestamp.strftime("%Y-%m-%d") if e.timestamp else "unknown"
        if day not in daily:
            daily[day] = {"date": day, "total": 0, "criminal": 0, "weapon": 0, "suspicious": 0}
        daily[day]["total"] += 1
        if e.is_criminal:
            daily[day]["criminal"] += 1
        if e.weapon_present:
            daily[day]["weapon"] += 1
        if e.is_suspicious:
            daily[day]["suspicious"] += 1
    return {"trends": sorted(daily.values(), key=lambda x: x["date"])}
