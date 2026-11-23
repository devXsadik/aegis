"""District / area administration. A user with scope_jurisdiction_id works inside that area and the
areas under it: incidents, reports and (for admins) user accounts outside it are not visible to
them. Unscoped users are national. Police are scoped by their own jurisdictions as before."""

from __future__ import annotations

from typing import Optional, Set

from sqlalchemy.orm import Session

from backend.models.jurisdiction import OfficerJurisdiction
from backend.models.user import User


def area_ids(db: Session, user: User) -> Optional[Set[int]]:
    """Area ids this user is limited to, or None for national users."""
    jid = getattr(user, "scope_jurisdiction_id", None)
    if not jid:
        return None
    from backend.services.jurisdiction import descendants
    return descendants(db, jid) or {jid}


def within(db: Session, user: User, jurisdiction_id: Optional[int]) -> bool:
    areas = area_ids(db, user)
    return areas is None or (jurisdiction_id is not None and jurisdiction_id in areas)


def user_in_scope(db: Session, admin: User, target: User) -> bool:
    """May this (possibly district) admin see / manage `target`?"""
    areas = area_ids(db, admin)
    if areas is None:
        return True
    if target.scope_jurisdiction_id in areas:
        return True
    linked = {j for (j,) in db.query(OfficerJurisdiction.jurisdiction_id).filter(OfficerJurisdiction.user_id == target.id)}
    return bool(linked) and target.scope_jurisdiction_id is None and linked <= areas


def narrow(db: Session, user: User, requested: Optional[Set[int]]) -> Optional[Set[int]]:
    """Intersect a requested set of areas (None = all) with the user's scope."""
    areas = area_ids(db, user)
    if areas is None:
        return requested
    return areas if requested is None else (requested & areas)
