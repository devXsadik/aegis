"""
Vehicle Detection and Tracking Module
Uses YOLO to detect vehicles (cars, trucks, motorcycles, buses)
"""
import cv2
import numpy as np
from typing import List, Dict, Optional


class VehicleDetector:
    """Detect vehicles using YOLO"""

    VEHICLE_CLASSES = [2, 3, 5, 7]  # car, motorcycle, bus, truck in COCO

    def __init__(self, model_path: str, conf_threshold: float = 0.5):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.model = None
        self._load_model()

    def _load_model(self):
        """Load YOLO model"""
        try:
            from ultralytics import YOLO
            self.model = YOLO(self.model_path)
            print(f"Vehicle detector loaded: {self.model_path}")
        except Exception as e:
            print(f"Failed to load vehicle model: {e}")
            self.model = None

    def detect(self, frame) -> List[Dict]:
        """
        Detect vehicles in frame
        Returns list of dicts: {bbox, score, class_id, class_name}
        """
        if self.model is None:
            return []

        try:
            results = self.model(frame, conf=self.conf_threshold, verbose=False)[0]

            vehicles = []
            for r in results.boxes.data.tolist():
                x1, y1, x2, y2, score, class_id = r
                if int(class_id) in self.VEHICLE_CLASSES:
                    class_name = self._get_class_name(int(class_id))
                    vehicles.append({
                        'bbox': [int(x1), int(y1), int(x2), int(y2)],
                        'score': float(score),
                        'class_id': int(class_id),
                        'class_name': class_name
                    })

            return vehicles

        except Exception as e:
            print(f"Vehicle detection error: {e}")
            return []

    def _get_class_name(self, class_id: int) -> str:
        names = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}
        return names.get(class_id, 'vehicle')


class VehicleTracker:
    """Track vehicles across frames"""

    def __init__(self):
        self.tracks = {}
        self.next_id = 1

    def update(self, detections: List[Dict], frame) -> Dict:
        """
        Update vehicle tracks with new detections
        Returns dict of track_id -> {bbox, info}
        """
        updated_tracks = {}

        for det in detections:
            track_id = self.next_id
            self.next_id += 1
            updated_tracks[track_id] = {
                'bbox': det['bbox'],
                'info': det
            }

        self.tracks = updated_tracks
        return updated_tracks
