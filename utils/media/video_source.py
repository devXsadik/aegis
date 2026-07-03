"""Resilient video capture for webcams, RTSP IP cameras, and files."""

from __future__ import annotations

import os
import time
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import cv2

logger = logging.getLogger("HumanAnalysis")


def resolve_source(source):
    """Expand env vars in source strings, e.g. ${RTSP_GATE_1}."""
    if not isinstance(source, str):
        return source
    if source.startswith("${") and source.endswith("}"):
        env_name = source[2:-1]
        return os.getenv(env_name, source)
    if source.startswith("env:"):
        return os.getenv(source[4:], source)
    return os.path.expandvars(source)


def configure_rtsp_options():
    """Prefer TCP transport for RTSP streams (more reliable on most networks)."""
    if os.getenv("RTSP_TRANSPORT", "tcp").lower() == "tcp":
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


def open_capture(source, max_retries: int = 5, retry_delay: float = 2.0):
    """Open a video source with retries (important for IP cameras)."""
    import cv2

    configure_rtsp_options()
    resolved = resolve_source(source)
    is_network = isinstance(resolved, str) and (
        resolved.startswith("rtsp://")
        or resolved.startswith("http://")
        or resolved.startswith("https://")
    )

    for attempt in range(1, max_retries + 1):
        cap = cv2.VideoCapture(resolved)
        if is_network:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if cap.isOpened():
            if is_network:
                ret, _ = cap.read()
                if not ret:
                    cap.release()
                    logger.warning(f"Open attempt {attempt}/{max_retries} failed for: {resolved}")
                    time.sleep(retry_delay)
                    continue
            logger.info(f"Opened video source: {resolved}")
            return cap
        cap.release()
        logger.warning(f"Open attempt {attempt}/{max_retries} failed for: {resolved}")
        time.sleep(retry_delay)

    raise RuntimeError(f"Cannot open video source after {max_retries} attempts: {resolved}")


def read_frame_with_reconnect(cap, source, max_retries: int = 10):
    """Read a frame; reconnect on failure."""
    import cv2

    for _ in range(max_retries):
        ret, frame = cap.read()
        if ret and frame is not None:
            return cap, frame
        logger.warning("Frame read failed — reconnecting...")
        try:
            cap.release()
        except Exception:
            pass
        time.sleep(1.0)
        cap = open_capture(source, max_retries=3, retry_delay=1.0)
    return cap, None
