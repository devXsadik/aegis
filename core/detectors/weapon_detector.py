import threading

import numpy as np
from ultralytics import YOLO


class WeaponDetector:
    def __init__(self, model_path: str, conf_threshold: float = 0.4, device: str = "cpu"):
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.device = device
        self._lock = threading.Lock()

    def detect(self, frame: np.ndarray):
        with self._lock:
            results = self.model(frame, conf=self.conf_threshold, verbose=False, device=self.device)
        weapons = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                weapons.append({
                    "bbox": (x1, y1, x2, y2),
                    "score": conf,
                    "class_id": cls_id,
                })
        return weapons
