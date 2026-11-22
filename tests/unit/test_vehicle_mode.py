"""vehicle_detection modes: off, fast (person model, same pass), accurate (YOLOv8l)."""

import numpy as np

from core.pipeline.base import FrameContext
from core.pipeline.stages.detection import DetectionStage
from utils.config import vehicle_mode


def test_vehicle_mode_parses_old_booleans_and_strings():
    assert vehicle_mode({}) == "fast"
    assert vehicle_mode({"vehicle_detection": True}) == "accurate"
    assert vehicle_mode({"vehicle_detection": False}) == "off"
    assert vehicle_mode({"vehicle_detection": " Accurate "}) == "accurate"
    assert vehicle_mode({"vehicle_detection": "nonsense"}) == "fast"


class _People:
    def __init__(self):
        self.calls = []

    def detect(self, frame):
        self.calls.append("detect")
        return [([0, 0, 10, 20], 0.9, 0)]

    def detect_with_vehicles(self, frame):
        self.calls.append("both")
        return [([0, 0, 10, 20], 0.9, 0)], [{"bbox": (5, 5, 50, 30), "score": 0.8, "class_id": 2, "class_name": "car"}]


def _ctx():
    return FrameContext(frame=np.zeros((40, 60, 3), np.uint8))


def test_fast_mode_gets_people_and_vehicles_from_one_pass():
    people = _People()
    ctx = DetectionStage(people, vehicles_from_people=True).process(_ctx())
    assert people.calls == ["both"]
    assert len(ctx.human_detections) == 1 and ctx.vehicle_detections[0]["class_name"] == "car"


def test_without_fast_mode_people_model_does_not_report_vehicles():
    people = _People()
    ctx = DetectionStage(people).process(_ctx())
    assert people.calls == ["detect"] and ctx.vehicle_detections == []
