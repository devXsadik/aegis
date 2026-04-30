import face_recognition
import numpy as np
from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.models.face_encoding import FaceEncoding
from typing import Optional


class FaceRecognizerDB:
    """Database-backed face recognizer that replaces pickle-based version"""

    def __init__(self, tolerance: float = 0.45):
        self.tolerance = tolerance
        self.known_encodings = []
        self.known_names = []
        self._load_encodings()

    def _load_encodings(self):
        """Load face encodings from PostgreSQL"""
        db = SessionLocal()
        try:
            records = db.query(FaceEncoding).all()
            self.known_encodings = [
                FaceEncoding.deserialize_encoding(r.encoding) for r in records
            ]
            self.known_names = [r.person_name for r in records]
            print(f"Loaded {len(self.known_encodings)} face encodings from database")
        except Exception as e:
            print(f"Error loading face encodings: {e}")
            self.known_encodings = []
            self.known_names = []
        finally:
            db.close()

    def recognize_person(self, roi) -> Optional[str]:
        """Recognize a person from ROI image"""
        if not self.known_encodings:
            return None

        # Convert ROI to RGB if needed
        if len(roi.shape) == 3 and roi.shape[2] == 3:
            rgb_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        else:
            rgb_roi = roi

        # Get face encodings from ROI
        face_encodings = face_recognition.face_encodings(rgb_roi)
        if not face_encodings:
            return None

        face_encoding = face_encodings[0]

        # Compare with known encodings
        matches = face_recognition.compare_faces(
            self.known_encodings, face_encoding, tolerance=self.tolerance
        )

        if True in matches:
            first_match_index = matches.index(True)
            return self.known_names[first_match_index]

        return None

    def reload_encodings(self):
        """Reload encodings from database (call after adding new faces)"""
        self._load_encodings()


import cv2
