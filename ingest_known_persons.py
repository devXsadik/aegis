"""
ingest_known_persons.py
-----------------------
Replaces encode_faces.py.

Reads images from known_person/ + optional manifest.json metadata,
generates face encodings, and stores both encoding + raw image bytes
directly into PostgreSQL.

Usage:
    python3 ingest_known_persons.py
"""
import json
import cv2
import face_recognition
from pathlib import Path
from backend.db.database import SessionLocal, init_db
from backend.models.known_person import KnownPerson
from backend.models.person_image import PersonImage
from backend.models.face_encoding import FaceEncoding


KNOWN_DIR = Path(__file__).parent / "known_person"


def _read_image_bytes(path: str) -> bytes:
    img = cv2.imread(path)
    if img is None:
        return b""
    success, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buffer.tobytes() if success else b""


def _load_manifest() -> dict:
    manifest_path = KNOWN_DIR / "manifest.json"
    if not manifest_path.exists():
        return {}
    with open(manifest_path) as f:
        data = json.load(f)
    return {p["person_id"]: p for p in data.get("persons", [])}


def _folder_metadata(folder_name: str):
    parts = folder_name.split("_", 2)
    if len(parts) >= 3:
        name = parts[2].replace("_", " ")
        category = "criminal" if parts[0].upper() == "CRIMINAL" else "civilian"
    else:
        name = folder_name
        category = "civilian"
    return {
        "name": name,
        "category": category,
        "criminal_status": "unknown" if category == "criminal" else "cleared",
        "threat_level": 5 if category == "criminal" else 0,
        "notes": None,
    }


def ingest():
    if not KNOWN_DIR.exists():
        print(f"❌ known_person/ directory not found at {KNOWN_DIR}")
        return

    init_db()
    db = SessionLocal()
    manifest = _load_manifest()
    if manifest:
        print(f"✓ Loaded {len(manifest)} entries from manifest.json")

    total_persons = 0
    total_images = 0
    total_encodings = 0

    try:
        for person_dir in sorted(KNOWN_DIR.iterdir()):
            if not person_dir.is_dir():
                continue

            folder_name = person_dir.name
            meta = manifest.get(folder_name, _folder_metadata(folder_name))

            print(f"\n[{folder_name}]")

            person = db.query(KnownPerson).filter(
                KnownPerson.person_id == folder_name
            ).first()
            if not person:
                person = KnownPerson(
                    person_id=folder_name,
                    name=meta["name"],
                    category=meta["category"],
                    criminal_status=meta["criminal_status"],
                    threat_level=meta["threat_level"],
                    notes=meta.get("notes"),
                )
                db.add(person)
                db.flush()
                total_persons += 1
                print(f"  ✓ Created person record: {meta['name']}")

            for img_file in sorted(person_dir.iterdir()):
                if img_file.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                    continue

                img_path = str(img_file)

                try:
                    image = face_recognition.load_image_file(img_path)
                    encodings = face_recognition.face_encodings(image, num_jitters=5)
                except Exception as e:
                    print(f"  ✗ Error processing {img_file.name}: {e}")
                    continue

                if not encodings:
                    print(f"  ✗ No face found in: {img_file.name}")
                    continue

                enc_record = FaceEncoding(
                    person_id=person.id,
                    encoding=FaceEncoding.serialize_encoding(encodings[0]),
                )
                db.add(enc_record)
                total_encodings += 1

                image_bytes = _read_image_bytes(img_path)
                if image_bytes:
                    img_record = PersonImage(
                        person_id=person.id,
                        image_data=image_bytes,
                        image_type="face",
                        filename=img_file.name,
                    )
                    db.add(img_record)
                    total_images += 1

                print(f"  ✓ Encoded + stored: {img_file.name}")

        db.commit()
        print(f"\n{'='*50}")
        print(f"✅ Ingest complete!")
        print(f"   Persons:   {total_persons} created")
        print(f"   Images:    {total_images} stored in DB")
        print(f"   Encodings: {total_encodings} stored in DB")
        print(f"\nYou can now safely delete the known_person/ directory.")

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    ingest()
