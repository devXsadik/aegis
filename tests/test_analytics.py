"""
Tests for Analytics Module
"""
import pytest
import numpy as np
from datetime import datetime, timedelta
from core.analytics import HeatmapGenerator, DwellTimeAnalyzer


class TestHeatmapGenerator:
    def test_init(self):
        hg = HeatmapGenerator(1280, 720, grid_size=50)
        assert hg.w == 1280
        assert hg.h == 720
        assert hg.grid_w == 26  # 1280/50 + 1

    def test_add_detection(self):
        hg = HeatmapGenerator(1280, 720)
        hg.add_detection(640, 360, datetime.utcnow())
        assert hg.heatmap.max() > 0

    def test_get_heatmap_image(self):
        hg = HeatmapGenerator(1280, 720)
        hg.add_detection(640, 360, datetime.utcnow())
        result = hg.get_heatmap_image()
        assert result.shape == (720, 1280, 3)

    def test_get_hotspots(self):
        hg = HeatmapGenerator(1280, 720)
        # Add many detections in same area
        for _ in range(100):
            hg.add_detection(640, 360, datetime.utcnow())
        hotspots = hg.get_hotspots(threshold=0.5)
        assert len(hotspots) > 0
        assert "x" in hotspots[0]
        assert "y" in hotspots[0]


class TestDwellTimeAnalyzer:
    def test_init(self):
        dta = DwellTimeAnalyzer()
        assert dta.dwell_threshold == 300
        assert len(dta.track_data) == 0

    def test_get_movement_pattern_insufficient_data(self):
        dta = DwellTimeAnalyzer()
        result = dta.get_movement_pattern(999)
        assert result["pattern"] == "insufficient_data"

    def test_get_dwell_zones(self):
        dta = DwellTimeAnalyzer()
        now = datetime.utcnow()
        # Simulate a track dwelling for 10 minutes
        points = [
            (now - timedelta(minutes=10), (100, 100)),
            (now - timedelta(minutes=9), (101, 101)),
            (now - timedelta(minutes=8), (102, 102)),
            (now, (105, 105))
        ]
        dta.track_data[1] = points
        zones = dta.get_dwell_zones(1)
        # Would need 5+ minutes to trigger
        assert isinstance(zones, list)
