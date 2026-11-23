from core.detectors.device import lock_for, read_boxes

import numpy as np
from ultralytics import YOLO

# COCO ids the person model also knows. Asking for them in the same pass costs next to nothing,
# against a second model (YOLOv8l: about twice the person model's time) for vehicles alone.
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
BAG_CLASSES = {24: "backpack", 26: "handbag", 28: "suitcase"}       # unattended-bag alerts


class HumanDetector:
    def __init__(self, model_path: str, conf_threshold: float = 0.5, device: str = "cpu",
                 imgsz: int | None = None):
        self.model = YOLO(model_path)
        self.imgsz = imgsz
        self.conf_threshold = conf_threshold
        self.device = device
        self._lock = lock_for(device)   # one model instance is shared by all cameras

    def detect(self, frame: np.ndarray):
        return self.detect_with_vehicles(frame, vehicles=False)[0]

    def detect_with_vehicles(self, frame: np.ndarray, vehicles: bool = True):
        """One pass: (people as [([x1, y1, x2, y2], conf, 0)], vehicles as VehicleDetector returns them)."""
        people, cars, _ = self.detect_scene(frame, vehicles=vehicles, bags=False)
        return people, cars

    def detect_scene(self, frame: np.ndarray, vehicles: bool = True, bags: bool = False):
        """One pass: people, vehicles and (optionally) bags, all from the person model."""
        classes = [0, *(VEHICLE_CLASSES if vehicles else ()), *(BAG_CLASSES if bags else ())]
        with self._lock:
            results = self.model(frame, conf=self.conf_threshold, classes=classes, verbose=False, device=self.device,
                                 **({"imgsz": self.imgsz} if self.imgsz else {}))
            boxes = read_boxes(results)                  # tensor reads are GPU work: keep them in the lock
        people = [([x1, y1, x2, y2], conf, 0) for x1, y1, x2, y2, conf, cls in boxes if cls == 0]
        cars = [{"bbox": (x1, y1, x2, y2), "score": conf, "class_id": cls, "class_name": VEHICLE_CLASSES[cls]}
                for x1, y1, x2, y2, conf, cls in boxes if cls in VEHICLE_CLASSES]
        found_bags = [{"bbox": (x1, y1, x2, y2), "score": conf, "class_id": cls, "class_name": BAG_CLASSES[cls]}
                      for x1, y1, x2, y2, conf, cls in boxes if cls in BAG_CLASSES]
        return people, cars, found_bags
