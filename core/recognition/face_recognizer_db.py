import cv2
import face_recognition
import numpy as np
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.models.face_encoding import FaceEncoding
from backend.models.known_person import KnownPerson


class FaceRecognizerDB:
    def __init__(self, tolerance: float = 0.45):
        self.tolerance = tolerance
        self._cache = None

    def _load_encodings(self):
        if self._cache is not None:
            return self._cache
        db: Session = SessionLocal()
        try:
            records = db.query(FaceEncoding).all()
            encodings = []
            names = []
            for rec in records:
                enc = FaceEncoding.deserialize_encoding(rec.encoding)
                if enc.size > 0:
                    encodings.append(enc)
                    names.append(rec.person.person_id)
            self._cache = (encodings, names)
            return self._cache
        finally:
            db.close()

    def recognize_person(self, face_roi):
        rgb = cv2.cvtColor(face_roi, cv2.COLOR_BGR2RGB)
        
        # IP cameras often produce small person ROIs. 
        # Upsample if the person ROI is small to help HOG find the face.
        h, w = rgb.shape[:2]
        upsample = 2 if (h < 300 or w < 300) else 1
        
        boxes = face_recognition.face_locations(rgb, model="hog", number_of_times_to_upsample=upsample)
        if not boxes:
            return None
        encodings = face_recognition.face_encodings(rgb, boxes)
        if not encodings:
            return None
        known_encodings, known_names = self._load_encodings()
        if not known_encodings:
            return None
        matches = face_recognition.compare_faces(known_encodings, encodings[0], self.tolerance)
        if not any(matches):
            return None
        distances = face_recognition.face_distance(known_encodings, encodings[0])
        best_idx = int(np.argmin(distances))
        if matches[best_idx]:
            return known_names[best_idx]
        return None

    def invalidate_cache(self):
        self._cache = None

