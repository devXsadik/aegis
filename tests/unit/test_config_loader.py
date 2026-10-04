"""Tests for config loader utilities."""

import os
from utils.config import expand_env, load_cameras_config


class TestExpandEnv:
    def test_plain_string(self):
        assert expand_env("hello") == "hello"

    def test_env_var_braces(self, monkeypatch):
        monkeypatch.setenv("RTSP_GATE_1", "rtsp://cam1/stream")
        assert expand_env("${RTSP_GATE_1}") == "rtsp://cam1/stream"

    def test_env_prefix(self, monkeypatch):
        monkeypatch.setenv("MY_CAM", "rtsp://x")
        assert expand_env("env:MY_CAM") == "rtsp://x"

    def test_nested_dict(self, monkeypatch):
        monkeypatch.setenv("FOO", "bar")
        result = expand_env({"source": "${FOO}"})
        assert result["source"] == "bar"


class TestLoadCamerasConfig:
    def test_loads_enabled_cameras(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_root = os.path.dirname(base)
        cameras = load_cameras_config(project_root)
        assert len(cameras) >= 1
        assert all(c.get("enabled", True) for c in cameras)          # disabled ones are filtered out
        ids = [c["id"] for c in cameras]
        assert len(ids) == len(set(ids))

