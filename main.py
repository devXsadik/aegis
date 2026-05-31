import cv2
import yaml
import time
import os
import argparse
import threading
import random
import json
from datetime import datetime
import numpy as np
from collections import defaultdict

from core import (
    HumanDetector,
    WeaponDetector,
    HumanTracker,
    FaceAnalyzer,
    PoseAnalyzer,
    is_suspicious_behavior,
)
from core.face_recognizer_db import FaceRecognizerDB
from core.anpr import LicensePlateRecognizer, LicensePlateDatabase
from core.vehicle_detector import VehicleDetector, VehicleTracker
from core.cross_camera_tracker import CrossCameraTracker
from core.anomaly_detector import AnomalyDetector
from core.analytics import HeatmapGenerator, DwellTimeAnalyzer
from core.stream_manager import StreamManager, CameraFeed
from utils import logger
from utils.evidence_db import save_evidence_db
from utils.alerts import AlertOrchestrator
from utils.performance import FrameSkipper, ResourceMonitor

# Re-run face recognition every N frames per track ID
RERECOGNIZE_EVERY = 90


def draw_box(frame, x1, y1, x2, y2, label, color):
    """Draw bounding box with label"""
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
    cv2.rectangle(frame, (x1, y1 - lh - 10), (x1 + lw + 10, y1), color, -1)
    cv2.putText(frame, label, (x1 + 5, y1 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    return frame


def draw_sci_fi_box(frame, x1, y1, x2, y2, color, thickness=1, length=20):
    # Draw corners
    cv2.line(frame, (x1, y1), (x1 + length, y1), color, thickness + 1)
    cv2.line(frame, (x1, y1), (x1, y1 + length), color, thickness + 1)
    cv2.line(frame, (x2, y1), (x2 - length, y1), color, thickness + 1)
    cv2.line(frame, (x2, y1), (x2, y1 + length), color, thickness + 1)
    cv2.line(frame, (x1, y2), (x1 + length, y2), color, thickness + 1)
    cv2.line(frame, (x1, y2), (x1, y2 - length), color, thickness + 1)
    cv2.line(frame, (x2, y2), (x2 - length, y2), color, thickness + 1)
    cv2.line(frame, (x2, y2), (x2, y2 - length), color, thickness + 1)

    # Draw thin full box
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)
    return frame

def draw_hud_panel(frame, person_name, status, is_criminal, confidence, face_crop):
    fh, fw = frame.shape[:2]
    panel_w = 300
    panel_x = fw - panel_w - 20
    panel_y = 20
    panel_h = 450
    
    # Draw semi-transparent panel
    overlay = frame.copy()
    cv2.rectangle(overlay, (panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h), (10, 15, 10), -1)
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)
    
    # Draw border
    cv2.rectangle(frame, (panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h), (50, 150, 50), 1)
    
    # Header
    cv2.putText(frame, "AI FACIAL RECOGNITION", (panel_x + 15, panel_y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 255, 150), 1)
    
    # Face crop
    if face_crop is not None and face_crop.size > 0:
        crop_size = 180
        ch, cw = face_crop.shape[:2]
        scale = crop_size / min(ch, cw)
        resized_crop = cv2.resize(face_crop, (int(cw * scale), int(ch * scale)))
        rch, rcw = resized_crop.shape[:2]
        start_y = (rch - crop_size) // 2
        start_x = (rcw - crop_size) // 2
        final_crop = resized_crop[start_y:start_y+crop_size, start_x:start_x+crop_size]
        
        crop_x = panel_x + (panel_w - crop_size) // 2
        crop_y = panel_y + 60
        
        # Draw crop
        frame[crop_y:crop_y+crop_size, crop_x:crop_x+crop_size] = final_crop
        # Draw corners for crop
        draw_sci_fi_box(frame, crop_x - 5, crop_y - 5, crop_x + crop_size + 5, crop_y + crop_size + 5, (100, 200, 100), length=15)
    
    # Details
    text_y = panel_y + 280
    cv2.putText(frame, "NAME:", (panel_x + 20, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
    cv2.putText(frame, person_name, (panel_x + 20, text_y + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 255, 150), 2)
    
    cv2.putText(frame, "AGE:", (panel_x + 20, text_y + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
    import hashlib
    fake_age = 20 + (int(hashlib.md5(person_name.encode()).hexdigest(), 16) % 30)
    cv2.putText(frame, str(fake_age), (panel_x + 20, text_y + 85), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 255, 150), 1)
    
    cv2.putText(frame, "STATUS:", (panel_x + 20, text_y + 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
    color = (0, 0, 255) if is_criminal else (150, 255, 150)
    cv2.putText(frame, status, (panel_x + 20, text_y + 145), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    
    # Match confidence bar
    cv2.putText(frame, f"MATCH CONFIDENCE:    {confidence:.1f}%", (panel_x + 20, text_y + 190), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)
    
    bar_w = 260
    bar_h = 10
    bar_x = panel_x + 20
    bar_y = text_y + 200
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (50, 50, 50), 1)
    fill_w = int(bar_w * (confidence / 100.0))
    cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), (50, 200, 50), -1)

    return frame

def run_boot_sequence(frame_shape):
    """Simulates a mainframe boot sequence."""
    h, w = frame_shape[:2]
    messages = [
        "INITIATING SECURE UPLINK...",
        "CONNECTING TO POSTGRESQL DATABASE...",
        "LOADING FACE ENCODINGS FROM DB...",
        "INITIALIZING ENCRYPTION MODULE...",
        "STARTING AUDIT LOGGING...",
        "SYSTEM ONLINE. PHASE 1 SECURITY ENABLED."
    ]
    
    boot_frame = np.zeros((h, w, 3), dtype=np.uint8)
    for i, msg in enumerate(messages):
        boot_frame.fill(0)
        # Draw previous messages
        for j in range(i):
            cv2.putText(boot_frame, messages[j] + " [OK]", (50, 100 + j * 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50, 255, 50), 2)
        
        # Typewriter effect for current message
        current_text = ""
        for char in msg:
            current_text += char
            temp_frame = boot_frame.copy()
            cv2.putText(temp_frame, current_text, (50, 100 + i * 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 255, 150), 2)
            cv2.imshow("Human Analysis System", temp_frame)
            cv2.waitKey(15)
        
        # Blink cursor briefly
        for _ in range(3):
            temp_frame = boot_frame.copy()
            cv2.putText(temp_frame, current_text + " _", (50, 100 + i * 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 255, 150), 2)
            cv2.imshow("Human Analysis System", temp_frame)
            cv2.waitKey(150)
            
            temp_frame = boot_frame.copy()
            cv2.putText(temp_frame, current_text, (50, 100 + i * 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 255, 150), 2)
            cv2.imshow("Human Analysis System", temp_frame)
            cv2.waitKey(150)
            
    time.sleep(0.5)

def play_alarm():
    """Plays an alarm sound on MacOS."""
    def _play():
        os.system("afplay /System/Library/Sounds/Ping.aiff")
    threading.Thread(target=_play, daemon=True).start()

def draw_data_stream(frame, time_elapsed):
    """Draws a scrolling data stream on the left."""
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (180, h), (5, 10, 5), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
    
    cv2.putText(frame, "ENCRYPTED DATALINK", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 0), 1)
    cv2.line(frame, (10, 40), (170, 40), (0, 200, 0), 1)
    
    # Generate fake scrolling hex data
    num_lines = h // 20 - 3
    random.seed(int(time_elapsed * 10)) # change text every 100ms
    for i in range(num_lines):
        hex_str = "".join([random.choice("0123456789ABCDEF") for _ in range(16)])
        y = 60 + i * 20
        cv2.putText(frame, hex_str, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 150, 0), 1)
        
    return frame

def draw_crosshairs(frame):
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    color = (150, 255, 150)
    
    # Center dot
    cv2.circle(frame, (cx, cy), 2, color, -1)
    # Crosshair lines
    length = 20
    gap = 10
    cv2.line(frame, (cx, cy - gap), (cx, cy - gap - length), color, 1)
    cv2.line(frame, (cx, cy + gap), (cx, cy + gap + length), color, 1)
    cv2.line(frame, (cx - gap, cy), (cx - gap - length, cy), color, 1)
    cv2.line(frame, (cx + gap, cy), (cx + gap + length, cy), color, 1)
    
    # Corner brackets around center
    b_len = 15
    b_gap = 50
    # Top-Left
    cv2.line(frame, (cx - b_gap, cy - b_gap), (cx - b_gap + b_len, cy - b_gap), color, 1)
    cv2.line(frame, (cx - b_gap, cy - b_gap), (cx - b_gap, cy - b_gap + b_len), color, 1)
    # Top-Right
    cv2.line(frame, (cx + b_gap, cy - b_gap), (cx + b_gap - b_len, cy - b_gap), color, 1)
    cv2.line(frame, (cx + b_gap, cy - b_gap), (cx + b_gap, cy - b_gap + b_len), color, 1)
    # Bottom-Left
    cv2.line(frame, (cx - b_gap, cy + b_gap), (cx - b_gap + b_len, cy + b_gap), color, 1)
    cv2.line(frame, (cx - b_gap, cy + b_gap), (cx - b_gap, cy + b_gap - b_len), color, 1)
    # Bottom-Right
    cv2.line(frame, (cx + b_gap, cy + b_gap), (cx + b_gap - b_len, cy + b_gap), color, 1)
    cv2.line(frame, (cx + b_gap, cy + b_gap), (cx + b_gap, cy + b_gap - b_len), color, 1)

    return frame

def draw_rec_indicator(frame, time_elapsed):
    if int(time_elapsed * 2) % 2 == 0:
        cv2.circle(frame, (40, 40), 6, (0, 0, 255), -1)
    cv2.putText(frame, "SECURE FEED / REC", (55, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    return frame

def draw_threat_level(frame, score):
    """Draws a global threat level bar at the top."""
    h, w = frame.shape[:2]
    bar_h = 25
    cv2.rectangle(frame, (0, 0), (w, bar_h), (10, 10, 10), -1)
    
    if score >= 75:
        level = "CRITICAL"
        color = (0, 0, 255)
    elif score >= 40:
        level = "ELEVATED"
        color = (0, 165, 255)
    else:
        level = "LOW"
        color = (50, 200, 50)
        
    text = f"GLOBAL THREAT LEVEL: {level} | PHASE 1 SECURITY ACTIVE"
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.putText(frame, text, (w // 2 - tw // 2, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    
    # Progress bar underneath
    cv2.rectangle(frame, (0, bar_h), (w, bar_h + 3), (30, 30, 30), -1)
    fill_w = int(w * (score / 100.0))
    cv2.rectangle(frame, (0, bar_h), (fill_w, bar_h + 3), color, -1)
    return frame

def draw_radar(frame, tracks, frame_w, frame_h, time_elapsed, criminal_ids):
    """Draws a tactical mini-radar in the bottom right corner."""
    radar_r = 70
    radar_cx = frame_w - radar_r - 20
    radar_cy = frame_h - radar_r - 20
    
    # Draw radar background
    overlay = frame.copy()
    cv2.circle(overlay, (radar_cx, radar_cy), radar_r, (10, 20, 10), -1)
    cv2.addWeighted(overlay, 0.8, frame, 0.2, 0, frame)
    
    # Draw radar rings and cross
    cv2.circle(frame, (radar_cx, radar_cy), radar_r, (0, 150, 0), 1)
    cv2.circle(frame, (radar_cx, radar_cy), radar_r // 2, (0, 150, 0), 1)
    cv2.line(frame, (radar_cx - radar_r, radar_cy), (radar_cx + radar_r, radar_cy), (0, 100, 0), 1)
    cv2.line(frame, (radar_cx, radar_cy - radar_r), (radar_cx, radar_cy + radar_r), (0, 100, 0), 1)
    
    # Draw sweeping line
    import math
    angle = (time_elapsed * 2) % (2 * math.pi)
    end_x = int(radar_cx + radar_r * math.cos(angle))
    end_y = int(radar_cy + radar_r * math.sin(angle))
    cv2.line(frame, (radar_cx, radar_cy), (end_x, end_y), (0, 255, 0), 2)
    
    # Draw dots for tracks
    for track in tracks:
        if not track.is_confirmed():
            continue
        # Map frame pos to radar pos
        x1, y1, x2, y2 = map(int, track.to_ltrb())
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        
        # Relative to center
        rel_x = (cx - frame_w / 2) / (frame_w / 2)
        rel_y = (cy - frame_h / 2) / (frame_h / 2)
        
        dot_x = int(radar_cx + rel_x * radar_r)
        dot_y = int(radar_cy + rel_y * radar_r)
        
        # Keep inside circle
        dist = math.hypot(dot_x - radar_cx, dot_y - radar_cy)
        if dist > radar_r - 3:
            continue
            
        color = (0, 0, 255) if track.track_id in criminal_ids else (50, 255, 50)
        # Flash red dots
        if track.track_id in criminal_ids and int(time_elapsed * 5) % 2 == 0:
            color = (255, 255, 255)
            
        cv2.circle(frame, (dot_x, dot_y), 3, color, -1)
        
    return frame

def draw_flash_effect(frame, flash_time, current_time):
    """Simulates a bright white flash fading out over 0.5 seconds."""
    if flash_time > 0:
        elapsed = current_time - flash_time
        if elapsed < 0.5:
            alpha = max(0, 1.0 - (elapsed / 0.5))
            overlay = np.full_like(frame, 255)
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    return frame

def main():
    parser = argparse.ArgumentParser(description="Advanced National Security System")
    parser.add_argument("--camera", type=str, default="", help="RTSP URL or camera index (overrides config camera_index).")
    parser.add_argument("--video", type=str, default="", help="Path to video file fallback if camera fails.")
    args = parser.parse_args()
    base_dir = os.path.dirname(os.path.abspath(__file__))

    config_path = os.path.join(base_dir, "config", "config.yaml")
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    camera_index      = cfg.get("camera_index", 0)
    conf_threshold    = cfg.get("confidence_threshold", 0.5)
    weapon_conf       = cfg.get("weapon_conf_threshold", 0.4)
    face_tolerance    = cfg.get("face_tolerance", 0.45)
    camera_location   = cfg.get("camera_location", "Camera_1")
    criminal_names    = set(cfg.get("criminal_names", []))
    simple_hud        = cfg.get("performance", {}).get("simple_hud", True)

    model_dir         = os.path.join(base_dir, cfg.get("model_dir", "models"))
    human_model_path  = os.path.join(model_dir, cfg.get("human_model", "yolov8x.pt"))
    weapon_model_path = os.path.join(model_dir, cfg.get("weapon_model", "weapon_yolo.pt"))

    # Create evidence directories (still used for file storage with DB metadata)
    evidence_dir = os.path.join(base_dir, "evidence")
    for d in ["criminals", "weapons", "suspicious"]:
        os.makedirs(os.path.join(evidence_dir, d), exist_ok=True)

    logger.info(f"Human model  : {human_model_path}")
    logger.info(f"Weapon model : {weapon_model_path}")
    logger.info(f"Criminal list: {criminal_names}")

    if args.camera:
        camera_source = args.camera
        logger.info(f"Using camera from --camera arg: {camera_source}")
    elif args.video:
        camera_source = args.video
        logger.info(f"Using video file: {camera_source}")
    else:
        camera_source = camera_index
        logger.info(f"Using camera index: {camera_source}")

    cap = cv2.VideoCapture(camera_source)

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video source: {camera_source}")
        
    ret, initial_frame = cap.read()
    if ret:
        run_boot_sequence(initial_frame.shape)

    detector = HumanDetector(human_model_path, conf_threshold)

    weapon_detector = None
    weapon_enabled  = False
    if os.path.exists(weapon_model_path):
        try:
            weapon_detector = WeaponDetector(weapon_model_path, weapon_conf)
            weapon_enabled  = True
            logger.info("Weapon detector: ENABLED")
        except Exception as e:
            logger.warning(f"Weapon detector DISABLED: {e}")
    else:
        logger.warning(f"Weapon model not found → weapon detection OFF")

    tracker         = HumanTracker()
    face_analyzer   = FaceAnalyzer()
    pose_analyzer   = PoseAnalyzer()
    face_recognizer = FaceRecognizerDB(tolerance=face_tolerance)

    # Phase 3: ANPR and Vehicle Detection
    anpr = LicensePlateRecognizer(languages=['en'], gpu=False)
    plate_db = LicensePlateDatabase()
    vehicle_detector = None
    vehicle_model_path = os.path.join(model_dir, "yolov8l.pt")
    if os.path.exists(vehicle_model_path):
        try:
            vehicle_detector = VehicleDetector(vehicle_model_path, conf_threshold)
            logger.info("Vehicle detector: ENABLED")
        except Exception as e:
            logger.warning(f"Vehicle detector DISABLED: {e}")
    vehicle_tracker = VehicleTracker()
    alert_orchestrator = AlertOrchestrator()

    # Per-track state
    id_name_map        = {}   # track_id → name
    id_frame_count     = defaultdict(int)   # track_id → frames seen
    track_history      = defaultdict(list)  # track_id → [(t, cx, cy)]
    last_saved         = {}   # track_id → last save timestamp

    # Phase 4: Performance optimizations
    frame_skipper = FrameSkipper(target_fps=30)
    resource_monitor = ResourceMonitor()
    perf_enabled = os.getenv('PERF_MONITOR', 'false').lower() == 'true'

    # ── Cross-camera tracking ──
    cross_camera_enabled = cfg.get("cross_camera", {}).get("enabled", True)
    cross_camera_tracker = CrossCameraTracker(
        similarity_threshold=cfg.get("cross_camera", {}).get("similarity_threshold", 0.6)
    ) if cross_camera_enabled else None

    # ── Anomaly detection ──
    analytics_enabled = cfg.get("analytics", {}).get("enabled", True)
    anomaly_detector = AnomalyDetector() if analytics_enabled else None
    heatmap_gen = HeatmapGenerator(
        frame_width=640, frame_height=480,
        grid_size=cfg.get("analytics", {}).get("heatmap_grid_size", 50)
    ) if analytics_enabled else None
    dwell_analyzer = DwellTimeAnalyzer() if analytics_enabled else None

    # ── Multi-camera stream manager ──
    cameras_cfg = cfg.get("cameras", [])
    stream_mgr = StreamManager()
    for cam_cfg in cameras_cfg:
        feed = CameraFeed(
            camera_id=cam_cfg.get("id", ""),
            name=cam_cfg.get("name", ""),
            uri=cam_cfg.get("uri", 0),
            location=cam_cfg.get("location", ""),
            lat=cam_cfg.get("lat", 0.0),
            lng=cam_cfg.get("lng", 0.0),
        )
        stream_mgr.add_camera(feed)
    if stream_mgr.feeds:
        stream_mgr.start_all()

    logger.info("System Started — press Q to quit. Press T for Thermal Mode.")
    frame_count = 0
    start_time  = time.time()
    last_alarm_time = 0
    thermal_mode = False
    last_flash_time = 0

    # Analytics accumulators
    analytics_start = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            logger.error("Failed to read frame")
            break

        # Performance: Skip frames if needed
        if not frame_skipper.should_process():
            continue

        if thermal_mode:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)

        frame_count += 1
        now = time.time()

        detections = detector.detect(frame)
        tracks     = tracker.track(detections, frame)
        
        elapsed = now - start_time
        
        # Advanced HUD Background Elements
        if not simple_hud:
            frame = draw_data_stream(frame, elapsed)
            frame = draw_crosshairs(frame)
            frame = draw_rec_indicator(frame, elapsed)

        # Weapon detection
        weapons        = []
        weapon_present = False
        if weapon_enabled and weapon_detector is not None:
            try:
                weapons        = weapon_detector.detect(frame)
                weapon_present = len(weapons) > 0
            except Exception as e:
                logger.warning(f"Weapon detection error: {e}")

        for w in weapons:
            wx1, wy1, wx2, wy2 = w["bbox"]
            frame = draw_box(
                frame, wx1, wy1, wx2, wy2,
                f"WEAPON {w['score']:.0%}", (0, 0, 255)
            )

        # Phase 3: Vehicle detection and ANPR
        vehicles = []
        if vehicle_detector is not None:
            try:
                vehicles = vehicle_detector.detect(frame)
            except Exception as e:
                logger.warning(f"Vehicle detection error: {e}")

        for v in vehicles:
            vx1, vy1, vx2, vy2 = v['bbox']
            cv2.rectangle(frame, (vx1, vy1), (vx2, vy2), (255, 165, 0), 2)
            label = f"{v['class_name'].upper()} {v['score']:.0%}"
            cv2.putText(frame, label, (vx1, vy1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 165, 0), 2)

            # Run ANPR on vehicle ROI (throttled: every 30 frames)
            if frame_count % 30 == 0:
                vehicle_roi = frame[vy1:vy2, vx1:vx2]
                if vehicle_roi.size > 0:
                    plates = anpr.detect_plates(vehicle_roi)
                    for plate in plates:
                        px1, py1, px2, py2 = plate['bbox'][0:4]
                        px1 += vx1; py1 += vy1; px2 += vx1; py2 += vy1
                        cv2.rectangle(frame, (px1, py1), (px2, py2), (0, 255, 255), 2)
                        cv2.putText(frame, plate['plate_number'], (px1, py1 - 5),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

                        # Check if watchlisted
                        if plate_db.is_watchlisted(plate['plate_number']):
                            cv2.putText(frame, "WATCHLISTED", (px1, py2 + 20),
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                            logger.warning(f"WATCHLISTED PLATE: {plate['plate_number']}")

                            # Send alert
                            try:
                                alert_orchestrator.send_suspicious_vehicle_alert(
                                    plate['plate_number'],
                                    v['class_name'],
                                    camera_location,
                                    "Watchlisted plate detected"
                                )
                            except Exception as e:
                                logger.warning(f"Alert failed: {e}")

        # Count active criminals this frame for HUD
        active_criminals = []
        criminal_ids = set()

        for track in tracks:
            if not track.is_confirmed():
                continue

            track_id = track.track_id
            x1, y1, x2, y2 = map(int, track.to_ltrb())

            fh, fw = frame.shape[:2]
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(fw, x2)
            y2 = min(fh, y2)

            roi = frame[y1:y2, x1:x2]
            if roi.size == 0:
                continue

            # Track center history
            track_history[track_id].append((now, (x1 + x2) / 2, (y1 + y2) / 2))
            track_history[track_id] = [
                p for p in track_history[track_id] if now - p[0] <= 30
            ]

            # Analytics: heatmap + dwell time
            if heatmap_gen is not None:
                heatmap_gen.add_detection((x1 + x2) // 2, (y1 + y2) // 2, datetime.utcnow())
            if dwell_analyzer is not None:
                dwell_analyzer.update_track(track_id, datetime.utcnow(), ((x1 + x2) // 2, (y1 + y2) // 2))

            # Face recognition:
            should_recognize = (
                track_id not in id_name_map
                or id_frame_count[track_id] % RERECOGNIZE_EVERY == 0
            )

            if should_recognize:
                try:
                    name = face_recognizer.recognize_person(roi)
                except Exception as e:
                    logger.warning(f"Face recog failed ID {track_id}: {e}")
                    name = None

                if name:
                    id_name_map[track_id] = name
                    if name in criminal_names:
                        logger.info(f"CRIMINAL DETECTED: {name} | ID:{track_id}")

                    # Cross-camera tracking
                    if cross_camera_tracker is not None:
                        try:
                            cross_camera_tracker.identify_person(
                                camera_id=camera_location,
                                face_roi=roi,
                                body_roi=roi,
                                timestamp=datetime.utcnow(),
                            )
                        except Exception as e:
                            logger.warning(f"Cross-camera tracking error: {e}")
                elif track_id not in id_name_map:
                    # First time and no match → Unknown
                    id_name_map[track_id] = "Unknown"

            name = id_name_map.get(track_id, "Unknown")

            # Pose & behavior
            try:
                pose_landmarks = pose_analyzer.analyze(roi)
            except Exception:
                pose_landmarks = None

            is_suspicious, reasons = is_suspicious_behavior(
                track_history[track_id], pose_landmarks
            )

            is_criminal = name in criminal_names
            alert       = is_criminal or weapon_present or is_suspicious

            if is_criminal:
                active_criminals.append(name)
                criminal_ids.add(track_id)

            # Color and label
            if is_criminal:
                color      = (0, 0, 255)       # red
                status     = "CRIMINAL"
                # Play alarm every 5 seconds if still detected
                if now - last_alarm_time > 5.0:
                    play_alarm()
                    last_alarm_time = now
                    # Phase 3: Send alert to law enforcement
                    try:
                        alert_orchestrator.send_criminal_alert(
                            criminal_name=name,
                            camera_location=camera_location,
                            track_id=track_id
                        )
                    except Exception as e:
                        logger.warning(f"Alert failed: {e}")
            elif weapon_present:
                color      = (0, 0, 255)       # red
                status     = "Armed"
                # Phase 3: Send weapon alert
                if now - last_alarm_time > 5.0:
                    try:
                        alert_orchestrator.send_weapon_alert(
                            camera_location=camera_location,
                            track_id=track_id
                        )
                    except Exception as e:
                        logger.warning(f"Weapon alert failed: {e}")
            elif is_suspicious:
                color      = (0, 165, 255)     # orange
                status     = "Suspicious"
            else:
                color      = (50, 200, 50)     # green
                status     = "Clear"

            # Draw sci-fi box
            frame = draw_sci_fi_box(frame, x1, y1, x2, y2, color, thickness=1)
            
            # Label background and text
            label = "PERSON OF INTEREST" if is_criminal else f"ID: {track_id}"
            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (x1, y1 - 25), (x1 + lw + 10, y1), color, -1)
            cv2.putText(frame, label, (x1 + 5, y1 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

            # Draw HUD if it's a person of interest or criminal
            if is_criminal or is_suspicious:
                import random
                conf = 98.7 if is_criminal else 75.0 + random.random() * 20.0
                frame = draw_hud_panel(frame, name, status, is_criminal, conf, roi)
                try:
                    face_result = face_analyzer.analyze(roi)
                    if face_result and face_result.multi_face_landmarks:
                        face_analyzer.draw_mesh(roi, face_result.multi_face_landmarks[0])
                except Exception:
                    pass

            # Anomaly detection
            if anomaly_detector is not None and alert:
                try:
                    anomaly_detector.record_detection(
                        camera_id=camera_location,
                        detection_type=category if alert else "normal",
                        confidence=0.5,
                        location=((x1 + x2) // 2, (y1 + y2) // 2),
                        timestamp=datetime.utcnow(),
                    )
                except Exception as e:
                    logger.warning(f"Anomaly detection error: {e}")

            # Save evidence (throttled: once per 10s per ID)
            if alert and (now - last_saved.get(track_id, 0) >= 10):
                try:
                    evidence_thread = threading.Thread(
                        target=save_evidence_db,
                        args=(
                            camera_location, track_id, name,
                            is_criminal, weapon_present, is_suspicious,
                            reasons, frame.copy(), roi.copy()
                        ),
                        daemon=True
                    )
                    evidence_thread.start()
                    last_saved[track_id] = now
                    last_flash_time = now
                except Exception as e:
                    logger.warning(f"Failed to save evidence: {e}")

                
        # Draw Ultimate Tactical HUD elements
        score = min(100, len(tracks)*5 + weapon_present*40 + len(active_criminals)*50)
        frame = draw_threat_level(frame, score)
        if not simple_hud:
            frame = draw_radar(frame, tracks, frame.shape[1], frame.shape[0], elapsed, criminal_ids)
            frame = draw_flash_effect(frame, last_flash_time, now)

        # Basic HUD overlay
        elapsed = now - start_time
        fps = frame_count / elapsed if elapsed > 0 else 0

        hud_h = 30 + 20 * max(1, len(active_criminals) + 3)
        if perf_enabled:
            hud_h += 20  # Extra space for perf stats
        cv2.rectangle(frame, (0, 0), (350, hud_h), (0, 0, 0), -1)

        cv2.putText(
            frame, f"FPS: {fps:.1f}  |  People: {len(tracks)}",
            (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2,
        )
        cv2.putText(
            frame, f"Weapon: {'ON' if weapon_enabled else 'OFF'}  "
                   f"Weapon detected: {'YES' if weapon_present else 'NO'}",
            (10, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
            (0, 0, 255) if weapon_present else (0, 255, 0), 1,
        )
        cv2.putText(
            frame, f"Criminals in frame: {len(active_criminals)}",
            (10, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
            (0, 0, 255) if active_criminals else (200, 200, 200), 1,
        )

        # Performance monitoring
        if perf_enabled:
            perf_stats = resource_monitor.get_stats()
            if 'error' not in perf_stats:
                cv2.putText(
                    frame, f"CPU: {perf_stats['cpu_percent']:.1f}%  "
                           f"MEM: {perf_stats['memory_mb']:.0f}MB",
                    (10, 84), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (200, 200, 200), 1,
                )
            skip_stats = frame_skipper.get_stats()
            cv2.putText(
                frame, f"Skip: {skip_stats['skip_rate']}",
                (10, 104), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                (200, 200, 200), 1,
            )

        # List each criminal name on HUD
        for i, cname in enumerate(active_criminals):
            cv2.putText(
                frame, f"  >> {cname}",
                (10, 84 + i * 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1,
            )

        cv2.putText(
            frame, f"Cam: {camera_location}",
            (10, hud_h - 6), cv2.FONT_HERSHEY_SIMPLEX,
            0.4, (150, 150, 150), 1,
        )

        cv2.imshow("Human Analysis System - Phase 3 (ANPR+Vehicle)", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("t"):
            thermal_mode = not thermal_mode

    cap.release()
    cv2.destroyAllWindows()
    logger.info("System Stopped")


if __name__ == "__main__":
    main()
