from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from backend.db.database import get_db
from backend.models.evidence import Evidence
from backend.auth.auth import operator_or_admin, admin_only
from backend.models.user import User
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

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
    reasons: Optional[str]
    category: str
    encrypted: bool

    class Config:
        orm_mode = True


@router.get("/", response_model=list[EvidenceResponse])
def list_evidence(
    skip: int = 0,
    limit: int = 100,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    query = db.query(Evidence)
    if category:
        query = query.filter(Evidence.category == category)
    return query.order_by(desc(Evidence.timestamp)).offset(skip).limit(limit).all()


@router.get("/{evidence_id}", response_model=EvidenceResponse)
def get_evidence(
    evidence_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return evidence
