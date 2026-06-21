"""
AI Smart Surveillance System (Ai-SSS) v5.0
============================================
Production Architecture — Pipeline-based Entrypoint

Refactored from 725-line monolith into modular pipeline stages.
Each stage (detection, tracking, recognition, behavior, analytics, output)
is independently configurable and timed.

Usage:
    python main.py                       # Live camera
    python main.py --video path/to.mp4   # Video file
"""

import cv2
import yaml
import time
import os
import argparse
import threading
import logging

from core import HumanDetector, WeaponDetector, HumanTracker, FaceAnalyzer, PoseAnalyzer
from core.face_recognizer_db import FaceRecognizerDB
from core.anpr import LicensePlateRecognizer, LicensePlateDatabase
from core.vehicle_detector import VehicleDetector, VehicleTracker
from core.anomaly_detector import AnomalyDetector
from core.pipeline import SurveillancePipeline
from core.pipeline.stages import (
    DetectionStage, TrackingStage, RecognitionStage,
    BehaviorStage, AnalyticsStage, OutputStage,
)
from core.visualization.hud import render_full_hud, run_boot_sequence
from utils import logger
from utils.alerts import AlertOrchestrator
from utils.performance import FrameSkipper, ResourceMonitor


def play_alarm():
    """Plays an alarm sound on MacOS."""
    def _play():
        os.system("afplay /System/Library/Sounds/Ping.aiff")
    threading.Thread(target=_play, daemon=True).start()


def build_pipeline(cfg, base_dir):
    """Build the surveillance pipeline from config."""
    model_dir = os.path.join(base_dir, cfg.get("model_dir", "models"))
    conf_threshold = cfg.get("confidence_threshold", 0.5)
    weapon_conf = cfg.get("weapon_conf_threshold", 0.4)
    face_tolerance = cfg.get("face_tolerance", 0.45)
    camera_location = cfg.get("camera_location", "Camera_1")
    criminal_names = set(cfg.get("criminal_names", []))

    human_model_path = os.path.join(model_dir, cfg.get("human_model", "yolov8x.pt"))
    weapon_model_path = os.path.join(model_dir, cfg.get("weapon_model", "weapon_yolo.pt"))
    vehicle_model_path = os.path.join(model_dir, "yolov8l.pt")

    if not os.path.exists(human_model_path):
        raise FileNotFoundError(f"Human model not found: {human_model_path}")

    # --- Initialize components ---
    human_detector = HumanDetector(human_model_path, conf_threshold)

    weapon_detector = None
    if os.path.exists(weapon_model_path):
        try:
            weapon_detector = WeaponDetector(weapon_model_path, weapon_conf)
            logger.info("Weapon detector: ENABLED")
        except Exception as e:
            logger.warning(f"Weapon detector DISABLED: {e}")

    vehicle_detector = None
    if os.path.exists(vehicle_model_path):
        try:
            vehicle_detector = VehicleDetector(vehicle_model_path, conf_threshold)
            logger.info("Vehicle detector: ENABLED")
        except Exception as e:
            logger.warning(f"Vehicle detector DISABLED: {e}")

    human_tracker = HumanTracker()
    vehicle_tracker = VehicleTracker()
    face_recognizer = FaceRecognizerDB(tolerance=face_tolerance)
    pose_analyzer = PoseAnalyzer()
    anomaly_detector = AnomalyDetector()
    anpr = LicensePlateRecognizer(languages=["en"], gpu=False)
    plate_db = LicensePlateDatabase()
    alert_orchestrator = AlertOrchestrator()

    # --- Build pipeline ---
    pipeline = SurveillancePipeline()

    pipeline.add_stage(DetectionStage(
        human_detector=human_detector,
        vehicle_detector=vehicle_detector,
        weapon_detector=weapon_detector,
    ))

    pipeline.add_stage(TrackingStage(
        human_tracker=human_tracker,
        vehicle_tracker=vehicle_tracker,
    ))

    pipeline.add_stage(RecognitionStage(
        face_recognizer=face_recognizer,
        criminal_names=criminal_names,
        rerecognize_every=cfg.get("rerecognize_every", 30),
    ))

    pipeline.add_stage(BehaviorStage(
        pose_analyzer=pose_analyzer,
        anomaly_detector=anomaly_detector,
        anpr=anpr,
        plate_db=plate_db,
    ))

    pipeline.add_stage(AnalyticsStage())

    pipeline.add_stage(OutputStage(
        alert_orchestrator=alert_orchestrator,
        camera_location=camera_location,
        evidence_throttle_seconds=cfg.get("evidence_throttle_seconds", 10.0),
        alarm_interval_seconds=cfg.get("alarm_interval_seconds", 5.0),
        alarm_callback=play_alarm,
    ))

    return pipeline, criminal_names, camera_location


def main():
    parser = argparse.ArgumentParser(description="AI Smart Surveillance System v5.0")
    parser.add_argument("--video", type=str, default="", help="Path to video file.")
    args = parser.parse_args()
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # --- Load config ---
    config_path = os.path.join(base_dir, "config", "config.yaml")
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    camera_index = cfg.get("camera_index", 0)

    # --- Create evidence dirs ---
    evidence_dir = os.path.join(base_dir, "evidence")
    for d in ["criminals", "weapons", "suspicious"]:
        os.makedirs(os.path.join(evidence_dir, d), exist_ok=True)

    # --- Build pipeline ---
    pipeline, criminal_names, camera_location = build_pipeline(cfg, base_dir)

    # --- Open video source ---
    if args.video:
        cap = cv2.VideoCapture(args.video)
        logger.info(f"Using video file: {args.video}")
    else:
        cap = cv2.VideoCapture(camera_index)
        logger.info(f"Using camera: {camera_index}")

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video source")

    ret, initial_frame = cap.read()
    if ret:
        run_boot_sequence(initial_frame.shape)

    # --- Performance ---
    frame_skipper = FrameSkipper(target_fps=cfg.get("target_fps", 30))
    resource_monitor = ResourceMonitor()
    perf_enabled = os.getenv("PERF_MONITOR", "false").lower() == "true"

    logger.info("✅ System Started — press Q to quit, T for thermal mode")
    start_time = time.time()
    thermal_mode = False

    # --- Main loop ---
    while True:
        ret, frame = cap.read()
        if not ret:
            logger.error("Failed to read frame")
            break

        if not frame_skipper.should_process():
            continue

        if thermal_mode:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)

        # Run full pipeline
        ctx = pipeline.run(frame, camera_id="cam_0", camera_location=camera_location)

        # Render HUD
        perf_stats = resource_monitor.get_stats() if perf_enabled else None
        frame = render_full_hud(
            frame, ctx, start_time, criminal_names, perf_stats, thermal_mode,
        )

        # Display
        cv2.imshow("AI-SSS v5.0", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("t"):
            thermal_mode = not thermal_mode
        elif key == ord("s"):
            # Print pipeline stats
            stats = pipeline.get_stats()
            logger.info(f"Pipeline stats: {stats}")

    cap.release()
    cv2.destroyAllWindows()

    # Print final pipeline stats
    stats = pipeline.get_stats()
    logger.info(f"Final pipeline stats: {stats}")
    logger.info("System Stopped")


if __name__ == "__main__":
    main()
