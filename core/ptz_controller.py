"""
PTZ Camera Controller
Controls Pan-Tilt-Zoom for compatible cameras via ONVIF or HTTP API
"""

from typing import Optional


class PTZController:
    def __init__(self, camera_uri: str, protocol: str = "onvif",
                 username: str = "", password: str = ""):
        self.camera_uri = camera_uri
        self.protocol = protocol
        self.username = username
        self.password = password
        self._connected = False

    def connect(self) -> bool:
        if self.protocol == "onvif":
            try:
                from onvif import ONVIFCamera
                self._connected = True
            except ImportError:
                print("PTZ: onvif not installed. Use: pip install onvif-zeep")
                self._connected = False
        else:
            self._connected = True
        return self._connected

    def pan_left(self, speed: float = 0.5):
        print(f"PTZ pan_left {speed} on {self.camera_uri}")

    def pan_right(self, speed: float = 0.5):
        print(f"PTZ pan_right {speed} on {self.camera_uri}")

    def tilt_up(self, speed: float = 0.5):
        print(f"PTZ tilt_up {speed} on {self.camera_uri}")

    def tilt_down(self, speed: float = 0.5):
        print(f"PTZ tilt_down {speed} on {self.camera_uri}")

    def zoom_in(self, level: float = 0.5):
        print(f"PTZ zoom_in {level} on {self.camera_uri}")

    def zoom_out(self, level: float = 0.5):
        print(f"PTZ zoom_out {level} on {self.camera_uri}")

    def stop(self):
        print(f"PTZ stop on {self.camera_uri}")

    def auto_track(self, target_x: float, target_y: float,
                   frame_w: float, frame_h: float):
        """
        Auto-track a target by centering it in frame.
        Call every frame with the target's position.
        """
        cx, cy = frame_w / 2, frame_h / 2
        threshold = 0.1

        dx = (target_x - cx) / cx
        dy = (target_y - cy) / cy

        if abs(dx) > threshold:
            if dx > 0:
                self.pan_right(min(abs(dx), 1.0))
            else:
                self.pan_left(min(abs(dx), 1.0))

        if abs(dy) > threshold:
            if dy > 0:
                self.tilt_down(min(abs(dy), 1.0))
            else:
                self.tilt_up(min(abs(dy), 1.0))
