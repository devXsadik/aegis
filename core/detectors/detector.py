import cv2
import numpy as np
from ultralytics import YOLO


class HumanDetector:
    def __init__(self, model_path: str, conf_threshold: float = 0.5):
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold

    def detect(self, frame: np.ndarray):
        results = self.model(frame, conf=self.conf_threshold, classes=[0], verbose=False, device="cpu")
        detections = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                detections.append(([x1, y1, x2, y2], conf, 0))
        return detections
