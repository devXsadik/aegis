import os
import pickle
import cv2
import numpy as np
import face_recognition


class FaceRecognizer:
    def __init__(self, encoding_file="face_encodings.pkl", tolerance=0.45):
        if not os.path.exists(encoding_file):
            raise FileNotFoundError(
                f"Encoding file not found: {encoding_file}. Run encode_faces.py first."
            )
        with open(encoding_file, "rb") as f:
            self.known_encodings, self.known_names = pickle.load(f)
        self.tolerance = tolerance

    def _best_match(self, face_enc):
        if len(self.known_encodings) == 0:
            return None
        distances = face_recognition.face_distance(self.known_encodings, face_enc)
        best_idx = int(np.argmin(distances))
        if distances[best_idx] <= self.tolerance:
            return self.known_names[best_idx]
        return None

    def recognize_person(self, roi):
        if roi is None or roi.size == 0:
            return None
        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb, model="hog")
        if not locations:
            return None
        encodings = face_recognition.face_encodings(rgb, locations, num_jitters=2)
        if not encodings:
            return None
        return self._best_match(encodings[0])

    def recognize_all(self, frame):
        """Recognize all faces in a full frame. Returns list of (name, bbox)."""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb, model="hog")
        if not locations:
            return []
        encodings = face_recognition.face_encodings(rgb, locations, num_jitters=2)
        results = []
        for (top, right, bottom, left), enc in zip(locations, encodings):
            name = self._best_match(enc) or "Unknown"
            results.append({"name": name, "bbox": (left, top, right, bottom)})
        return results
