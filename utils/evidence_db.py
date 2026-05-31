import cv2
import numpy as np
from datetime import datetime
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.models.evidence import Evidence
from backend.utils.audit import AuditLogger
from backend.utils.encryption import EncryptionManager
from dotenv import load_dotenv

load_dotenv()

_enc_mgr = None


def _get_encryption_manager():
    global _enc_mgr
    if _enc_mgr is None:
        _enc_mgr = EncryptionManager()
    return _enc_mgr


def _encode_image_to_bytes(image) -> bytes:
    """Encode a numpy frame to JPEG bytes in-memory (no disk write)."""
    if image is None:
        return b""
    success, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not success:
        return b""
    return buffer.tobytes()


def save_evidence_db(
    camera_location: str,
    track_id: int,
    name: str,
    is_criminal: bool,
    weapon_present: bool,
    is_suspicious: bool,
    reasons: list,
    frame,
    roi,
    category: str = "unknown",
    username: str = None
):
    """
    Save evidence to PostgreSQL.
    Images (frame and ROI) are stored as JPEG bytes directly in the DB.
    No files are written to disk.
    Returns (evidence_id, None, None) on success or (None, None, None) on failure.
    """
    db = SessionLocal()
    try:
        # Determine category
        if is_criminal:
            category = "criminals"
        elif weapon_present:
            category = "weapons"
        elif is_suspicious:
            category = "suspicious"

        # Encode images to JPEG bytes in-memory and encrypt
        frame_data = _encode_image_to_bytes(frame)
        roi_data = _encode_image_to_bytes(roi)
        enc = _get_encryption_manager()
        if frame_data:
            frame_data = enc.encrypt(frame_data)
        if roi_data:
            roi_data = enc.encrypt(roi_data)

        # Save to database
        reason_str = ",".join(reasons) if reasons else "none"
        evidence = Evidence(
            timestamp=datetime.now(),
            camera_location=camera_location,
            track_id=track_id,
            person_name=name,
            is_criminal=is_criminal,
            weapon_present=weapon_present,
            is_suspicious=is_suspicious,
            reasons=reason_str,
            frame_path=None,
            roi_path=None,
            frame_data=frame_data,
            roi_data=roi_data,
            encrypted=True,
            created_by=None,
            category=category
        )
        db.add(evidence)
        db.commit()
        db.refresh(evidence)

        # Audit log
        try:
            audit = AuditLogger(db)
            audit.log(
                action="evidence_saved",
                username=username,
                resource="evidence",
                resource_id=str(evidence.id),
                details=f"track_id={track_id}, criminal={is_criminal}, weapon={weapon_present}"
            )
        except Exception:
            pass

        return evidence.id, None, None

    except Exception as e:
        print(f"Error saving evidence: {e}")
        db.rollback()
        return None, None, None
    finally:
        db.close()
