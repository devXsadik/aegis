import os
from ultralytics import YOLO


class WeaponDetector:
    def __init__(self, model_path, conf):
        self.conf = conf
        self.model_path = model_path

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Weapon model not found: {model_path}")

        if os.path.getsize(model_path) == 0:
            raise ValueError(f"Weapon model file is empty: {model_path}")

        self.model = YOLO(model_path)

    def detect(self, frame):
        results = self.model(frame, conf=self.conf, verbose=False)
        weapons = []

        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                # Adjust according to your trained weapon model classes
                if cls_id in [0, 1]:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    score = float(box.conf[0])
                    weapons.append(
                        {
                            "bbox": [x1, y1, x2, y2],
                            "score": score,
                            "cls_id": cls_id,
                        }
                    )

        return weapons
