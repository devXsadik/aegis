from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.auth.auth import verify_token, operator_or_admin, admin_only
from backend.models.user import User
from backend.models.evidence import Evidence
from backend.models.vehicle import VehicleDetection
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta

router = APIRouter(prefix="/analytics", tags=["analytics"])


class HeatmapRequest(BaseModel):
    camera_location: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class HeatmapResponse(BaseModel):
    hotspots: List[Dict]
    total_detections: int


class AnomalyResponse(BaseModel):
    type: str
    description: str
    severity: str
    location: Optional[str] = None


@router.get("/summary")
def get_analytics_summary(
    days: int = 1,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    """Get analytics summary for the last N days"""
    cutoff = datetime.utcnow() - timedelta(days=days)

    # Evidence stats
    evidence_query = db.query(Evidence).filter(Evidence.timestamp >= cutoff)
    total_evidence = evidence_query.count()
    criminals = evidence_query.filter(Evidence.is_criminal == True).count()
    weapons = evidence_query.filter(Evidence.weapon_present == True).count()
    suspicious = evidence_query.filter(Evidence.is_suspicious == True).count()

    # Vehicle stats
    vehicle_query = db.query(VehicleDetection).filter(
        VehicleDetection.timestamp >= cutoff
    )
    total_vehicles = vehicle_query.count()
    suspicious_vehicles = vehicle_query.filter(
        VehicleDetection.is_suspicious == True
    ).count()

    return {
        "period_days": days,
        "total_detections": total_evidence,
        "criminals_detected": criminals,
        "weapons_detected": weapons,
        "suspicious_activities": suspicious,
        "vehicles_detected": total_vehicles,
        "suspicious_vehicles": suspicious_vehicles,
        "alerts_sent": 0  # Would come from alert log
    }


@router.get("/hotspots/{camera_location}")
def get_hotspots(
    camera_location: str,
    hours: int = 24,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    """Get activity hotspots for a camera"""
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    detections = db.query(Evidence).filter(
        Evidence.camera_location == camera_location,
        Evidence.timestamp >= cutoff
    ).all()

    # Aggregate by position (simplified)
    location_counts = {}
    for d in detections:
        key = d.camera_location
        location_counts[key] = location_counts.get(key, 0) + 1

    hotspots = [
        {"location": loc, "count": count, "intensity": count / max(1, total)}
        for loc, count in sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    return {
        "camera_location": camera_location,
        "period_hours": hours,
        "total_detections": len(detections),
        "hotspots": hotspots
    }


@router.get("/anomalies/{camera_location}")
def detect_anomalies(
    camera_location: str,
    user: User = Depends(operator_or_admin)
):
    """Detect anomalies for a camera location"""
    # This would use the AnomalyDetector from core
    # For now, return a placeholder
    return {
        "camera_location": camera_location,
        "anomalies": [],
        "message": "Anomaly detection running"
    }


@router.get("/movement-patterns")
def get_movement_patterns(
    person_name: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    """Get movement patterns for persons across cameras"""
    query = db.query(Evidence)
    if person_name:
        query = query.filter(Evidence.person_name == person_name)

    # Group by person and analyze
    persons = {}
    for e in query.all():
        if e.person_name not in persons:
            persons[e.person_name] = []
        persons[e.person_name].append({
            "location": e.camera_location,
            "timestamp": e.timestamp.isoformat()
        })

    return {
        "patterns": [
            {
                "person": name,
                "detection_count": len(locations),
                "locations": list(set(l["location"] for l in locations))
            }
            for name, locations in persons.items()
        ]
    }
