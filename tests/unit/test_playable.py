"""browser_playable: DVR recordings (mp4v) get a cached H.264 copy; H.264 passes through."""

import shutil

import cv2
import numpy as np
import pytest

from backend.services import playable


def _clip(path, fourcc, n=12):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), 8, (160, 120))
    if not w.isOpened():
        pytest.skip(f"this OpenCV cannot write {fourcc}")
    for i in range(n):
        w.write(np.full((120, 160, 3), i * 15, np.uint8))
    w.release()
    return path


def _codec(path):
    return playable._fourcc(path)


@pytest.mark.parametrize("use_ffmpeg", [True, False])
def test_dvr_recording_gets_a_cached_h264_copy(tmp_path, monkeypatch, use_ffmpeg):
    if use_ffmpeg and not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    if not use_ffmpeg:
        monkeypatch.setattr(playable, "_with_ffmpeg", lambda src, dst: False)    # the OpenCV fallback
    src = _clip(tmp_path / "091500_cam.mp4", "mp4v")
    out = playable.browser_playable(src)
    assert out.name == "091500_cam.web.mp4" and _codec(out) in playable.BROWSER_CODECS
    assert _codec(src) not in playable.BROWSER_CODECS                  # the original is untouched
    mtime = out.stat().st_mtime
    assert playable.browser_playable(src) == out and out.stat().st_mtime == mtime   # cached
    assert not list(tmp_path.glob("*.tmp.mp4"))


def test_h264_and_other_files_pass_through(tmp_path):
    h264 = _clip(tmp_path / "a.mp4", "avc1")
    assert playable.browser_playable(h264) == h264
    jpg = tmp_path / "x.jpg"
    jpg.write_bytes(b"\xff\xd8")
    assert playable.browser_playable(jpg) == jpg


def test_failed_conversion_serves_the_original(tmp_path, monkeypatch):
    src = _clip(tmp_path / "b.mp4", "mp4v")
    monkeypatch.setattr(playable, "_with_ffmpeg", lambda src, dst: False)
    monkeypatch.setattr(playable, "_with_opencv", lambda src, dst: False)
    assert playable.browser_playable(src) == src
    assert not list(tmp_path.glob("*.web.mp4*"))
