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
        if data and isinstance(data, tuple) and len(data) == 2 and isinstance(data[0], list) and isinstance(data[1], list):
            print("Detected (encodings, names) tuple format, zipping...")
            data = [{"encoding": e, "name": n} for e, n in zip(data[0], data[1])]
        elif data and isinstance(data, tuple) and len(data) >= 2 and isinstance(data[0], str):
            print("Detected single entry tuple format, wrapping in list")
            data = [data]
        
        for item in data:
            if isinstance(item, dict):
                person_name = item.get("name", "Unknown")
                person_id = item.get("name", "Unknown")
                encoding_data = item.get("encoding")
                image_path = item.get("image_path", "")
            elif isinstance(item, (list, tuple)):
                # Fallback for list/tuple format [name, encoding, image_path]
                # Some formats have [name, [encoding1, encoding2, ...], image_path]
                person_name = item[0] if len(item) > 0 else "Unknown"
                person_id = person_name
                encoding_data = None
                if len(item) > 1:
                    encs = item[1]
                    if isinstance(encs, (list, tuple)) and len(encs) > 0:
                        encoding_data = encs[0] # Take first encoding
                    else:
                        encoding_data = encs
                image_path = item[2] if len(item) > 2 else ""
            else:
                print(f"Skipping unknown item format: {type(item)}")
                continue

            try:
                encoding = FaceEncoding(
                    person_name=person_name,
                    person_id=person_id,
                    encoding=FaceEncoding.serialize_encoding(encoding_data),
                    image_path=image_path
                )
                db.add(encoding)
                count += 1
            except Exception as e:
                print(f"Error migrating face encoding for {person_name}: {e}")
                print(f"Data was: name={person_name}, enc_type={type(encoding_data)}")

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
                    camera_location=row.get("camera_location") or "Unknown",
                    track_id=int(row.get("track_id") or 0),
                    person_name=row.get("name") or "Unknown",
                    is_criminal=str(row.get("is_criminal", "")).lower() == "true",
                    weapon_present=str(row.get("weapon_present", "")).lower() == "true",
                    is_suspicious=str(row.get("is_suspicious", "")).lower() == "true",
                    reasons=row.get("reasons"),
                    frame_path=row.get("frame_path"),
                    roi_path=row.get("roi_path"),
                    category=row.get("category") or "unknown"
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
