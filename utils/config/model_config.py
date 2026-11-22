"""Load model paths and settings from config/models.yaml."""

import os
from utils.config.config_loader import load_yaml


def load_model_registry(base_dir: str) -> dict:
    path = os.path.join(base_dir, "config", "models.yaml")
    if not os.path.exists(path):
        return {}
    return load_yaml(path).get("models", {})


def model_path(base_dir: str, model_dir: str, key: str, fallback: str) -> str:
    registry = load_model_registry(base_dir)
    entry = registry.get(key, {})
    rel = entry.get("path", fallback)
    if os.path.isabs(rel):
        return rel
    return os.path.join(model_dir, os.path.basename(rel))


def model_setting(base_dir: str, key: str, setting: str, default=None):
    registry = load_model_registry(base_dir)
    return registry.get(key, {}).get(setting, default)



def vehicle_mode(cfg: dict) -> str:
    """`vehicle_detection` in config.yaml → "off" | "fast" | "accurate".

    fast: the person model reports vehicles in the same pass (next to no extra cost).
    accurate: a separate YOLOv8l (about twice the person model's time per frame).
    Booleans are the old setting: true meant the YOLOv8l model.
    """
    raw = cfg.get("vehicle_detection", "fast")
    if raw is True:
        return "accurate"
    if raw is False or raw is None:
        return "off"
    mode = str(raw).strip().lower()
    return mode if mode in {"off", "fast", "accurate"} else "fast"
