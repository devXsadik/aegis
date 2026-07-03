"""Tests for camera GPS registry."""

import os
from utils.config import build_camera_registry, get_camera_geo, maps_url


class TestCameraRegistry:
    def test_build_registry_has_gate(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project = os.path.dirname(base)
        registry = build_camera_registry(project)
        assert "gate_1" in registry
        assert registry["gate_1"]["lat"] == 23.8103
        assert registry["gate_1"]["lng"] == 90.4125

    def test_get_camera_geo(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project = os.path.dirname(base)
        geo = get_camera_geo(project, "gate_1")
        assert geo["lat"] == 23.8103
        assert geo["lng"] == 90.4125

    def test_maps_url(self):
        url = maps_url(23.8103, 90.4125)
        assert "google.com/maps" in url
        assert "23.8103" in url

    def test_maps_url_none(self):
        assert maps_url(None, 90.0) is None
