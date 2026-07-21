"""
AI Smart Surveillance System (Ai-SSS) v5.0
============================================
Production Architecture — Pipeline-based Entrypoint

Usage:
    python main.py                       # Single camera (config.yaml)
    python main.py --video path/to.mp4   # Video file
    python main.py --multi               # All enabled cameras (cameras.yaml)
    python main.py --multi --no-display  # Headless multi-camera
"""

import argparse
import os
import threading

import cv2

from core.app.factory import build_pipeline
from core.runtime import run_camera_loop
from paths import CONFIG_YAML, EVIDENCE_DIR, ROOT
from utils.config import load_cameras_config, load_yaml, expand_env, get_camera_geo
from utils.media import resolve_source
from utils.system import logger

cv2.setNumThreads(0)


def _resolve_camera_index(cfg):
    env_index = os.getenv("CAMERA_INDEX")
    if env_index:
        try:
            return int(env_index)
        except ValueError:
            return env_index
    return expand_env(cfg.get("camera_index", 0))


def _start_camera_thread(cam_cfg, cfg, base_dir, show_window):
    cam_id = cam_cfg["id"]
    cam_loc = cam_cfg.get("location", cam_id)
    cam_name = cam_cfg.get("name", cam_id)
    cam_lat = cam_cfg.get("lat")
    cam_lng = cam_cfg.get("lng")
    source = resolve_source(cam_cfg.get("source", 0))
    fps = cam_cfg.get("fps_limit", cfg.get("target_fps", 30))

    # Wire ONVIF PTZ if configured for this camera
    if cam_cfg.get("onvif_host"):
        try:
            from backend.services.ptz import configure_onvif
            configure_onvif(
                cam_id,
                host=str(cam_cfg["onvif_host"]),
                username=str(cam_cfg.get("onvif_user") or "admin"),
                password=str(cam_cfg.get("onvif_pass") or ""),
                profile_token=cam_cfg.get("onvif_profile") or "Profile_1",
            )
            logger.info(f"ONVIF PTZ configured for {cam_id}")
        except Exception as e:
            logger.warning(f"ONVIF setup skipped for {cam_id}: {e}")

    pipeline, criminal_names, _ = build_pipeline(cfg, base_dir, camera_location=cam_loc)

    def worker():
        run_camera_loop(
            pipeline=pipeline,
            criminal_names=criminal_names,
            source=source,
            camera_id=cam_id,
            camera_location=cam_loc,
            camera_name=cam_name,
            camera_lat=cam_lat,
            camera_lng=cam_lng,
            target_fps=fps,
            show_window=show_window,
            window_title=f"AI-SSS — {cam_name}",
        )

    t = threading.Thread(target=worker, name=f"camera-{cam_id}", daemon=True)
    t.start()
    return t


def main():
    parser = argparse.ArgumentParser(description="AI Smart Surveillance System v5.0")
    parser.add_argument("--video", type=str, default="", help="Path to video file.")
    parser.add_argument("--multi", action="store_true", help="Run all enabled cameras from cameras.yaml.")
    parser.add_argument("--no-display", action="store_true", help="Headless mode (no OpenCV windows).")
    args = parser.parse_args()
    base_dir = str(ROOT)

    cfg = load_yaml(str(CONFIG_YAML))

    for d in ["criminals", "weapons", "suspicious"]:
        os.makedirs(EVIDENCE_DIR / d, exist_ok=True)

    show_window = not args.no_display and os.getenv("HEADLESS", "false").lower() != "true"
    target_fps = cfg.get("target_fps", 30)

    if args.multi:
        cameras = load_cameras_config(base_dir)
        if not cameras:
            logger.error("No enabled cameras in config/cameras.yaml")
            return
        logger.info(f"Starting multi-camera mode: {len(cameras)} camera(s)")
        threads = [_start_camera_thread(c, cfg, base_dir, show_window) for c in cameras]
        try:
            while any(t.is_alive() for t in threads):
                threading.Event().wait(0.5 if show_window else 1.0)
        except KeyboardInterrupt:
            pass
        cv2.destroyAllWindows()
        return

    if args.video:
        source = args.video
        camera_id = "video_0"
        geo = get_camera_geo(base_dir, camera_id)
    else:
        source = _resolve_camera_index(cfg)
        camera_id = "cam_0"
        geo = get_camera_geo(base_dir, camera_id)

    camera_location = geo.get("location", cfg.get("camera_location", "Camera_1"))
    camera_name = geo.get("name", camera_location)
    camera_lat = geo.get("lat")
    camera_lng = geo.get("lng")

    pipeline, criminal_names, camera_location = build_pipeline(
        cfg, base_dir, camera_location=camera_location,
    )
    logger.info("System started — press Q to quit, T for thermal, S for stats")
    if camera_lat and camera_lng:
        logger.info(f"Camera GPS: {camera_lat}, {camera_lng}")

    run_camera_loop(
        pipeline=pipeline,
        criminal_names=criminal_names,
        source=source,
        camera_id=camera_id,
        camera_location=camera_location,
        camera_name=camera_name,
        camera_lat=camera_lat,
        camera_lng=camera_lng,
        target_fps=target_fps,
        show_window=show_window,
    )

    stats = pipeline.get_stats()
    logger.info(f"Final pipeline stats: {stats}")
    logger.info("System stopped")


if __name__ == "__main__":
    main()

