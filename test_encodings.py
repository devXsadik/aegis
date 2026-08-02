import numpy as np
from backend.db.database import SessionLocal
from backend.models.face_encoding import FaceEncoding
from backend.models.known_person import KnownPerson

db = SessionLocal()
records = db.query(FaceEncoding).all()
print(f"Total encodings: {len(records)}")
for rec in records:
    enc = FaceEncoding.deserialize_encoding(rec.encoding)
    print(f"ID: {rec.id}, Person ID: {rec.person_id}, Name: {rec.person.name}, Enc Size: {enc.size}, First val: {enc[0]:.4f}")
db.close()
