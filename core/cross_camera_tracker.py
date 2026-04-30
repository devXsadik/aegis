"""
Cross-Camera Person Re-Identification Module
Tracks the same person across multiple camera feeds using face/body features
"""
import numpy as np
from typing import Dict, List, Optional, Tuple
import cv2
import face_recognition
from datetime import datetime, timedelta
from collections import defaultdict


class PersonIdentity:
    """Represents a unique person tracked across cameras"""

    def __init__(self, person_id: str, name: Optional[str] = None):
        self.person_id = person_id
        self.name = name
        self.face_encodings: List[np.ndarray] = []
        self.body_features: List[np.ndarray] = []
        self.last_seen: Dict[str, datetime] = {}  # camera_id -> last seen time
        self.locations: List[Tuple[str, datetime, Tuple[int, int]]] = []  # (camera, time, position)
        self.criminal = False

    def add_face_encoding(self, encoding: np.ndarray):
        if len(self.face_encodings) < 5:  # Keep last 5
            self.face_encodings.append(encoding)

    def add_body_features(self, features: np.ndarray):
        if len(self.body_features) < 5:
            self.body_features.append(features)

    def update_location(self, camera_id: str, position: Tuple[int, int]):
        now = datetime.utcnow()
        self.last_seen[camera_id] = now
        self.locations.append((camera_id, now, position))
        # Keep last 50 locations
        self.locations = self.locations[-50:]


class CrossCameraTracker:
    """Tracks persons across multiple camera feeds"""

    def __init__(self, similarity_threshold: float = 0.6):
        self.persons: Dict[str, PersonIdentity] = {}
        self.similarity_threshold = similarity_threshold
        self.next_person_id = 1

    def identify_person(
        self,
        camera_id: str,
        face_roi,
        body_roi,
        timestamp: datetime
    ) -> PersonIdentity:
        """
        Identify a person across cameras.
        Returns existing PersonIdentity or creates new one.
        """
        # Extract face encoding
        face_encoding = None
        if face_roi is not None and face_roi.size > 0:
            rgb = cv2.cvtColor(face_roi, cv2.COLOR_BGR2RGB)
            encodings = face_recognition.face_encodings(rgb)
            if encodings:
                face_encoding = encodings[0]

        # Extract body features (simple color histogram)
        body_features = None
        if body_roi is not None and body_roi.size > 0:
            body_features = self._extract_body_features(body_roi)

        # Try to match with existing persons
        if face_encoding is not None:
            for person in self.persons.values():
                if person.face_encodings:
                    matches = face_recognition.compare_faces(
                        person.face_encodings,
                        face_encoding,
                        tolerance=self.similarity_threshold
                    )
                    if True in matches:
                        person.add_face_encoding(face_encoding)
                        if body_features is not None:
                            person.add_body_features(body_features)
                        return person

        # No match found, create new person
        person_id = f"PERSON_{self.next_person_id}"
        self.next_person_id += 1

        person = PersonIdentity(person_id)
        if face_encoding is not None:
            person.add_face_encoding(face_encoding)
        if body_features is not None:
            person.add_body_features(body_features)

        self.persons[person_id] = person
        return person

    def _extract_body_features(self, roi) -> np.ndarray:
        """Extract simple body features (color histogram)"""
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist.flatten()

    def get_person_journey(self, person_id: str) -> List[Tuple[str, datetime, Tuple[int, int]]]:
        """Get the movement journey of a person across cameras"""
        if person_id in self.persons:
            return self.persons[person_id].locations
        return []

    def get_active_persons(self, camera_id: Optional[str] = None, minutes: int = 10):
        """Get persons active in last N minutes"""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        active = []
        for person in self.persons.values():
            if camera_id:
                if camera_id in person.last_seen and person.last_seen[camera_id] > cutoff:
                    active.append(person)
            else:
                if any(t > cutoff for t in person.last_seen.values()):
                    active.append(person)
        return active
