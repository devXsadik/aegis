"""Resilient video capture for webcams, RTSP IP cameras, and files."""

from __future__ import annotations

import os
import time
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import cv2

logger = logging.getLogger("HumanAnalysis")

class ThreadedCamera:
    """
    Continuously reads frames in a background thread.
    This prevents OpenCV's internal buffer from accumulating old frames
    when the ML pipeline runs slower than the camera's framerate,
    completely eliminating live streaming lag.
    """
    def __init__(self, cap):
        self.cap = cap
        self.ret, self.frame = self.cap.read()
        self.stopped = False
        self.new_frame_event = threading.Event()
        self.new_frame_event.set()
        
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while not self.stopped:
            ret, frame = self.cap.read()
            if not ret:
                self.ret = False
                self.stopped = True
                self.new_frame_event.set()
                break
            self.ret = ret
            self.frame = frame
            self.new_frame_event.set()

    def read(self):
        # Wait up to 2 seconds for a new frame
        self.new_frame_event.wait(timeout=2.0)
        self.new_frame_event.clear()
        if self.stopped and not self.ret:
            return False, None
        return self.ret, self.frame

    def release(self):
        self.stopped = True
        self.new_frame_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.cap.release()

    def isOpened(self):
        return self.cap.isOpened() and not self.stopped
    
    def set(self, prop, value):
        return self.cap.set(prop, value)
    
    def get(self, prop):
        return self.cap.get(prop)


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
    options = []
    if os.getenv("RTSP_TRANSPORT", "tcp").lower() == "tcp":
        options.append("rtsp_transport;tcp")
    
    # Increase timeouts for slow IP cameras (microseconds)
    options.append("stimeout;10000000")  # 10 sec for RTSP
    options.append("timeout;10000000")   # 10 sec for HTTP
    
    # Reduce latency for IP cameras by disabling FFMPEG buffering
    options.append("fflags;nobuffer")
    options.append("flags;low_delay")
    options.append("strict;experimental")
    
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "|".join(options)


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
        # Force FFMPEG backend for network streams to respect timeout options
        if is_network:
            cap = cv2.VideoCapture(resolved, cv2.CAP_FFMPEG)
        else:
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
            return ThreadedCamera(cap)
        cap.release()
        logger.warning(f"Open attempt {attempt}/{max_retries} failed for: {resolved}")
        time.sleep(retry_delay)

    raise RuntimeError(f"Cannot open video source after {max_retries} attempts: {resolved}")


def read_frame_with_reconnect(cap, source, max_retries: int = 10):
    """Read a frame; reconnect on failure."""
    import cv2

    is_video_file = isinstance(source, str) and source.lower().endswith(('.mp4', '.avi', '.mkv', '.mov'))

    for _ in range(max_retries):
        ret, frame = cap.read()
        if ret and frame is not None:
            return cap, frame
        if is_video_file:
            return cap, None
        logger.warning("Frame read failed — reconnecting...")
        try:
            cap.release()
        except Exception:
            pass
        time.sleep(1.0)
        cap = open_capture(source, max_retries=3, retry_delay=1.0)
    return cap, None
