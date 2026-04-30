import os
import cv2
from datetime import datetime
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.models.evidence import Evidence
from backend.utils.encryption import EncryptionManager
from backend.utils.audit import AuditLogger
from dotenv import load_dotenv

load_dotenv()


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
    Save evidence to PostgreSQL with optional encryption.
    Returns (frame_path, roi_path) or (None, None) on failure.
    """
    db = SessionLocal()
    try:
        timestamp = datetime.now()
        ts_str = timestamp.strftime("%Y%m%d_%H%M%S_%f")

        # Determine category
        if is_criminal:
            category = "criminals"
        elif weapon_present:
            category = "weapons"
        elif is_suspicious:
            category = "suspicious"

        # Save frame and ROI images
        evidence_dir = os.path.join("evidence", category)
        os.makedirs(evidence_dir, exist_ok=True)

        frame_path = os.path.join(evidence_dir, f"{ts_str}_{camera_location}_id{track_id}_frame.jpg")
        roi_path = os.path.join(evidence_dir, f"{ts_str}_{camera_location}_id{track_id}_roi.jpg")

        cv2.imwrite(frame_path, frame)
        cv2.imwrite(roi_path, roi)

        # Encrypt files if configured
        encrypted = False
        if os.getenv("ENCRYPTION_KEY", "default") != "default":
            try:
                enc_manager = EncryptionManager()
                frame_path = enc_manager.encrypt_file(frame_path)
                roi_path = enc_manager.encrypt_file(roi_path)
                encrypted = True
            except Exception as e:
                print(f"Encryption failed: {e}")

        # Save to database
        reason_str = ",".join(reasons) if reasons else "none"
        evidence = Evidence(
            timestamp=timestamp,
            camera_location=camera_location,
            track_id=track_id,
            person_name=name,
            is_criminal=is_criminal,
            weapon_present=weapon_present,
            is_suspicious=is_suspicious,
            reasons=reason_str,
            frame_path=frame_path,
            roi_path=roi_path,
            encrypted=encrypted,
            created_by=username,
            category=category
        )
        db.add(evidence)
        db.commit()

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

        return frame_path, roi_path

    except Exception as e:
        print(f"Error saving evidence: {e}")
        db.rollback()
        return None, None
    finally:
        db.close()
