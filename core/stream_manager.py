"""
Multi-Camera Stream Manager
Manages concurrent video streams from multiple sources with reconnection
"""

import cv2
import threading
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CameraFeed:
    camera_id: str
    name: str
    uri: str
    location: str
    lat: float
    lng: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    active: bool = True
    username: str = ""
    password: str = ""


class StreamManager:
    def __init__(self):
        self.feeds: Dict[str, CameraFeed] = {}
        self.captures: Dict[str, cv2.VideoCapture] = {}
        self.locks: Dict[str, threading.Lock] = {}
        self.last_frames: Dict[str, object] = {}
        self.running: Dict[str, bool] = {}

        self._start_times: Dict[str, float] = {}
        self._last_frame_times: Dict[str, float] = {}
        self._reconnect_attempts: Dict[str, int] = {}
        self._resolutions: Dict[str, tuple] = {}
        self._frame_counts: Dict[str, int] = {}
        self._fps_start_times: Dict[str, float] = {}
        self._frame_processors: List[Callable] = []

    def add_camera(self, feed: CameraFeed):
        self.feeds[feed.camera_id] = feed
        self.locks[feed.camera_id] = threading.Lock()
        self.running[feed.camera_id] = False
        self._reconnect_attempts[feed.camera_id] = 0
        self._frame_counts[feed.camera_id] = 0

    def remove_camera(self, camera_id: str):
        self.stop_stream(camera_id)
        self.feeds.pop(camera_id, None)
        self.locks.pop(camera_id, None)
        self.last_frames.pop(camera_id, None)
        self.running.pop(camera_id, None)
        self._start_times.pop(camera_id, None)
        self._last_frame_times.pop(camera_id, None)
        self._reconnect_attempts.pop(camera_id, None)
        self._resolutions.pop(camera_id, None)
        self._frame_counts.pop(camera_id, None)
        self._fps_start_times.pop(camera_id, None)

    def start_stream(self, camera_id: str) -> bool:
        if camera_id not in self.feeds:
            return False
        if self.running.get(camera_id, False):
            return True

        feed = self.feeds[camera_id]
        cap = cv2.VideoCapture(feed.uri if isinstance(feed.uri, str) else int(feed.uri))
        if not cap.isOpened():
            print(f"Stream {camera_id}: failed to open {feed.uri}")
            return False

        self.captures[camera_id] = cap
        self.running[camera_id] = True
        self._start_times[camera_id] = time.time()
        self._reconnect_attempts[camera_id] = 0
        self._frame_counts[camera_id] = 0
        self._fps_start_times[camera_id] = time.time()

        thread = threading.Thread(target=self._capture_loop, args=(camera_id,), daemon=True)
        thread.start()
        print(f"Stream {camera_id}: started")
        return True

    def stop_stream(self, camera_id: str):
        self.running[camera_id] = False
        cap = self.captures.pop(camera_id, None)
        if cap:
            cap.release()

    def start_all(self):
        for cid in self.feeds:
            self.start_stream(cid)

    def stop_all(self):
        for cid in list(self.running.keys()):
            self.stop_stream(cid)

    def get_frame(self, camera_id: str):
        with self.locks.get(camera_id, threading.Lock()):
            return self.last_frames.get(camera_id)

    def get_all_frames(self) -> Dict[str, object]:
        frames = {}
        for cid in self.feeds:
            frame = self.get_frame(cid)
            if frame is not None:
                frames[cid] = frame
        return frames

    def get_health(self, camera_id: str) -> Optional[Dict]:
        if camera_id not in self.feeds:
            return None
        feed = self.feeds[camera_id]
        now = time.time()
        uptime = now - self._start_times.get(camera_id, now) if self.running.get(camera_id, False) else 0
        last_frame_age = now - self._last_frame_times.get(camera_id, now) if self._last_frame_times.get(camera_id) else None
        res = self._resolutions.get(camera_id, (0, 0))
        return {
            "camera_id": camera_id,
            "connected": self.running.get(camera_id, False),
            "uptime_seconds": round(uptime, 1),
            "last_frame_age_seconds": round(last_frame_age, 1) if last_frame_age is not None else None,
            "fps": round(feed.fps, 1),
            "width": res[1],
            "height": res[0],
            "reconnect_count": self._reconnect_attempts.get(camera_id, 0),
            "total_frames": self._frame_counts.get(camera_id, 0),
        }

    def get_health_all(self) -> Dict[str, Dict]:
        return {cid: self.get_health(cid) for cid in self.feeds}

    def add_frame_processor(self, processor: Callable):
        self._frame_processors.append(processor)

    def _capture_loop(self, camera_id: str):
        cap = self.captures[camera_id]
        feed = self.feeds[camera_id]
        frame_count = 0
        fps_start = time.time()

        while self.running.get(camera_id, False):
            ret, frame = cap.read()
            if not ret:
                attempts = self._reconnect_attempts.get(camera_id, 0) + 1
                self._reconnect_attempts[camera_id] = attempts
                delay = min(2 ** attempts, 30)
                print(f"Stream {camera_id}: read failed (attempt {attempts}), reconnecting in {delay}s...")
                cap.release()
                time.sleep(delay)
                cap = cv2.VideoCapture(feed.uri if isinstance(feed.uri, str) else int(feed.uri))
                self.captures[camera_id] = cap
                if cap.isOpened():
                    self._reconnect_attempts[camera_id] = 0
                    print(f"Stream {camera_id}: reconnected")
                continue

            self._reconnect_attempts[camera_id] = 0
            frame_count += 1
            self._frame_counts[camera_id] = self._frame_counts.get(camera_id, 0) + 1
            now = time.time()

            with self.locks[camera_id]:
                self.last_frames[camera_id] = frame
                self._last_frame_times[camera_id] = now
                if self._resolutions.get(camera_id) is None:
                    self._resolutions[camera_id] = frame.shape[:2]

            elapsed = now - fps_start
            if elapsed >= 1.0:
                feed.fps = frame_count / elapsed
                frame_count = 0
                fps_start = now
                self._fps_start_times[camera_id] = fps_start

            for processor in self._frame_processors:
                try:
                    processor(camera_id, frame)
                except Exception as e:
                    print(f"Stream {camera_id}: processor error: {e}")
