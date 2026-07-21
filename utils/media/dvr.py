"""
Continuous DVR segment recorder — 24/7 rolling video for VMS timeline scrub.

Writes fixed-length MP4 segments under data/recordings/{camera_id}/continuous/
and notifies a callback when each segment closes (for DB indexing + retention).
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

logger = logging.getLogger("HumanAnalysis")


class ContinuousRecorder:
    """Non-blocking continuous segment writer for one camera."""

    def __init__(
        self,
        camera_id: str,
        out_dir: Path,
        *,
        segment_seconds: float = 60.0,
        target_fps: float = 10.0,
        width: int = 960,
        camera_location: str = "",
        on_segment: Optional[Callable[[dict], None]] = None,
    ):
        self.camera_id = camera_id
        self.camera_location = camera_location
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.segment_seconds = max(10.0, float(segment_seconds))
        self.target_fps = max(1.0, float(target_fps))
        self.width = int(width)
        self.on_segment = on_segment

        self._writer: Optional[cv2.VideoWriter] = None
        self._path: Optional[Path] = None
        self._started: Optional[datetime] = None
        self._started_mono = 0.0
        self._frames = 0
        self._last_write = 0.0
        self._frame_interval = 1.0 / self.target_fps
        self._lock = threading.Lock()
        self._thumb: Optional[np.ndarray] = None

    def write(self, frame: np.ndarray) -> None:
        """Accept a BGR frame; may drop frames to honor target_fps."""
        now = time.monotonic()
        if now - self._last_write < self._frame_interval:
            return
        self._last_write = now

        with self._lock:
            img = self._resize(frame)
            if self._writer is None:
                self._open(img)
            if self._writer is None:
                return
            self._writer.write(img)
            self._frames += 1
            if self._frames == 1:
                self._thumb = img.copy()
            if now - self._started_mono >= self.segment_seconds:
                self._close_locked()

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _resize(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w <= self.width:
            return frame
        scale = self.width / w
        return cv2.resize(frame, (self.width, int(h * scale)))

    def _open(self, sample: np.ndarray) -> None:
        h, w = sample.shape[:2]
        day = datetime.utcnow().strftime("%Y%m%d")
        dest = self.out_dir / day
        dest.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%H%M%S")
        self._path = dest / f"{stamp}_{self.camera_id}.mp4"
        self._started = datetime.utcnow()
        self._started_mono = time.monotonic()
        self._frames = 0

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(
            str(self._path), fourcc, self.target_fps, (w, h),
        )
        if not self._writer.isOpened():
            logger.warning("DVR writer failed to open %s — trying AVI/MJPEG", self._path)
            self._path = self._path.with_suffix(".avi")
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self._writer = cv2.VideoWriter(
                str(self._path), fourcc, self.target_fps, (w, h),
            )
        if not self._writer.isOpened():
            logger.error("DVR cannot open video writer for %s", self.camera_id)
            self._writer = None
            self._path = None

    def _close_locked(self) -> None:
        if self._writer is None:
            return
        path = self._path
        started = self._started
        frames = self._frames
        thumb = self._thumb
        self._writer.release()
        self._writer = None
        self._path = None
        self._thumb = None
        self._frames = 0

        if not path or not path.exists() or frames < 2:
            if path and path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
            return

        ended = datetime.utcnow()
        duration = (ended - started).total_seconds() if started else frames / self.target_fps
        digest = _file_sha256(path)
        thumb_path = None
        if thumb is not None:
            tp = path.with_suffix(".jpg")
            cv2.imwrite(str(tp), thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])
            thumb_path = tp

        meta = {
            "camera_id": self.camera_id,
            "camera_location": self.camera_location,
            "started_at": started.isoformat() if started else ended.isoformat(),
            "ended_at": ended.isoformat(),
            "duration_seconds": round(duration, 2),
            "trigger": "continuous",
            "file_path": str(path),
            "file_sha256": digest,
            "frame_count": frames,
            "thumbnail_path": str(thumb_path) if thumb_path else None,
        }
        if self.on_segment:
            try:
                self.on_segment(meta)
            except Exception as e:
                logger.warning("DVR on_segment callback failed: %s", e)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def purge_old_recordings(root: Path, retention_hours: float) -> int:
    """Delete continuous recording files older than retention window."""
    if retention_hours <= 0:
        return 0
    cutoff = time.time() - retention_hours * 3600
    removed = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".mp4", ".avi", ".jpg", ".mjpeg"}:
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed
