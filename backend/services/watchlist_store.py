"""DB-backed loaders injected into the CV pipeline (keeps `core` free of backend imports)."""

import logging
from typing import List, Set, Tuple

import numpy as np

from backend.db.database import SessionLocal
from backend.models.face_encoding import FaceEncoding
from backend.models.known_person import KnownPerson  # noqa: F401  (mapper for FaceEncoding.person)

logger = logging.getLogger("HumanAnalysis")

ALERT_STATUSES = ("wanted", "convicted", "suspect")


def load_face_encodings() -> Tuple[List[np.ndarray], List[str]]:
    db = SessionLocal()
    try:
        encodings, names = [], []
        for rec in db.query(FaceEncoding).all():
            enc = FaceEncoding.deserialize_encoding(rec.encoding)
            if enc.size > 0:
                encodings.append(enc)
                names.append(rec.person.person_id)
        return encodings, names
    finally:
        db.close()


def load_watchlisted_plates() -> Set[str]:
    """Canonical plates of approved, unexpired vehicle watchlist entries (watchlist_gov)."""
    from backend.services.watchlist_gov import active_plates
    db = SessionLocal()
    try:
        return active_plates(db)
    finally:
        db.close()


def load_criminal_ids() -> Set[str]:
    """Approved, unexpired criminal watchlist entries. Everyone else stays enrolled (still
    recognised, so lookalikes are suppressed) but raises no alert."""
    from backend.services.watchlist_gov import active_person_ids
    db = SessionLocal()
    try:
        return active_person_ids(db)
    finally:
        db.close()
