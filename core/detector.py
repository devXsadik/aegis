import os
import cv2
from ultralytics import YOLO


class HumanDetector:
    def __init__(self, model_path, conf, iou=0.45, imgsz=640):
        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz

        if os.path.exists(model_path) and os.path.getsize(model_path) == 0:
            raise ValueError(f"Human model file is empty: {model_path}")

        self.model = YOLO(model_path)

    def preprocess(self, frame):
        # Improve contrast for low-light/dark frames
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        enhanced = cv2.merge((l, a, b))
        return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

    def detect(self, frame):
        enhanced = self.preprocess(frame)

        results = self.model(
            enhanced,
            conf=self.conf,
            iou=self.iou,
            imgsz=self.imgsz,
            verbose=False,
            augment=True,     # test-time augmentation for better accuracy
        )

        detections = []
        for r in results:
            for box in r.boxes:
                if int(box.cls[0]) == 0:  # person
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    score = float(box.conf[0])
                    detections.append(([x1, y1, x2 - x1, y2 - y1], score))

        return detections
