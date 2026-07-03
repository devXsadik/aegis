"""Per-camera surveillance loop for single- and multi-camera operation."""

import os
import time
import logging
from typing import Optional

import cv2

from core.visualization.hud import render_full_hud
from utils.media import open_capture, read_frame_with_reconnect
from utils.alerts import publish_heartbeat
from utils.system import FrameSkipper, ResourceMonitor

logger = logging.getLogger("HumanAnalysis")


def run_camera_loop(
    pipeline,
    criminal_names,
    source,
    camera_id: str,
    camera_location: str,
    target_fps: int = 30,
    show_window: bool = True,
    window_title: Optional[str] = None,
    camera_name: str = "",
    camera_lat: Optional[float] = None,
    camera_lng: Optional[float] = None,
):
    """Run the CV pipeline on one video source until quit or stream end."""
    cap = open_capture(source)
    frame_skipper = FrameSkipper(target_fps=target_fps)
    resource_monitor = ResourceMonitor()
    perf_enabled = os.getenv("PERF_MONITOR", "false").lower() == "true"

    start_time = time.time()
    thermal_mode = False
    last_heartbeat = 0.0
    heartbeat_interval = float(os.getenv("HEARTBEAT_INTERVAL", "5"))
    fps_counter = 0
    fps_window_start = time.time()
    current_fps = 0.0

    title = window_title or f"AI-SSS — {camera_location or camera_id}"
    logger.info(f"Camera worker started: {camera_id} @ {camera_location}")

    while True:
        cap, frame = read_frame_with_reconnect(cap, source)
        if frame is None:
            logger.error(f"Stream lost for {camera_id}")
            break

        if not frame_skipper.should_process():
            if show_window:
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
            continue

        if thermal_mode:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)

        ctx = pipeline.run(
            frame,
            camera_id=camera_id,
            camera_location=camera_location,
            camera_name=camera_name,
            camera_lat=camera_lat,
            camera_lng=camera_lng,
        )

        fps_counter += 1
        elapsed = time.time() - fps_window_start
        if elapsed >= 1.0:
            current_fps = fps_counter / elapsed
            fps_counter = 0
            fps_window_start = time.time()

        now = time.time()
        if now - last_heartbeat >= heartbeat_interval:
            publish_heartbeat(
                camera_id=camera_id,
                camera_location=camera_location,
                fps=round(current_fps, 1),
                threat_score=ctx.threat_score,
                frame_number=ctx.frame_number,
            )
            last_heartbeat = now

        if show_window:
            perf_stats = resource_monitor.get_stats() if perf_enabled else None
            display = render_full_hud(
                frame, ctx, start_time, criminal_names, perf_stats, thermal_mode,
            )
            cv2.imshow(title, display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("t"):
                thermal_mode = not thermal_mode
            elif key == ord("s"):
                stats = pipeline.get_stats()
                logger.info(f"[{camera_id}] Pipeline stats: {stats}")

    cap.release()
    if show_window:
        try:
            cv2.destroyWindow(title)
        except Exception:
            pass
    logger.info(f"Camera worker stopped: {camera_id}")


