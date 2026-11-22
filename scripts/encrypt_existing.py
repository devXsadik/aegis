#!/usr/bin/env python3
"""Encrypt images stored before encryption at rest was on (backend/utils/at_rest.py).

Evidence stills, capture stills and enrolment photos that are still plaintext are encrypted in
place; evidence gets an ENCRYPTED custody record (its content_sha256 is of the plaintext and
stays valid). Safe to run again: already encrypted rows are skipped. Back up first.

    python scripts/encrypt_existing.py --dry-run
    python scripts/encrypt_existing.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import SessionLocal, init_db  # noqa: E402
from backend.models.capture import AlertCapture  # noqa: E402
from backend.models.evidence import Evidence  # noqa: E402
from backend.models.person_image import PersonImage  # noqa: E402
from backend.services.custody import append_custody  # noqa: E402
from backend.utils.encryption import EncryptionManager  # noqa: E402


def main(dry_run: bool) -> dict:
    init_db()
    enc = EncryptionManager()
    db = SessionLocal()
    counts = {"evidence": 0, "captures": 0, "enrolment_photos": 0}
    try:
        for ev in db.query(Evidence).filter((Evidence.encrypted == False) | (Evidence.encrypted.is_(None))):  # noqa: E712
            if not (ev.frame_data or ev.roi_data):
                continue
            counts["evidence"] += 1
            if not dry_run:
                ev.frame_data = enc.encrypt(ev.frame_data) if ev.frame_data else None
                ev.roi_data = enc.encrypt(ev.roi_data) if ev.roi_data else None
                ev.encrypted = True
                append_custody(db, ev.id, "ENCRYPTED", actor="SYSTEM", details="encrypted at rest")
        for c in db.query(AlertCapture).filter(AlertCapture.encrypted == False):  # noqa: E712
            counts["captures"] += 1
            if not dry_run:
                c.image_data, c.encrypted = enc.encrypt(c.image_data), True
        for p in db.query(PersonImage).filter(PersonImage.encrypted == False):  # noqa: E712
            counts["enrolment_photos"] += 1
            if not dry_run:
                p.image_data, p.encrypted = enc.encrypt(p.image_data), True
        if not dry_run:
            db.commit()
    finally:
        db.close()
    return counts


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print(("Would encrypt: " if dry else "Encrypted: ") + ", ".join(f"{k} {v}" for k, v in main(dry).items()))
