import threading

import numpy as np
from ultralytics import YOLO


class HumanDetector:
    def __init__(self, model_path: str, conf_threshold: float = 0.5, device: str = "cpu"):
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.device = device
        self._lock = threading.Lock()   # one model instance is shared by all cameras

    def detect(self, frame: np.ndarray):
        with self._lock:
            results = self.model(frame, conf=self.conf_threshold, classes=[0], verbose=False, device=self.device)
        detections = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                detections.append(([x1, y1, x2, y2], conf, 0))
        return detections
