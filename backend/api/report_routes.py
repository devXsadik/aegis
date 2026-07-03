"""Incident report API routes."""

from fastapi import APIRouter, Depends, Query
from backend.auth.auth import operator_or_admin
from backend.models.user import User
from utils.data import ReportGenerator

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/incident")
def incident_report(
    hours: int = Query(default=24, ge=1, le=168),
    user: User = Depends(operator_or_admin),
):
    gen = ReportGenerator()
    try:
        return gen.generate_incident_report(hours=hours)
    finally:
        gen.close()


@router.get("/evidence-bundle")
def evidence_bundle(
    ids: str = Query(..., description="Comma-separated evidence IDs"),
    user: User = Depends(operator_or_admin),
):
    evidence_ids = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    gen = ReportGenerator()
    try:
        return gen.generate_evidence_bundle(evidence_ids)
    finally:
        gen.close()
