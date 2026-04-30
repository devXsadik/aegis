import io
import numpy as np
import face_recognition
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.db.database import get_db
from backend.models.face_encoding import FaceEncoding
from backend.models.known_person import KnownPerson
from backend.models.person_image import PersonImage
from backend.auth.auth import admin_only, operator_or_admin
from backend.models.user import User
import cv2

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


@router.post("/enroll")
async def enroll_face(
    person_id: str,
    person_name: str,
    category: str = "criminal",
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(admin_only)
):
    """
    Enroll a new person by uploading their face image directly.
    The image and face encoding are both stored in the database — no disk writes.
    """
    # Read uploaded image bytes
    raw_bytes = await image.read()
    np_arr = np.frombuffer(raw_bytes, np.uint8)
    img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise HTTPException(status_code=400, detail="Could not decode image")

    # Convert to RGB for face_recognition
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    encodings = face_recognition.face_encodings(img_rgb, num_jitters=3)
    if not encodings:
        raise HTTPException(status_code=400, detail="No face detected in the uploaded image")

    # Re-encode to JPEG bytes for storage
    success, buffer = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    stored_bytes = buffer.tobytes() if success else raw_bytes

    # Get or create KnownPerson record
    person = db.query(KnownPerson).filter(KnownPerson.person_id == person_id).first()
    if not person:
        person = KnownPerson(
            person_id=person_id,
            name=person_name,
            category=category,
            criminal_status="unknown" if category == "criminal" else "cleared",
            threat_level=5 if category == "criminal" else 0,
        )
        db.add(person)
        db.flush()

    # Store face encoding
    enc_record = FaceEncoding(
        person_name=person_id,
        person_id=person_id,
        encoding=FaceEncoding.serialize_encoding(encodings[0]),
        image_path=None,
    )
    db.add(enc_record)

    # Store image bytes
    img_record = PersonImage(
        person_id=person.id,
        image_data=stored_bytes,
        image_type="face",
        filename=image.filename,
        image_path=None,
    )
    db.add(img_record)

    db.commit()
    return {
        "status": "success",
        "person_id": person_id,
        "person_name": person_name,
        "encoding_stored": True,
        "image_stored": True,
        "message": "Face enrolled successfully. Reload the recognizer to activate."
    }


@router.get("/{person_id}/images")
def list_person_images(
    person_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    """List all images stored for a given person."""
    person = db.query(KnownPerson).filter(KnownPerson.person_id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    images = db.query(PersonImage).filter(PersonImage.person_id == person.id).all()
    return [{"id": img.id, "filename": img.filename, "image_type": img.image_type,
             "has_data": bool(img.image_data), "created_at": str(img.created_at)} for img in images]


@router.get("/images/{image_id}/photo")
def get_person_image(
    image_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(operator_or_admin)
):
    """Serve a person's face image stored in DB."""
    img = db.query(PersonImage).filter(PersonImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    if not img.image_data:
        raise HTTPException(status_code=404, detail="No image data stored")
    return Response(content=img.image_data, media_type="image/jpeg")


@router.post("/encode")
def encode_faces_legacy(
    db: Session = Depends(get_db),
    user: User = Depends(admin_only)
):
    """
    Legacy endpoint — use POST /faces/enroll instead.
    Kept for backwards compatibility.
    """
    raise HTTPException(
        status_code=410,
        detail="This endpoint is deprecated. Use POST /faces/enroll to enroll faces directly via upload."
    )
