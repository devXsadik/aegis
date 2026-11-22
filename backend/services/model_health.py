"""Which detector models exist on disk. 'missing' = that feature is OFF; 'disabled' = turned off in config."""

import logging
import os

from utils.config.model_config import vehicle_mode

logger = logging.getLogger("HumanAnalysis")

KEYS = ("human_detector", "weapon_detector", "vehicle_detector", "pose_analyzer", "fire_detector")
LABELS = {
    "human_detector": "Person detection",
    "weapon_detector": "Weapon detection",
    "vehicle_detector": "Vehicle detection",
    "pose_analyzer": "Pose / fall checks",
    "fire_detector": "Fire & smoke detection",
}


def _switched_off(key: str, cfg: dict) -> bool:
    if key == "vehicle_detector":
        return vehicle_mode(cfg) == "off"
    if key == "pose_analyzer":
        return not (cfg.get("pose") or {}).get("enabled", True)
    return False


def model_status() -> dict:
    from paths import ROOT
    from utils.config import load_yaml
    from utils.config.model_config import load_model_registry

    out = {}
    try:
        cfg = load_yaml(str(ROOT / "config" / "config.yaml")) or {}
        registry = load_model_registry(str(ROOT))
        for key in KEYS:
            entry = registry.get(key, {})
            if key == "vehicle_detector" and vehicle_mode(cfg) == "fast":
                entry = registry.get("human_detector", {})   # fast mode rides on the person model
            rel = entry.get("path")
            if not rel:
                continue
            path = os.path.join(str(ROOT), cfg.get("model_dir", "models"), os.path.basename(rel))
            if _switched_off(key, cfg):
                out[key] = "disabled"       # off on purpose in config.yaml, not broken
            elif os.path.exists(path):
                out[key] = "ok"
            else:
                out[key] = "not_installed" if entry.get("optional") else "missing"
    except Exception as e:
        logger.warning(f"Model status check failed: {e}")
    return out
