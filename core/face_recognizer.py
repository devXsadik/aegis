import os
import pickle
import face_recognition
import numpy as np
from pathlib import Path


class FaceRecognizer:
    def __init__(self, encodings_path: str = "face_encodings.pkl", tolerance: float = 0.45):
        self.tolerance = tolerance
        self.known_encodings = []
        self.known_names = []
        if os.path.exists(encodings_path):
            self._load(encodings_path)

    def _load(self, path: str):
        with open(path, "rb") as f:
            data = pickle.load(f)
        for item in data:
            self.known_encodings.append(item["encoding"])
            self.known_names.append(item["name"])

    def recognize(self, face_roi):
        rgb = face_recognition.load_image_file(face_roi) if isinstance(face_roi, str) else \
              cv2.cvtColor(face_roi, cv2.COLOR_BGR2RGB) if hasattr(face_roi, 'shape') else None
        if rgb is None:
            return None
        boxes = face_recognition.face_locations(rgb, model="hog")
        if not boxes:
            return None
        encodings = face_recognition.face_encodings(rgb, boxes)
        if not encodings:
            return None
        matches = face_recognition.compare_faces(self.known_encodings, encodings[0], self.tolerance)
        if not any(matches):
            return None
        face_distances = face_recognition.face_distance(self.known_encodings, encodings[0])
        best_idx = np.argmin(face_distances)
        if matches[best_idx]:
            return self.known_names[best_idx]
        return None
