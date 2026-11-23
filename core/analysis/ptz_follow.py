"""PTZ follow-the-target: keep a critical subject (watchlist match, armed person, cross-camera
target) in the middle of a PTZ camera's picture.

The pipeline only computes the move; the backend sends it to the camera (ONVIF ContinuousMove)
and only while an operator has switched "Follow target" on for that camera (Live page / PTZ
panel). Commands go out at most `rate_hz` times a second; when the target has been out of view for
`lost_seconds` the camera stops, and after `home_seconds` it returns to its home position.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple

logger = logging.getLogger("HumanAnalysis")


def follow_command(box, frame_shape, deadband: float = 0.12, gain: float = 0.8,
                   min_height: float = 0.25, max_height: float = 0.7) -> Tuple[float, float, float]:
    """(pan, tilt, zoom) velocities in [-1, 1] that bring `box` (x1, y1, x2, y2) to the centre at a
    comfortable size. ONVIF convention: pan + = right, tilt + = up, zoom + = in."""
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = box
    ex = ((x1 + x2) / 2 - w / 2) / (w / 2)
    ey = ((y1 + y2) / 2 - h / 2) / (h / 2)
    clamp = lambda v: max(-1.0, min(1.0, v))                       # noqa: E731
    pan = 0.0 if abs(ex) < deadband else clamp(gain * ex)
    tilt = 0.0 if abs(ey) < deadband else clamp(-gain * ey)
    frac = (y2 - y1) / h
    zoom = 0.0
    if pan == 0 and tilt == 0:                     # zoom only once centred, or the target leaves the frame
        zoom = 0.3 if frac < min_height else -0.3 if frac > max_height else 0.0
    return round(pan, 3), round(tilt, 3), round(zoom, 3)


class PtzFollower:
    """Per camera: chooses the subject, rate-limits commands and posts them to the backend."""

    def __init__(self, camera_id: str, rate_hz: float = 3.0, lost_seconds: float = 3.0, home_seconds: float = 30.0,
                 send=None):
        self.camera_id = camera_id
        self.min_gap = 1.0 / max(rate_hz, 0.1)
        self.lost_seconds = lost_seconds
        self.home_seconds = home_seconds
        self._send = send or _post
        self._last_cmd = float("-inf")
        self._last_seen: Optional[float] = None
        self._moving = False
        self._homed = True
        self._off_until = 0.0                      # backend said follow is off: ask again later

    @staticmethod
    def pick_target(ctx) -> Optional[tuple]:
        """Box of the most important subject in view: weapon > watchlist face > cross-camera target."""
        boxes = {t.track_id: tuple(t.to_ltrb()) for t in getattr(ctx, "tracks", []) if t.is_confirmed()}
        for tid in list(getattr(ctx, "confirmed_weapons", {}) or {}):
            if tid in boxes:
                return boxes[tid]
        for tid in list(getattr(ctx, "criminal_ids", set()) or set()) + list(getattr(ctx, "tracked", {}) or {}):
            if tid in boxes:
                return boxes[tid]
        return None

    def update(self, ctx, now: Optional[float] = None) -> Optional[dict]:
        now = time.monotonic() if now is None else now
        if now < self._off_until:
            return None
        box = self.pick_target(ctx)
        cmd = None
        if box is not None:
            self._last_seen = now
            self._homed = False
            pan, tilt, zoom = follow_command(box, ctx.frame.shape)
            if (pan or tilt or zoom) and now - self._last_cmd >= self.min_gap:
                cmd = {"action": "move", "pan": pan, "tilt": tilt, "zoom": zoom}
                self._moving = True
            elif not (pan or tilt or zoom) and self._moving:
                cmd = {"action": "stop"}
                self._moving = False
        elif self._last_seen is not None:
            gone = now - self._last_seen
            if self._moving and gone >= self.lost_seconds:
                cmd = {"action": "stop"}
                self._moving = False
            elif not self._homed and gone >= self.home_seconds:
                cmd = {"action": "home"}
                self._homed = True
        if cmd:
            self._last_cmd = now
            self._send(self.camera_id, cmd, self._follow_off)
        return cmd

    def _follow_off(self) -> None:
        """The backend said follow is off for this camera: stay quiet for a while."""
        self._off_until = time.monotonic() + 10.0
        self._moving = False


def _post(camera_id: str, cmd: dict, on_off=None) -> None:
    """Fire-and-forget to the backend; `on_off` runs when it answers that follow is switched off."""
    from utils.alerts.event_publisher import BACKEND_URL, _headers

    def go():
        try:
            import httpx
            r = httpx.post(f"{BACKEND_URL}/api/v1/vms/ptz/{camera_id}/track", json=cmd, headers=_headers(), timeout=2.0)
            if r.status_code < 400 and r.json().get("following") is False and on_off:
                on_off()
        except Exception as e:  # noqa: BLE001
            logger.debug("PTZ follow post failed: %s", e)

    threading.Thread(target=go, daemon=True).start()
