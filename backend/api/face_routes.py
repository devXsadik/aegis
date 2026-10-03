import face_recognition
import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from backend.db.database import get_db
from backend.models.face_encoding import FaceEncoding
from backend.models.known_person import KnownPerson
from backend.models.person_image import PersonImage
from backend.models.user import User
from backend.auth.auth import operator_or_admin, admin_only

router = APIRouter(prefix="/faces", tags=["faces"])


class FaceEncodingResponse(BaseModel):
    id: int
    person_id: str
    person_name: Optional[str]
    encoding_version: str

    class Config:
        from_attributes = True


class KnownPersonResponse(BaseModel):
    id: int
    person_id: str
    name: str
    category: str
    criminal_status: str
    threat_level: int
    notes: Optional[str]

    class Config:
        from_attributes = True


@router.get("/", response_model=list[FaceEncodingResponse])
def list_encodings(skip: int = 0, limit: int = 100, db: Session = Depends(get_db),
                   user: User = Depends(operator_or_admin)):
    return db.query(FaceEncoding).offset(skip).limit(limit).all()


@router.get("/known-persons", response_model=list[KnownPersonResponse])
def list_known_persons(skip: int = 0, limit: int = 100, db: Session = Depends(get_db),
                       user: User = Depends(operator_or_admin)):
    return db.query(KnownPerson).offset(skip).limit(limit).all()


@router.post("/encode")
def reencode_faces(db: Session = Depends(get_db), admin: User = Depends(admin_only)):
    persons = db.query(KnownPerson).all()
    results = {"encoded": 0, "errors": 0}
    for person in persons:
        images = db.query(PersonImage).filter(PersonImage.person_id == person.id).all()
        for img in images:
            try:
                arr = np.frombuffer(img.image_data, dtype=np.uint8)
                import cv2
                decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                rgb = cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)
                encodings = face_recognition.face_encodings(rgb, num_jitters=3)
                if encodings:
                    enc_record = FaceEncoding(
                        person_id=person.id,
                        encoding=FaceEncoding.serialize_encoding(encodings[0]),
                    )
                    db.add(enc_record)
                    results["encoded"] += 1
            except Exception:
                results["errors"] += 1
    db.commit()
    return results

