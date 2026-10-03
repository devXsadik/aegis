from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import desc
from backend.db.database import get_db
from backend.auth.auth import operator_or_admin, admin_only
from backend.models.user import User
from backend.models.alert import Alert
from backend.services.alert_dispatcher import dispatch_alert, redispatch_alert
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import os

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertResponse(BaseModel):
    id: int
    timestamp: datetime
    alert_type: str
    severity: str
    camera_location: Optional[str]
    person_name: Optional[str]
    plate_number: Optional[str]
    message: Optional[str]
    acknowledged: bool
    dismissed: bool
    channels_sent: Optional[str]

    class Config:
        from_attributes = True


class AcknowledgeRequest(BaseModel):
    acknowledged: bool = True
    dismissed: bool = False


class DispatchAlertRequest(BaseModel):
    alert_type: str
    severity: str = "critical"
    camera_location: Optional[str] = None
    camera_id: Optional[str] = None
    track_id: Optional[int] = None
    person_name: Optional[str] = None
    plate_number: Optional[str] = None
    message: Optional[str] = None
    camera_name: Optional[str] = None
    camera_lat: Optional[float] = None
    camera_lng: Optional[float] = None


def _verify_internal_key(key: Optional[str]) -> None:
    expected = os.getenv("INTERNAL_API_KEY", "pipeline-internal-key-change-me")
    if not key or key != expected:
        raise HTTPException(status_code=401, detail="Invalid internal API key")


@router.post("/dispatch")
async def auto_dispatch_alert(
    body: DispatchAlertRequest,
    x_internal_key: Optional[str] = Header(default=None, alias="X-Internal-Key"),
):
    """
    Fully automated alert dispatch from pipeline (any camera).
    Saves DB + audit log + WebSocket + webhooks in one call.
    """
    _verify_internal_key(x_internal_key)
    result = await dispatch_alert(
        alert_type=body.alert_type,
        severity=body.severity,
        camera_location=body.camera_location,
        camera_id=body.camera_id,
        track_id=body.track_id,
        person_name=body.person_name,
        plate_number=body.plate_number,
        message=body.message,
        camera_name=body.camera_name,
        camera_lat=body.camera_lat,
        camera_lng=body.camera_lng,
    )
    return result


@router.get("/", response_model=List[AlertResponse])
def list_alerts(
    skip: int = 0,
    limit: int = 50,
    alert_type: Optional[str] = None,
    severity: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    dismissed: Optional[bool] = None,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    query = db.query(Alert)
    if alert_type:
        query = query.filter(Alert.alert_type == alert_type.upper())
    if severity:
        query = query.filter(Alert.severity == severity)
    if acknowledged is not None:
        query = query.filter(Alert.acknowledged == acknowledged)
    if dismissed is not None:
        query = query.filter(Alert.dismissed == dismissed)
    return query.order_by(desc(Alert.timestamp)).offset(skip).limit(limit).all()


@router.get("/unacknowledged", response_model=List[AlertResponse])
def unacknowledged_alerts(
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    return (
        db.query(Alert)
        .filter(Alert.acknowledged == False, Alert.dismissed == False)
        .order_by(desc(Alert.timestamp))
        .limit(100)
        .all()
    )


@router.get("/stats")
def alert_stats(
    hours: int = 24,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    total = db.query(Alert).filter(Alert.timestamp >= cutoff).count()
    unack = db.query(Alert).filter(Alert.timestamp >= cutoff, Alert.acknowledged == False).count()
    by_type = (
        db.query(Alert.alert_type, Alert.severity)
        .filter(Alert.timestamp >= cutoff)
        .all()
    )
    type_counts = {}
    for t, s in by_type:
        type_counts[t] = type_counts.get(t, 0) + 1
    return {
        "period_hours": hours,
        "total": total,
        "unacknowledged": unack,
        "by_type": type_counts,
    }


@router.put("/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: int,
    body: AcknowledgeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = body.acknowledged
    alert.dismissed = body.dismissed
    if body.acknowledged:
        alert.acknowledged_by = user.id
        alert.acknowledged_at = datetime.utcnow()
    db.commit()
    return {"status": "updated", "id": alert_id}


@router.post("/{alert_id}/dispatch")
async def dispatch_police(
    alert_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    """Operator-triggered police dispatch — reuses webhook channels + audit trail."""
    from backend.models.audit_log import AuditLog
    import json

    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    lat = lng = camera_name = None
    if alert.details:
        try:
            geo = json.loads(alert.details)
            lat, lng = geo.get("lat"), geo.get("lng")
            camera_name = geo.get("camera_name")
        except Exception:
            pass

    result = await redispatch_alert(
        alert,
        message=f"[MANUAL DISPATCH by {user.username}] {alert.message or alert.alert_type}",
        db=db,
    )
    alert.acknowledged = True
    alert.acknowledged_by = user.id
    alert.acknowledged_at = datetime.utcnow()
    db.add(AuditLog(
        user_id=user.id,
        username=user.username,
        action="MANUAL_DISPATCH",
        resource="alert",
        resource_id=str(alert_id),
        details=f"Police dispatched for alert {alert_id}",
    ))
    db.commit()
    return {"status": "dispatched", "alert_id": alert_id, "redispatch": result}


