import threading

import numpy as np
from ultralytics import YOLO


class FireSmokeDetector:
    """YOLO fire/smoke detector. Needs a trained model (config/models.yaml: fire_detector)."""

    def __init__(self, model_path: str, conf_threshold: float = 0.5, device: str = "cpu"):
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.device = device
        self._lock = threading.Lock()

    def detect(self, frame: np.ndarray):
        with self._lock:
            results = self.model(frame, conf=self.conf_threshold, verbose=False, device=self.device)
        out = []
        for r in results:
            names = r.names
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cls_id = int(box.cls[0])
                out.append({"bbox": (x1, y1, x2, y2), "score": float(box.conf[0]),
                            "class_id": cls_id, "class_name": names.get(cls_id, str(cls_id))})
        return out
