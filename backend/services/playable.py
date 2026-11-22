"""Recordings the browser can play.

The DVR writes MPEG-4 Part 2 (`mp4v`): cheap to encode on every frame of every camera, but no
browser decodes it. H.264 costs about 3x the CPU per frame, so instead of recording in it, a
segment is converted once, when someone first plays it, and the copy is kept next to the
original (`<name>.web.mp4`, removed with it by retention). The original stays untouched for
evidence: hashes and downloads use it.
"""

import logging
import shutil
import subprocess
import threading
from pathlib import Path

import cv2

logger = logging.getLogger("HumanAnalysis")

BROWSER_CODECS = {"avc1", "h264", "H264", "AVC1", "x264", "X264"}
_locks: dict = {}
_locks_guard = threading.Lock()


def _fourcc(path: Path) -> str:
    cap = cv2.VideoCapture(str(path))
    try:
        code = int(cap.get(cv2.CAP_PROP_FOURCC))
    finally:
        cap.release()
    return "".join(chr((code >> 8 * i) & 0xFF) for i in range(4))


def _with_ffmpeg(src: Path, dst: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    run = subprocess.run(
        [ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", str(src), "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-f", "mp4", str(dst)],
        capture_output=True, text=True, timeout=120,
    )
    if run.returncode != 0:
        logger.warning(f"ffmpeg could not convert {src.name}: {run.stderr.strip()[:200]}")
    return run.returncode == 0


def _with_opencv(src: Path, dst: Path) -> bool:
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 8
    writer = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if writer is None:
                h, w = frame.shape[:2]
                writer = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"avc1"), fps, (w, h))
                if not writer.isOpened():
                    return False
            writer.write(frame)
    finally:
        cap.release()
        if writer is not None:
            writer.release()
    return writer is not None


def browser_playable(path: Path) -> Path:
    """An H.264 version of `path` (converted once, then cached), or `path` itself when it already
    plays in a browser or cannot be converted here."""
    if path.suffix.lower() != ".mp4" or path.name.endswith(".web.mp4") or _fourcc(path) in BROWSER_CODECS:
        return path
    cached = path.with_name(path.stem + ".web.mp4")
    with _locks_guard:
        lock = _locks.setdefault(str(path), threading.Lock())
    with lock:                                    # two viewers of one clip: convert once
        if cached.exists() and cached.stat().st_mtime >= path.stat().st_mtime:
            return cached
        tmp = path.with_name(path.stem + ".web.tmp.mp4")     # OpenCV picks the container from the extension
        try:
            if _with_ffmpeg(src=path, dst=tmp) or _with_opencv(src=path, dst=tmp):
                tmp.replace(cached)
                return cached
        except Exception as e:                    # never fail playback over the conversion
            logger.warning(f"Could not make {path.name} browser-playable: {e}")
        finally:
            tmp.unlink(missing_ok=True)
    return path
