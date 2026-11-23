"""Governance: data-retention policy (Settings → Data retention) and the accuracy dashboard
(matches, confirmed vs rejected, false-positive rate per camera / alert type / model / score)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.auth import admin_only, operator_or_admin
from backend.db.database import get_db
from backend.models.alert import Alert
from backend.models.user import User
from backend.services.audit import log_audit
from backend.services.matching.common import load_json_config, save_json_config
from clock import utcnow

router = APIRouter(prefix="/governance", tags=["governance"])
IDENTIFICATION = ("CRIMINAL_DETECTED", "FACE_MATCH", "VEHICLE_MATCH", "LOOKOUT_MATCH", "SUSPICIOUS_VEHICLE")
RETENTION_KEY = "retention_policy"


class Retention(BaseModel):
    detection_days: int = Field(ge=1, le=365, description="Non-matched detections, plate reads, vehicle attributes")
    capture_days: int = Field(ge=1, le=365)
    recording_hours: int = Field(ge=1, le=24 * 90)
    evidence_image_days: int = Field(ge=1, le=3650, description="Detection images not on an open case")


def retention(db: Session) -> dict:
    import os
    cfg = load_json_config(db, RETENTION_KEY)
    return {"detection_days": int(cfg.get("detection_days") or os.getenv("DETECTION_RETENTION_DAYS", "30")),
            "capture_days": int(cfg.get("capture_days") or os.getenv("CAPTURE_RETENTION_DAYS", "14")),
            "recording_hours": int(cfg.get("recording_hours") or os.getenv("DVR_RETENTION_HOURS", "48")),
            "evidence_image_days": int(cfg.get("evidence_image_days") or 90),
            "case_evidence": "kept per legal rules: never deleted automatically (admin soft-delete only)"}


@router.get("/retention")
def get_retention(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    return retention(db)


@router.put("/retention")
def put_retention(body: Retention, request: Request, db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    save_json_config(db, RETENTION_KEY, body.model_dump(), admin.id)
    log_audit(db, admin, "RETENTION_POLICY", "config", RETENTION_KEY, json.dumps(body.model_dump()), request)
    db.commit()
    return retention(db)


def _bucket(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    lo = int(score * 10) / 10
    return f"{lo:.1f}–{lo + 0.1:.1f}"


@router.get("/accuracy")
def accuracy(days: int = 30, db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    if user.role not in ("admin", "supervisor", "auditor", "operator"):
        raise HTTPException(403, "Not allowed")
    since = utcnow() - timedelta(days=max(1, min(days, 365)))
    rows = db.query(Alert).filter(Alert.alert_type.in_(IDENTIFICATION), Alert.timestamp >= since).all()

    def blank():
        return {"matches": 0, "confirmed": 0, "rejected": 0, "pending": 0}

    total, by_type, by_cam, by_model, by_score = blank(), defaultdict(blank), defaultdict(blank), defaultdict(blank), defaultdict(blank)
    for a in rows:
        st = a.review_status if a.review_status in ("confirmed", "rejected") else "pending"
        try:
            d = json.loads(a.details) if a.details else {}
        except ValueError:
            d = {}
        model = (d.get("face") or {}).get("model") or ("vehicle-match" if d.get("match") else "pipeline")
        score = (d.get("face") or {}).get("similarity") or (d.get("match") or {}).get("score")
        for bucket in (total, by_type[a.alert_type], by_cam[a.camera_id or "?"], by_model[model]) + \
                ((by_score[_bucket(score)],) if score is not None else ()):
            bucket["matches"] += 1
            bucket[st] += 1

    def rate(b):
        decided = b["confirmed"] + b["rejected"]
        return {**b, "false_positive_rate": round(b["rejected"] / decided, 3) if decided else None}

    def table(d):
        return sorted(({"key": k, **rate(v)} for k, v in d.items()), key=lambda r: -r["matches"])

    return {"days": days, "total": rate(total), "by_type": table(by_type), "by_camera": table(by_cam),
            "by_model": table(by_model), "by_score": sorted(table(by_score), key=lambda r: r["key"])}
