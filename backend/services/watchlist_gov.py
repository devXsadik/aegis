"""Watchlist governance, the same for people and vehicles.

An entry raises alerts only when ALL hold:
  * it carries a case / FIR / GD number, a legal basis and an issuing authority,
  * a second person (supervisor or admin, not the requester) approved it,
  * now is inside [starts_at, expires_at).
Expiry needs no job: matching checks the dates every time. `sweep` only relabels the status.
Editing a legal field of an active entry sends it back for approval."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Iterable, Optional, Set

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models.known_person import KnownPerson
from backend.models.user import User
from backend.models.watchlist import RISK_LEVELS, WatchlistVehicle
from backend.services.audit import log_audit
from clock import utcnow

COMMAND = ("admin", "supervisor")
PERSON_ALERT_STATUSES = ("wanted", "convicted", "suspect")
LEGAL_FIELDS = ("case_no", "legal_basis", "issuing_authority", "starts_at", "expires_at")
LEGACY_DAYS = 30


def max_days() -> int:
    try:
        return max(1, int(os.getenv("WATCHLIST_MAX_DAYS", "365")))
    except ValueError:
        return 365


class GovernanceError(ValueError):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def is_active(entry, now: Optional[datetime] = None) -> bool:
    now = now or utcnow()
    s, e = _naive(entry.starts_at), _naive(entry.expires_at)
    return entry.wl_status == "active" and s is not None and e is not None and s <= now < e


def effective_status(entry, now: Optional[datetime] = None) -> Optional[str]:
    """What the dashboard should show: 'scheduled' before start, 'expired' after the end."""
    now = now or utcnow()
    st = entry.wl_status
    if st == "active":
        if _naive(entry.expires_at) and _naive(entry.expires_at) <= now:
            return "expired"
        if _naive(entry.starts_at) and _naive(entry.starts_at) > now:
            return "scheduled"
    return st


def validate_legal(case_no, legal_basis, issuing_authority, starts_at, expires_at) -> None:
    missing = [n for n, v in (("case_no", case_no), ("legal_basis", legal_basis),
                              ("issuing_authority", issuing_authority), ("starts_at", starts_at),
                              ("expires_at", expires_at)) if not (str(v).strip() if v is not None else "")]
    if missing:
        raise GovernanceError(f"Required for a watchlist entry: {', '.join(missing)}")
    s, e = _naive(starts_at), _naive(expires_at)
    if e <= s:
        raise GovernanceError("expires_at must be after starts_at")
    if e <= utcnow():
        raise GovernanceError("expires_at is already in the past")
    if e - s > timedelta(days=max_days()):
        raise GovernanceError(f"An entry may last at most {max_days()} days; renew it with a new approval")
    if len(str(legal_basis).strip()) < 10:
        raise GovernanceError("legal_basis must say which law / order / warrant allows this (≥ 10 characters)")


def validate_risk(risk: Optional[str]) -> None:
    if risk is not None and risk not in RISK_LEVELS:
        raise GovernanceError(f"risk_level must be one of {', '.join(RISK_LEVELS)}")


def submit(entry, user: User, fields: dict) -> None:
    """Fill / change the legal fields and (re)submit for approval."""
    merged = {k: fields.get(k, getattr(entry, k, None)) for k in LEGAL_FIELDS}
    validate_legal(**merged)
    for k, v in fields.items():
        setattr(entry, k, _naive(v) if k in ("starts_at", "expires_at") else v)
    entry.wl_status = "pending"
    entry.requested_by, entry.requested_at = user.id, utcnow()
    entry.approved_by = entry.approved_at = None
    entry.decision_note = None
    entry.needs_review = False


def approve(entry, user: User, note: Optional[str] = None) -> None:
    if user.role not in COMMAND:
        raise GovernanceError("Only a supervisor or admin can approve", 403)
    if entry.wl_status != "pending":
        raise GovernanceError(f"Only a pending entry can be approved (this one is {entry.wl_status})", 409)
    if entry.requested_by is not None and entry.requested_by == user.id:
        raise GovernanceError("Second-person rule: the requester cannot approve their own entry", 403)
    validate_legal(entry.case_no, entry.legal_basis, entry.issuing_authority, entry.starts_at, entry.expires_at)
    entry.wl_status = "active"
    entry.approved_by, entry.approved_at = user.id, utcnow()
    entry.decision_note = note


def decide_against(entry, user: User, action: str, note: Optional[str]) -> None:
    """action = reject (pending) | revoke (active)."""
    if user.role not in COMMAND:
        raise GovernanceError(f"Only a supervisor or admin can {action}", 403)
    if not (note or "").strip():
        raise GovernanceError(f"A reason is required to {action}")
    want = "pending" if action == "reject" else "active"
    if entry.wl_status != want:
        raise GovernanceError(f"Only a {want} entry can be {action}ed", 409)
    entry.wl_status = "rejected" if action == "reject" else "revoked"
    entry.decision_note = note.strip()


def touches_legal(changes: Iterable[str]) -> bool:
    return any(k in LEGAL_FIELDS for k in changes)


# ——— Matching gates (used by the pipeline loaders and the alert dispatcher) ———

def _active_filter(model, now):
    return (model.wl_status == "active", model.starts_at <= now, model.expires_at > now)


def active_person_ids(db: Session, now: Optional[datetime] = None) -> Set[str]:
    now = now or utcnow()
    rows = (db.query(KnownPerson.person_id)
            .filter(KnownPerson.category == "criminal", KnownPerson.criminal_status.in_(PERSON_ALERT_STATUSES),
                    *_active_filter(KnownPerson, now)).all())
    return {r[0] for r in rows}


def person_may_alert(db: Session, person_id: str) -> bool:
    return person_id in active_person_ids(db)


def active_vehicles(db: Session, now: Optional[datetime] = None):
    now = now or utcnow()
    return db.query(WatchlistVehicle).filter(*_active_filter(WatchlistVehicle, now)).all()


def active_plates(db: Session) -> Set[str]:
    return {v.plate_canonical for v in active_vehicles(db) if v.plate_canonical}


def sweep(db: Session) -> int:
    """Relabel active entries past their expiry as 'expired' (and audit it)."""
    now = utcnow()
    n = 0
    for model, kind in ((KnownPerson, "person"), (WatchlistVehicle, "vehicle")):
        for e in db.query(model).filter(model.wl_status == "active", model.expires_at <= now).all():
            e.wl_status = "expired"
            ref = getattr(e, "person_id", None) or getattr(e, "ref", None)
            log_audit(db, None, "WATCHLIST_EXPIRED", f"watchlist_{kind}", ref, "expiry date reached")
            n += 1
    return n


ADOPTED_KEY = "watchlist.legacy_adopted"


def adopt_legacy(db: Session) -> int:
    """ONE TIME, on the first start with governance: entries that existed before it keep alerting
    for LEGACY_DAYS, flagged for review. Never again afterwards — otherwise a criminal enrolled
    later without approval would be activated by a restart."""
    from backend.models.config_entry import ConfigEntry
    if db.query(ConfigEntry).filter(ConfigEntry.key == ADOPTED_KEY).first():
        return 0
    db.add(ConfigEntry(key=ADOPTED_KEY, value=utcnow().isoformat()))
    now = utcnow()
    n = 1
    for p in db.query(KnownPerson).filter(
            KnownPerson.category == "criminal", KnownPerson.criminal_status.in_(PERSON_ALERT_STATUSES),
            or_(KnownPerson.wl_status.is_(None), KnownPerson.wl_status == "")).all():
        p.wl_status, p.needs_review = "active", True
        p.case_no = p.case_no or "LEGACY"
        p.issuing_authority = p.issuing_authority or "Pre-governance entry"
        p.legal_basis = p.legal_basis or "Legacy entry added before watchlist governance — review required"
        p.starts_at, p.expires_at = now, now + timedelta(days=LEGACY_DAYS)
        p.approved_at = now
        n += 1
    try:
        from backend.models.vehicle import LicensePlate
        from core.analysis.bd_plate import canonical
        from core.analysis.anpr import normalize_plate
        have = {v.plate_raw for v in db.query(WatchlistVehicle.plate_raw)}
        for lp in db.query(LicensePlate).filter(LicensePlate.watchlisted == True).all():  # noqa: E712
            if lp.plate_number in have:
                continue
            import uuid
            db.add(WatchlistVehicle(
                ref=f"V-{uuid.uuid4().hex[:8].upper()}", plate_raw=lp.plate_number,
                plate_canonical=canonical(lp.plate_number) or normalize_plate(lp.plate_number),
                notes=lp.reason, case_no="LEGACY", issuing_authority="Pre-governance entry",
                legal_basis="Legacy entry added before watchlist governance — review required",
                wl_status="active", needs_review=True, starts_at=now, expires_at=now + timedelta(days=LEGACY_DAYS),
                approved_at=now))
            n += 1
    except Exception:          # vehicle tables missing on a very old DB: people still migrate
        pass
    return n
