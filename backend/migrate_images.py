"""
migrate_images.py
-----------------
One-time migration script to:
1. Read known_person/ images -> store in known_persons + person_images tables
2. Read evidence/ image files -> store bytes in evidence.frame_data / roi_data columns

Run from project root:
    python3 -m backend.migrate_images
"""
import os
import cv2
from pathlib import Path
from backend.db.database import SessionLocal, init_db
from backend.models.known_person import KnownPerson
from backend.models.person_image import PersonImage
from backend.models.evidence import Evidence


def _read_image_bytes(path: str) -> bytes:
    """Read an image file and return JPEG-encoded bytes."""
    img = cv2.imread(path)
    if img is None:
        return b""
    success, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buffer.tobytes() if success else b""


def migrate_known_persons():
    """Migrate known_person/ folder images into known_persons + person_images tables."""
    known_dir = Path("known_person")
    if not known_dir.exists():
        print("  ⚠️  known_person/ not found, skipping")
        return

    db = SessionLocal()
    try:
        total_persons = 0
        total_images = 0

        for person_dir in sorted(known_dir.iterdir()):
            if not person_dir.is_dir():
                continue

            folder_name = person_dir.name  # e.g. CRIMINAL_001_Sadik
            # Parse person_id and name from folder
            parts = folder_name.split("_", 2)
            if len(parts) >= 3:
                person_id_str = f"{parts[0]}_{parts[1]}"
                name = parts[2].replace("_", " ")
                category = "criminal" if parts[0] == "CRIMINAL" else "civilian"
            else:
                person_id_str = folder_name
                name = folder_name
                category = "civilian"

            # Get or create the KnownPerson record
            person = db.query(KnownPerson).filter(
                KnownPerson.person_id == folder_name
            ).first()

            if not person:
                person = KnownPerson(
                    person_id=folder_name,
                    name=name,
                    category=category,
                    criminal_status="unknown" if category == "criminal" else "cleared",
                    threat_level=5 if category == "criminal" else 0,
                )
                db.add(person)
                db.flush()  # get person.id without committing
                total_persons += 1
                print(f"  ✓ Created person: {folder_name}")
            else:
                print(f"  → Person already exists: {folder_name}")

            # Migrate images
            for img_file in sorted(person_dir.iterdir()):
                if img_file.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                    continue

                image_bytes = _read_image_bytes(str(img_file))
                if not image_bytes:
                    print(f"    ✗ Could not read: {img_file.name}")
                    continue

                # Check if already migrated (has image_data)
                existing = db.query(PersonImage).filter(
                    PersonImage.person_id == person.id,
                    PersonImage.filename == img_file.name,
                    PersonImage.image_data.isnot(None)
                ).first()
                if existing:
                    print(f"    → Already migrated: {img_file.name}")
                    continue

                img_record = PersonImage(
                    person_id=person.id,
                    image_data=image_bytes,
                    image_type="face",
                    filename=img_file.name,
                    image_path=None,
                )
                db.add(img_record)
                total_images += 1
                print(f"    ✓ Migrated image: {img_file.name} ({len(image_bytes)} bytes)")

        db.commit()
        print(f"\n✅ Migrated {total_persons} persons, {total_images} images to DB")

    except Exception as e:
        print(f"  ✗ Error migrating known persons: {e}")
        db.rollback()
    finally:
        db.close()


def migrate_evidence_images():
    """
    For each evidence record that has a file path on disk, read the image
    bytes and store them in frame_data / roi_data columns.
    """
    db = SessionLocal()
    try:
        records = db.query(Evidence).filter(
            Evidence.frame_data.is_(None),
            Evidence.frame_path.isnot(None)
        ).all()

        if not records:
            print("  ℹ️  No evidence records with file paths found — skipping")
            return

        updated = 0
        for ev in records:
            changed = False

            if ev.frame_path and os.path.exists(ev.frame_path):
                ev.frame_data = _read_image_bytes(ev.frame_path)
                changed = True

            if ev.roi_path and os.path.exists(ev.roi_path):
                ev.roi_data = _read_image_bytes(ev.roi_path)
                changed = True

            if changed:
                updated += 1

        db.commit()
        print(f"✅ Migrated image data for {updated} evidence records")

    except Exception as e:
        print(f"  ✗ Error migrating evidence images: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("Initializing database schema...")
    init_db()

    print("\n1. Migrating known persons...")
    migrate_known_persons()

    print("\n2. Migrating evidence images...")
    migrate_evidence_images()

    print("\n✅ Migration complete!")
    print("You can now safely delete known_person/ and evidence/ directories.")
