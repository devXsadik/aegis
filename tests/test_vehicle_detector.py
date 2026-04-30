"""
Tests for Vehicle Detector Module
"""
import pytest
import numpy as np
from core.vehicle_detector import VehicleDetector, VehicleTracker


class TestVehicleDetector:
    def test_init(self, tmp_path):
        model_path = tmp_path / "test_model.pt"
        model_path.write_bytes(b"fake model")
        
        with patch('core.vehicle_detector.YOLO') as mock_yolo:
            detector = VehicleDetector(str(model_path), conf_threshold=0.6)
            assert detector.conf_threshold == 0.6

    def test_get_class_name(self):
        detector = VehicleDetector.__new__(VehicleDetector)
        assert detector._get_class_name(2) == 'car'
        assert detector._get_class_name(3) == 'motorcycle'
        assert detector._get_class_name(5) == 'bus'
        assert detector._get_class_name(7) == 'truck'
        assert detector._get_class_name(99) == 'vehicle'


class TestVehicleTracker:
    def test_init(self):
        tracker = VehicleTracker()
        assert tracker.next_id == 1
        assert len(tracker.tracks) == 0

    def test_update(self):
        tracker = VehicleTracker()
        detections = [
            {'bbox': [0, 0, 100, 100], 'score': 0.9, 'class_id': 2, 'class_name': 'car'}
        ]
        
        tracks = tracker.update(detections, np.random.rand(480, 640, 3))
        assert len(tracks) == 1
        assert tracker.next_id == 2
