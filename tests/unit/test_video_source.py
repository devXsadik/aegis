"""Tests for video source resolution."""

from utils.media import resolve_source


class TestResolveSource:
    def test_integer_passthrough(self):
        assert resolve_source(0) == 0

    def test_env_braces(self, monkeypatch):
        monkeypatch.setenv("RTSP_GATE_1", "rtsp://192.168.1.1/stream")
        assert resolve_source("${RTSP_GATE_1}") == "rtsp://192.168.1.1/stream"

    def test_env_prefix(self, monkeypatch):
        monkeypatch.setenv("CAM_URL", "rtsp://cam")
        assert resolve_source("env:CAM_URL") == "rtsp://cam"

    def test_plain_rtsp(self):
        url = "rtsp://user:pass@10.0.0.1:554/stream1"
        assert resolve_source(url) == url

