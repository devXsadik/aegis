"""Incident report API routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.services.audit import log_audit
from backend.auth.auth import get_current_user, operator_or_admin
from backend.models.user import User
from utils.data import ReportGenerator

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/incident")
def incident_report(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168),
    user: User = Depends(operator_or_admin),
    db: Session = Depends(get_db),
):
    log_audit(db, user, "REPORT_GENERATE", "report", "incident", f"hours={hours}", request)
    db.commit()
    gen = ReportGenerator()
    try:
        return gen.generate_incident_report(hours=hours)
    finally:
        gen.close()


@router.get("/evidence-bundle")
def evidence_bundle(
    request: Request,
    ids: str = Query(..., description="Comma-separated evidence IDs"),
    user: User = Depends(operator_or_admin),
    db: Session = Depends(get_db),
):
    evidence_ids = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    log_audit(db, user, "EVIDENCE_BUNDLE", "report", "bundle", f"ids={evidence_ids}", request)
    db.commit()
    gen = ReportGenerator()
    try:
        return gen.generate_evidence_bundle(evidence_ids)
    finally:
        gen.close()


# ——— command reports (response times, patterns, camera uptime) ———

REPORT_ROLES = {"admin", "supervisor", "operator", "auditor"}


def report_reader(user: User = Depends(get_current_user)) -> User:
    if user.role not in REPORT_ROLES:
        raise HTTPException(403, "Reports are for the command centre, supervisors and auditors")
    return user


def _scope(db: Session, jurisdiction_id: Optional[int], user: User):
    from backend.services import scope
    requested = None
    if jurisdiction_id is not None:
        from backend.services.jurisdiction import descendants
        requested = descendants(db, jurisdiction_id) or {jurisdiction_id}
    return scope.narrow(db, user, requested)


@router.get("/response-times")
def response_times(days: int = Query(30, ge=1, le=365), jurisdiction_id: Optional[int] = None,
                   db: Session = Depends(get_db), user: User = Depends(report_reader)):
    from backend.services import reports
    return reports.response_times(db, days, _scope(db, jurisdiction_id, user))


@router.get("/patterns")
def patterns(days: int = Query(30, ge=1, le=365), jurisdiction_id: Optional[int] = None,
             db: Session = Depends(get_db), user: User = Depends(report_reader)):
    from backend.services import reports
    return reports.patterns(db, days, _scope(db, jurisdiction_id, user))


@router.get("/camera-uptime")
def camera_uptime(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db), user: User = Depends(report_reader)):
    from backend.services import reports
    from backend.services import scope
    return reports.camera_uptime(db, days, scope.area_ids(db, user))
