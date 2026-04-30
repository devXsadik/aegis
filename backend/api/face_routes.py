from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.models.face_encoding import FaceEncoding
from backend.auth.auth import admin_only, operator_or_admin
from backend.models.user import User
import numpy as np
import face_recognition
import os

router = APIRouter(prefix="/faces", tags=["face-recognition"])


class FaceEncodingResponse(BaseModel):
    id: int
    person_name: str
    person_id: str
    created_at: str

    class Config:
        orm_mode = True


@router.get("/", response_model=list[FaceEncodingResponse])
def list_faces(db: Session = Depends(get_db), user: User = Depends(operator_or_admin)):
    return db.query(FaceEncoding).all()


@router.post("/encode")
def encode_faces(
    db: Session = Depends(get_db),
    user: User = Depends(admin_only)
):
    known_person_dir = "known_person"
    if not os.path.exists(known_person_dir):
        raise HTTPException(status_code=404, detail="known_person directory not found")

    encodings = []
    for person_dir in os.listdir(known_person_dir):
        person_path = os.path.join(known_person_dir, person_dir)
        if not os.path.isdir(person_path):
            continue

        for img_file in os.listdir(person_path):
            if not img_file.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
            img_path = os.path.join(person_path, img_file)
            image = face_recognition.load_image_file(img_path)
            face_encs = face_recognition.face_encodings(image)
            if face_encs:
                enc = FaceEncoding(
                    person_name=person_dir,
                    person_id=person_dir,
                    encoding=FaceEncoding.serialize_encoding(face_encs[0]),
                    image_path=img_path
                )
                encodings.append(enc)

    db.bulk_save_objects(encodings)
    db.commit()
    return {"status": "success", "encodings_added": len(encodings)}
