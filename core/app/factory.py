"""Pipeline factory — builds SurveillancePipeline from config."""

import os
import threading

from core import (
    HumanDetector, WeaponDetector, HumanTracker, PoseAnalyzer,
    FaceRecognizerDB, VehicleDetector, VehicleTracker,
    LicensePlateRecognizer, LicensePlateDatabase, AnomalyDetector,
)
from core.pipeline import SurveillancePipeline
from core.pipeline.stages import (
    DetectionStage, TrackingStage, RecognitionStage,
    BehaviorStage, AnalyticsStage, OutputStage,
)
from utils.system import logger
from utils.config import model_path, model_setting


def play_alarm():
    """Plays an alarm sound on MacOS."""
    def _play():
        os.system("afplay /System/Library/Sounds/Ping.aiff")
    threading.Thread(target=_play, daemon=True).start()


def build_pipeline(cfg, base_dir, camera_location=None):
    """Build the surveillance pipeline from config + models.yaml."""
    model_dir = os.path.join(base_dir, cfg.get("model_dir", "models"))
    conf_threshold = cfg.get("confidence_threshold", 0.5)
    weapon_conf = cfg.get("weapon_conf_threshold", 0.4)
    face_tolerance = cfg.get(
        "face_tolerance",
        model_setting(base_dir, "face_recognizer", "tolerance", 0.45),
    )
    loc = camera_location or cfg.get("camera_location", "Camera_1")
    criminal_names = set(cfg.get("criminal_names", []))

    try:
        from backend.db.database import SessionLocal
        from backend.models.known_person import KnownPerson
        db = SessionLocal()
        criminals = db.query(KnownPerson).filter(KnownPerson.category == "criminal").all()
        for c in criminals:
            criminal_names.add(c.person_id)
        db.close()
    except Exception as e:
        logger.warning(f"Failed to fetch criminal names from DB: {e}")

    human_model_path = model_path(
        base_dir, model_dir, "human_detector",
        cfg.get("human_model", "yolov8s.pt"),
    )
    weapon_model_path = model_path(
        base_dir, model_dir, "weapon_detector",
        cfg.get("weapon_model", "weapon_yolo.pt"),
    )
    vehicle_model_path = model_path(
        base_dir, model_dir, "vehicle_detector", "yolov8l.pt",
    )

    # if not os.path.exists(human_model_path):
    #     raise FileNotFoundError(f"Human model not found: {human_model_path}")

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
    anpr_cfg = cfg.get("anpr", {})
    anpr = LicensePlateRecognizer(
        languages=anpr_cfg.get(
            "languages",
            model_setting(base_dir, "anpr_ocr", "languages", ["en"]),
        ),
        gpu=anpr_cfg.get("gpu", model_setting(base_dir, "anpr_ocr", "gpu", False)),
    )
    plate_db = LicensePlateDatabase()

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
        camera_location=loc,
        evidence_throttle_seconds=cfg.get("evidence_throttle_seconds", 10.0),
        alarm_interval_seconds=cfg.get("alarm_interval_seconds", 5.0),
        alarm_callback=play_alarm,
    ))

    return pipeline, criminal_names, loc
