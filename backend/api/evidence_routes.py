from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import desc
from backend.db.database import get_db
from backend.models.evidence import Evidence
from backend.auth.auth import operator_or_admin, admin_only
from backend.models.user import User
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

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
    has_frame: bool = False
    has_roi: bool = False

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
    records = query.order_by(desc(Evidence.timestamp)).offset(skip).limit(limit).all()
    # Attach has_frame / has_roi flags
    for r in records:
        r.has_frame = bool(r.frame_data)
        r.has_roi = bool(r.roi_data)
    return records


@router.get("/{evidence_id}", response_model=EvidenceResponse)
def get_evidence(
    evidence_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    evidence.has_frame = bool(evidence.frame_data)
    evidence.has_roi = bool(evidence.roi_data)
    return evidence


@router.get("/{evidence_id}/frame")
def get_evidence_frame(
    evidence_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    """Serve the CCTV frame image stored in DB for this evidence record."""
    evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if not evidence.frame_data:
        raise HTTPException(status_code=404, detail="No frame image stored for this evidence")
    return Response(content=evidence.frame_data, media_type="image/jpeg")


@router.get("/{evidence_id}/roi")
def get_evidence_roi(
    evidence_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    """Serve the ROI (person crop) image stored in DB for this evidence record."""
    evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if not evidence.roi_data:
        raise HTTPException(status_code=404, detail="No ROI image stored for this evidence")
    return Response(content=evidence.roi_data, media_type="image/jpeg")


@router.get("/{evidence_id}/report")
def generate_evidence_report(
    evidence_id: int,
    format: str = "json",
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    """Generate an incident report for this evidence record."""
    from utils.reports import generate_report
    path = generate_report(evidence_id, format=format)
    if path == "Evidence not found":
        raise HTTPException(status_code=404, detail=path)
    if format == "pdf" and path.endswith(".pdf"):
        from fastapi.responses import FileResponse
        return FileResponse(path, media_type="application/pdf", filename=f"evidence_{evidence_id}.pdf")
    return {"status": "report_generated", "path": path}


@router.get("/export/bundle")
def export_evidence_bundle(
    evidence_ids: str,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin),
):
    """Export multiple evidence records as a bundle. evidence_ids: comma-separated."""
    from utils.reports import ReportGenerator
    ids = [int(x.strip()) for x in evidence_ids.split(",") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(status_code=400, detail="No valid evidence IDs provided")
    gen = ReportGenerator()
    path = gen.create_evidence_bundle(incident_id=f"bulk_{ids[0]}", evidence_ids=ids)
    return {"status": "bundle_created", "path": path, "evidence_count": len(ids)}


@router.delete("/retention/run")
def run_retention_policy(
    dry_run: bool = True,
    user: User = Depends(admin_only),
):
    """Run evidence retention policy (admin only). Set dry_run=false to actually delete."""
    from utils.retention import run_retention
    result = run_retention(dry_run=dry_run)
    return result
