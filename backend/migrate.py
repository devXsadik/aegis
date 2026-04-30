"""Migrate data from pickle and CSV to PostgreSQL"""
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal, init_db
from backend.models.face_encoding import FaceEncoding
from backend.models.evidence import Evidence
import pickle
import csv
import os


def migrate_face_encodings():
    """Migrate face_encodings.pkl to PostgreSQL"""
    pkl_path = "face_encodings.pkl"
    if not os.path.exists(pkl_path):
        print(f"{pkl_path} not found, skipping face encoding migration")
        return

    db = SessionLocal()
    try:
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)

        count = 0
        for item in data:
            encoding = FaceEncoding(
                person_name=item.get("name", "Unknown"),
                person_id=item.get("name", "Unknown"),
                encoding=FaceEncoding.serialize_encoding(item.get("encoding")),
                image_path=item.get("image_path", "")
            )
            db.add(encoding)
            count += 1

        db.commit()
        print(f"Migrated {count} face encodings to PostgreSQL")
    except Exception as e:
        print(f"Error migrating face encodings: {e}")
        db.rollback()
    finally:
        db.close()


def migrate_evidence_logs():
    """Migrate evidence/log.csv to PostgreSQL"""
    csv_path = "evidence/log.csv"
    if not os.path.exists(csv_path):
        print(f"{csv_path} not found, skipping evidence migration")
        return

    db = SessionLocal()
    try:
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                evidence = Evidence(
                    timestamp=row.get("timestamp"),
                    camera_location=row.get("camera_location"),
                    track_id=int(row.get("track_id", 0)),
                    person_name=row.get("name"),
                    is_criminal=row.get("is_criminal", "").lower() == "true",
                    weapon_present=row.get("weapon_present", "").lower() == "true",
                    is_suspicious=row.get("is_suspicious", "").lower() == "true",
                    reasons=row.get("reasons"),
                    frame_path=row.get("frame_path"),
                    roi_path=row.get("roi_path"),
                    category=row.get("category", "unknown")
                )
                db.add(evidence)
                count += 1

            db.commit()
            print(f"Migrated {count} evidence records to PostgreSQL")
    except Exception as e:
        print(f"Error migrating evidence: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("Migrating face encodings...")
    migrate_face_encodings()
    print("Migrating evidence logs...")
    migrate_evidence_logs()
    print("Migration complete!")
