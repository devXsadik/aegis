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
from core.analysis.behavior import configure_behavior
from utils.config import model_path, model_setting


def play_alarm():
    """Plays an alarm sound on MacOS."""
    def _play():
        os.system("afplay /System/Library/Sounds/Ping.aiff")
    threading.Thread(target=_play, daemon=True).start()


# One instance of each heavy model is shared by every camera (detectors lock internally).
_SHARED: dict = {}
_SHARED_LOCK = threading.Lock()


def _shared(key, factory):
    with _SHARED_LOCK:
        if key not in _SHARED:
            _SHARED[key] = factory()
        return _SHARED[key]


def build_pipeline(cfg, base_dir, camera_location=None, zones=None, lines=None):
    """Build the surveillance pipeline from config + models.yaml.

    This is the composition root: the only place `core` is wired to backend storage.
    """
    from backend.services import watchlist_store
    from core.detectors.device import resolve_device
    device = resolve_device(cfg.get("device", "auto"))
    model_dir = os.path.join(base_dir, cfg.get("model_dir", "models"))
    conf_threshold = cfg.get("confidence_threshold", 0.5)
    weapon_conf = cfg.get("weapon_conf_threshold", 0.4)
    face_tolerance = cfg.get(
        "face_tolerance",
        model_setting(base_dir, "face_recognizer", "tolerance", 0.45),
    )
    loc = camera_location or cfg.get("camera_location", "Camera_1")
    configure_behavior(cfg.get("behavior"))
    criminal_names = set(cfg.get("criminal_names", []))

    try:
        criminal_names |= watchlist_store.load_criminal_ids()
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

    human_detector = _shared(
        ("human", human_model_path),
        lambda: HumanDetector(human_model_path, conf_threshold, device),
    )
    logger.info(f"Inference device: {device}")

    weapon_detector = None
    if os.path.exists(weapon_model_path):
        try:
            weapon_detector = _shared(
                ("weapon", weapon_model_path),
                lambda: WeaponDetector(weapon_model_path, weapon_conf, device),
            )
            logger.info("Weapon detector: ENABLED")
        except Exception as e:
            logger.warning(f"Weapon detector DISABLED: {e}")
    else:
        logger.warning(f"Weapon detector DISABLED: model not found at {weapon_model_path}")

    vehicle_detector = None
    if os.path.exists(vehicle_model_path):
        try:
            vehicle_detector = _shared(
                ("vehicle", vehicle_model_path),
                lambda: VehicleDetector(vehicle_model_path, conf_threshold, device),
            )
            logger.info("Vehicle detector: ENABLED")
        except Exception as e:
            logger.warning(f"Vehicle detector DISABLED: {e}")
    else:
        logger.warning(f"Vehicle detector DISABLED: model not found at {vehicle_model_path}")

    human_tracker = HumanTracker()
    vehicle_tracker = VehicleTracker()
    face_recognizer = _shared(
        ("face", face_tolerance),
        lambda: FaceRecognizerDB(tolerance=face_tolerance,
                                 loader=watchlist_store.load_face_encodings),
    )
    pose_analyzer = PoseAnalyzer()
    anomaly_cfg = cfg.get("anomaly", {})
    anomaly_detector = AnomalyDetector(
        crowd_threshold=anomaly_cfg.get("crowd_threshold", 5),
        dwell_seconds=anomaly_cfg.get("dwell_seconds", 300),
        zones=zones if zones is not None else cfg.get("zones"),
        lines=lines if lines is not None else cfg.get("lines"),
    )
    # ANPR is opt-in: EasyOCR over whole vehicle crops is slow and noisy without a
    # dedicated plate detector. Enable with anpr.enabled: true in config.yaml.
    anpr_cfg = cfg.get("anpr", {})
    anpr = None
    plate_db = None
    if anpr_cfg.get("enabled", False):
        anpr = _shared(
            ("anpr", tuple(anpr_cfg.get("languages", ["en"]))),
            lambda: LicensePlateRecognizer(
                languages=anpr_cfg.get(
                    "languages",
                    model_setting(base_dir, "anpr_ocr", "languages", ["en"]),
                ),
                gpu=anpr_cfg.get("gpu", model_setting(base_dir, "anpr_ocr", "gpu", False)),
            ),
        )
        plate_db = LicensePlateDatabase(loader=watchlist_store.load_watchlisted_plates)
    else:
        logger.warning("ANPR disabled (anpr.enabled: false)")

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
