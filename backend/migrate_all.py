"""
Migrate all existing data to new database schema
"""
import pickle
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '.')

from backend.db.database import SessionLocal
from backend.models import User, KnownPerson, FaceEncoding, Evidence
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def migrate_users():
    """Create default users"""
    db = SessionLocal()
    try:
        # Check if admin exists
        if db.query(User).filter_by(username="admin").first():
            print("  ✓ Users already exist")
            return

        admin = User(
            username="admin",
            email="admin@surveillance.system",
            hashed_password=pwd_context.hash("Admin123!"),
            role="admin",
            is_active=True,
            created_at=datetime.utcnow()
        )
        db.add(admin)

        operator = User(
            username="operator",
            email="operator@surveillance.system",
            hashed_password=pwd_context.hash("Operator123!"),
            role="operator",
            is_active=True,
            created_at=datetime.utcnow()
        )
        db.add(operator)

        db.commit()
        print("  ✓ Created admin and operator users")

    except Exception as e:
        db.rollback()
        print(f"  ✗ Error: {e}")
    finally:
        db.close()


def migrate_known_persons():
    """Migrate known_person/ folder to known_persons table"""
    db = SessionLocal()
    try:
        known_dir = Path("known_person")
        if not known_dir.exists():
            print("  ⚠️  known_person/ not found, skipping")
            return

        count = 0
        for person_dir in known_dir.iterdir():
            if not person_dir.is_dir():
                continue

            # Parse name: CRIMINAL_001_Name or similar
            parts = person_dir.name.split("_")
            if len(parts) >= 3:
                person_id = person_dir.name
                name = " ".join(parts[2:])
                category = "criminal" if "criminal" in parts[0].lower() else "civilian"
            else:
                person_id = person_dir.name
                name = person_dir.name
                category = "civilian"

            # Check if exists
            existing = db.query(KnownPerson).filter_by(person_id=person_id).first()
            if existing:
                print(f"  ⚠️  {person_id} already exists, skipping")
                continue

            kp = KnownPerson(
                person_id=person_id,
                name=name,
                category=category,
                threat_level=10 if category == "criminal" else 0,
                created_at=datetime.utcnow()
            )
            db.add(kp)
            count += 1

        db.commit()
        print(f"  ✓ Migrated {count} known persons")

    except Exception as e:
        db.rollback()
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def migrate_face_encodings():
    """Migrate face_encodings.pkl to face_encodings table"""
    db = SessionLocal()
    try:
        pkl_path = Path("face_encodings.pkl")
        if not pkl_path.exists():
            print("  ⚠️  face_encodings.pkl not found, skipping")
            return

        with open(pkl_path, 'rb') as f:
            data = pickle.load(f)

        count = 0
        for item in data:
            name = item.get("name", "")
            encoding = item.get("encoding")
            image_path = item.get("image_path", "")

            # Find person
            person = db.query(KnownPerson).filter_by(person_id=name).first()
            if not person:
                # Create person
                person = KnownPerson(
                    person_id=name,
                    name=name,
                    category="unknown",
                    created_at=datetime.utcnow()
                )
                db.add(person)
                db.flush()

            # Create face encoding
            fe = FaceEncoding(
                person_id=person.id,
                encoding=pickle.dumps(encoding),
                image_path=image_path,
                created_at=datetime.utcnow()
            )
            db.add(fe)
            count += 1

        db.commit()
        print(f"  ✓ Migrated {count} face encodings")

    except Exception as e:
        db.rollback()
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def migrate_evidence_logs():
    """Migrate evidence/log.csv to evidence table"""
    db = SessionLocal()
    try:
        csv_path = Path("evidence/log.csv")
        if not csv_path.exists():
            print("  ⚠️  evidence/log.csv not found, skipping")
            return

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                # Parse timestamp
                try:
                    ts = datetime.strptime(row.get("timestamp", ""), "%Y%m%d_%H%M%S_%f")
                except:
                    ts = datetime.utcnow()

                # Find person
                person_name = row.get("name", "")
                person = None
                if person_name and person_name != "None":
                    person = db.query(KnownPerson).filter_by(name=person_name).first()

                evidence = Evidence(
                    timestamp=ts,
                    camera_location=row.get("location", ""),
                    track_id=int(row.get("track_id", 0)),
                    person_id=person.id if person else None,
                    person_name=person_name if person_name != "None" else None,
                    is_criminal=row.get("is_criminal", "").lower() == "true",
                    weapon_present=row.get("weapon_present", "").lower() == "true",
                    is_suspicious=row.get("is_suspicious", "").lower() == "true",
                    reasons=row.get("reasons"),
                    frame_path=row.get("frame_path"),
                    roi_path=row.get("roi_path"),
                    category="criminals" if row.get("is_criminal") == "True" else "suspicious",
                    created_at=datetime.utcnow()
                )
                db.add(evidence)
                count += 1

        db.commit()
        print(f"  ✓ Migrated {count} evidence records")

    except Exception as e:
        db.rollback()
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("  Data Migration: Old → New Database Schema")
    print("=" * 60)

    print("\n1. Migrating users...")
    migrate_users()

    print("\n2. Migrating known persons...")
    migrate_known_persons()

    print("\n3. Migrating face encodings...")
    migrate_face_encodings()

    print("\n4. Migrating evidence logs...")
    migrate_evidence_logs()

    print("\n" + "=" * 60)
    print("  Migration Complete!")
    print("=" * 60)
