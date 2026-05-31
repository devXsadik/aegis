from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from backend.db.database import get_db
from backend.auth.auth import operator_or_admin, admin_only
from backend.models.user import User
from backend.models.alert import Alert
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

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
