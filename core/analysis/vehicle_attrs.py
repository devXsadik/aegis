"""Vehicle attributes from a crop: colour, type, make/model and a re-identification vector.

Trained models are used when present (exported by training/, promoted in the model registry):
    models/vehicle_attr.onnx  + models/vehicle_attr.labels.json   multi-head: color, type, model
    models/vehicle_reid.onnx                                      appearance embedding
Without them the baselines below run: an HSV colour vote on the car body, type from the
detector class, and a colour/texture histogram as a weak re-ID vector. Baselines are honest
about it (`model` names them) and give lower confidences, so matching weighs them accordingly.

Night / IR: `is_night` flags grey or very dark frames; colour from those is marked unreliable."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Dict, Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - cv2 is a hard dependency of the pipeline
    cv2 = None

MODELS = os.getenv("AEGIS_MODELS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "models"))
COCO_TO_TYPE = {"car": "car", "bus": "bus", "truck": "truck", "motorcycle": "motorcycle", "motorbike": "motorcycle",
                "bicycle": "other"}


def is_night(img: np.ndarray) -> bool:
    """Grey (IR) or dark frame → colour unreliable."""
    if img is None or img.size == 0:
        return False
    if img.ndim == 2 or img.shape[2] == 1:
        return True
    b, g, r = (img[..., i].astype(np.int16) for i in range(3))
    if np.mean(np.abs(b - g)) < 4 and np.mean(np.abs(g - r)) < 4:     # IR: channels equal
        return True
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return float(np.mean(hsv[..., 2])) < 45


def _body(crop: np.ndarray) -> np.ndarray:
    """Middle band of the vehicle: below the windows, above road and shadow."""
    h, w = crop.shape[:2]
    return crop[int(h * 0.45):int(h * 0.85), int(w * 0.15):int(w * 0.85)]


def _label(h: int, s: int, v: int) -> str:
    if v < 55:
        return "black"
    if s < 40:
        if v > 185:
            return "white"
        if v > 125:
            return "silver"
        return "grey"
    if h < 8 or h >= 170:
        return "maroon" if v < 115 else "red"
    if h < 20:
        return "brown" if v < 125 else "orange"
    if h < 34:
        return "yellow"
    if h < 85:
        return "green"
    if h < 130:
        return "blue"
    return "other"


def dominant_color(crop: np.ndarray) -> Tuple[Optional[str], float]:
    """(colour, share of body pixels that voted for it) from the HSV vote; None for an empty crop."""
    if crop is None or crop.size == 0 or crop.ndim != 3:
        return None, 0.0
    body = _body(crop)
    if body.size == 0:
        return None, 0.0
    small = cv2.resize(body, (48, 24), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    votes: Dict[str, int] = {}
    for h, s, v in hsv:
        lab = _label(int(h), int(s), int(v))
        votes[lab] = votes.get(lab, 0) + 1
    best = max(votes, key=votes.get)
    return best, votes[best] / len(hsv)


def type_from_detector(class_name: Optional[str], det_conf: Optional[float] = None) -> Tuple[Optional[str], float]:
    """COCO class → our type list; BD-specific types (CNG, leguna, easy-bike) need the trained model."""
    if not class_name:
        return None, 0.0
    t = COCO_TO_TYPE.get(class_name.lower())
    return (t, float(det_conf or 0.6) * 0.8) if t else ("other", 0.3)


@lru_cache(maxsize=4)
def _net(name: str):
    path = os.path.join(MODELS, name)
    if cv2 is None or not os.path.exists(path):
        return None
    try:
        return cv2.dnn.readNetFromONNX(path)
    except Exception:
        return None


@lru_cache(maxsize=1)
def _attr_labels() -> Optional[dict]:
    path = os.path.join(MODELS, "vehicle_attr.labels.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _blob(crop: np.ndarray, size: int, mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)) -> np.ndarray:
    rgb = cv2.cvtColor(cv2.resize(crop, (size, size)), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - np.array(mean, np.float32)) / np.array(std, np.float32)
    return rgb.transpose(2, 0, 1)[None]


def _softmax(x):
    e = np.exp(x - np.max(x))
    return e / e.sum()


def classify(crop: np.ndarray, detector_class: Optional[str] = None, det_conf: Optional[float] = None) -> dict:
    """{'vehicle_type', 'color', 'make_model', 'confidences', 'is_night', 'model'}."""
    night = is_night(crop)
    net, labels = _net("vehicle_attr.onnx"), _attr_labels()
    if net is not None and labels:
        net.setInput(_blob(crop, int(labels.get("input_size", 224))))
        heads = labels["heads"]                                     # [{"name": "color", "classes": [...]}, ...]
        outs = net.forward([h["output"] for h in heads])
        out = {"confidences": {}, "is_night": night, "model": labels.get("version", "vehicle_attr")}
        for head, logits in zip(heads, outs):
            p = _softmax(np.asarray(logits).ravel())
            k = int(np.argmax(p))
            key = {"color": "color", "type": "vehicle_type", "model": "make_model"}[head["name"]]
            out[key] = head["classes"][k]
            out["confidences"][head["name"]] = float(p[k]) * (0.5 if night and head["name"] == "color" else 1.0)
        return out
    color, share = dominant_color(crop)
    vtype, tconf = type_from_detector(detector_class, det_conf)
    return {"vehicle_type": vtype, "color": color, "make_model": None, "is_night": night, "model": "baseline-v1",
            "confidences": {"type": tconf, "color": round(min(0.85, share) * (0.4 if night else 1.0), 3)}}


def reid_embedding(crop: np.ndarray) -> Tuple[Optional[np.ndarray], str]:
    """L2-normalised appearance vector and the name of what made it."""
    if crop is None or crop.size == 0:
        return None, "none"
    net = _net("vehicle_reid.onnx")
    if net is not None:
        net.setInput(_blob(crop, 256))
        v = np.asarray(net.forward()).ravel().astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-9), "vehicle_reid"
    small = cv2.resize(crop, (64, 64), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256]).ravel()
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx, gy = cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    mag, ang = cv2.cartToPolar(gx, gy)
    grad = np.histogram(ang, bins=32, range=(0, 2 * np.pi), weights=mag)[0]
    v = np.concatenate([hist / (hist.sum() + 1e-9), grad / (grad.sum() + 1e-9)]).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9), "hist-v1"


def cosine(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> Optional[float]:
    if a is None or b is None or a.shape != b.shape:
        return None
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))
