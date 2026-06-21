from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from backend.db.database import get_db
from backend.models.evidence import Evidence
from backend.models.user import User
from backend.auth.auth import operator_or_admin, admin_only

router = APIRouter(prefix="/evidence", tags=["evidence"])


class EvidenceResponse(BaseModel):
    id: int
    timestamp: datetime
    camera_location: str
    track_id: int
    person_name: Optional[str]
    is_criminal: bool
    weapon_present: bool
    is_suspicious: bool
    category: str
    reasons: Optional[str]

    class Config:
        from_attributes = True


@router.get("/", response_model=List[EvidenceResponse])
def list_evidence(
    skip: int = 0, limit: int = 50,
    category: Optional[str] = None,
    camera_location: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    query = db.query(Evidence)
    if category:
        query = query.filter(Evidence.category == category)
    if camera_location:
        query = query.filter(Evidence.camera_location == camera_location)
    return query.order_by(desc(Evidence.timestamp)).offset(skip).limit(limit).all()


@router.get("/{evidence_id}")
def get_evidence(evidence_id: int, db: Session = Depends(get_db),
                 user: User = Depends(operator_or_admin)):
    ev = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return ev


@router.delete("/{evidence_id}")
def delete_evidence(evidence_id: int, db: Session = Depends(get_db),
                    admin: User = Depends(admin_only)):
    ev = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    db.delete(ev)
    db.commit()
    return {"status": "deleted"}
