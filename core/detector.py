import os
import cv2
from ultralytics import YOLO


class HumanDetector:
    def __init__(self, model_path, conf, iou=0.45, imgsz=416):
        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz

        if os.path.exists(model_path) and os.path.getsize(model_path) == 0:
            raise ValueError(f"Human model file is empty: {model_path}")

        self.model = YOLO(model_path)

    def detect(self, frame):
        results = self.model(
            frame,
            conf=self.conf,
            iou=self.iou,
            imgsz=self.imgsz,
            verbose=False,
        )

        detections = []
        for r in results:
            for box in r.boxes:
                if int(box.cls[0]) == 0:  # person
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    score = float(box.conf[0])
                    detections.append(([x1, y1, x2 - x1, y2 - y1], score))

        return detections
