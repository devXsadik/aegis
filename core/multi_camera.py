"""
Multi-Camera Manager for Phase 2
Handles multiple RTSP streams, camera zoning, and load balancing
"""
import cv2
import threading
import time
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class CameraConfig:
    id: str
    name: str
    source: str  # RTSP URL or camera index
    location: str
    zone: str = "default"
    enabled: bool = True
    conf_threshold: float = 0.5
    weapon_conf_threshold: float = 0.4


class CameraStream:
    """Manages a single camera stream with reconnect logic"""

    def __init__(self, config: CameraConfig):
        self.config = config
        self.cap = None
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.running = False
        self.thread = None
        self.last_frame_time = 0
        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()

    def start(self):
        """Start capturing from this camera"""
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        return self

    def _capture_loop(self):
        """Background thread for frame capture"""
        while self.running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    self._connect()

                ret, frame = self.cap.read()
                if not ret:
                    print(f"Camera {self.config.id}: Failed to read frame, reconnecting...")
                    self.cap.release()
                    self.cap = None
                    time.sleep(2)
                    continue

                # Update FPS
                self.frame_count += 1
                now = time.time()
                if now - self.last_fps_time >= 1.0:
                    self.fps = self.frame_count
                    self.frame_count = 0
                    self.last_fps_time = now

                with self.frame_lock:
                    self.latest_frame = frame
                    self.last_frame_time = now

            except Exception as e:
                print(f"Camera {self.config.id} error: {e}")
                time.sleep(1)

    def _connect(self):
        """Connect to camera source"""
        print(f"Connecting to camera {self.config.id}: {self.config.source}")
        if self.cap:
            self.cap.release()

        source = self.config.source
        if source.isdigit():
            source = int(source)

        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera {self.config.id}")

    def get_frame(self) -> Optional[tuple]:
        """Get the latest frame (copy)"""
        with self.frame_lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy(), self.last_frame_time
        return None, 0

    def stop(self):
        """Stop capturing"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        if self.cap:
            self.cap.release()


class MultiCameraManager:
    """Manages multiple camera streams"""

    def __init__(self):
        self.cameras: Dict[str, CameraStream] = {}
        self._lock = threading.Lock()

    def add_camera(self, config: CameraConfig) -> CameraStream:
        """Add a camera to the manager"""
        with self._lock:
            stream = CameraStream(config)
            self.cameras[config.id] = stream
            if config.enabled:
                stream.start()
            return stream

    def get_camera(self, camera_id: str) -> Optional[CameraStream]:
        """Get a specific camera stream"""
        return self.cameras.get(camera_id)

    def get_all_frames(self) -> Dict[str, tuple]:
        """Get latest frames from all cameras"""
        frames = {}
        for cam_id, stream in self.cameras.items():
            if stream.config.enabled:
                frame, timestamp = stream.get_frame()
                if frame is not None:
                    frames[cam_id] = (frame, timestamp, stream.config)
        return frames

    def stop_all(self):
        """Stop all camera streams"""
        for stream in self.cameras.values():
            stream.stop()
