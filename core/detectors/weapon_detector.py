"""Weapon detector.

On CCTV a weapon is 15-40 px across; the model was trained on photos where it is ~100 px, and
scanning a 1920x1080 frame at 640 px shrinks it three times more. `mode` decides where it looks:

    full         the whole frame (old behaviour; finds close-ups and weapons nobody holds)
    person_crop  each person (box widened to take in outstretched arms) cut out and enlarged to
                 `crop_size`, so a knife in a hand is back at the size the model knows. One batched
                 pass for up to `max_crops` people (most confident first).
    both         full frame + person crops, overlapping boxes merged (default)
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np
from ultralytics import YOLO

from core.detectors.device import lock_for, read_boxes

MODES = ("full", "person_crop", "both")


def crop_region(box, frame_shape, pad_x: float = 0.35, pad_y: float = 0.12):
    """Person box widened (arms, a raised blade) and clipped to the frame → (x1, y1, x2, y2)."""
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    return (max(0, int(x1 - pad_x * bw)), max(0, int(y1 - pad_y * bh)),
            min(w, int(x2 + pad_x * bw)), min(h, int(y2 + pad_y * bh)))


def to_frame(box, region, scale: float):
    """A box found in an enlarged crop → frame coordinates."""
    rx, ry = region[0], region[1]
    return (int(rx + box[0] / scale), int(ry + box[1] / scale),
            int(rx + box[2] / scale), int(ry + box[3] / scale))


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def merge(dets: Sequence[dict], iou: float = 0.45) -> List[dict]:
    """Class-agnostic NMS: the same weapon seen in the frame and in a crop (or in two overlapping
    crops) is kept once, with the higher score."""
    kept: List[dict] = []
    for d in sorted(dets, key=lambda d: d["score"], reverse=True):
        if all(_iou(d["bbox"], k["bbox"]) < iou for k in kept):
            kept.append(d)
    return kept


class WeaponDetector:
    def __init__(self, model_path: str, conf_threshold: float = 0.4, device: str = "cpu",
                 mode: str = "both", crop_size: int = 640, max_crops: int = 4, min_person_px: int = 40):
        self.model = YOLO(model_path)
        self.names = dict(getattr(self.model, "names", {}) or {})
        self.conf_threshold = conf_threshold
        self.device = device
        self.mode = mode if mode in MODES else "both"
        self.crop_size = crop_size
        self.max_crops = max_crops
        self.min_person_px = min_person_px      # smaller people: even enlarged, nothing to see
        self._lock = lock_for(device)

    def _det(self, x1, y1, x2, y2, conf, cls) -> dict:
        return {"bbox": (x1, y1, x2, y2), "score": conf, "class_id": cls,
                "class_name": self.names.get(cls, "weapon")}

    def _crops(self, frame: np.ndarray, people) -> list:
        """[(region, scale, image)] for the people worth a closer look."""
        import cv2
        picked = sorted((p for p in people or [] if (p[0][3] - p[0][1]) >= self.min_person_px),
                        key=lambda p: p[1], reverse=True)[: self.max_crops]
        out = []
        for box, _conf, _cls in picked:
            region = crop_region(box, frame.shape)
            rw, rh = region[2] - region[0], region[3] - region[1]
            if rw < 8 or rh < 8:
                continue
            scale = self.crop_size / max(rw, rh)
            if scale <= 1.15:                  # already big: the full-frame pass sees it well enough
                if self.mode == "both":
                    continue
                scale = 1.0
            img = frame[region[1]:region[3], region[0]:region[2]]
            if scale != 1.0:
                img = cv2.resize(img, (int(rw * scale), int(rh * scale)), interpolation=cv2.INTER_LINEAR)
            out.append((region, scale, img))
        return out

    def detect(self, frame: np.ndarray, people: Optional[list] = None):
        """`people`: the person detections of this frame ([box, conf, cls]); needed for crops."""
        crops = self._crops(frame, people) if self.mode != "full" and people else []
        full = self.mode in ("full", "both") or not crops     # person_crop with nobody usable: whole frame
        images = ([frame] if full else []) + [c[2] for c in crops]
        if not images:
            return []
        with self._lock:
            results = self.model(images, conf=self.conf_threshold, verbose=False, device=self.device)
            per_image = [read_boxes([r]) for r in results]       # tensor reads inside the lock
        dets = []
        if full:
            dets += [self._det(*b) for b in per_image.pop(0)]
        for (region, scale, _img), boxes in zip(crops, per_image):
            for x1, y1, x2, y2, conf, cls in boxes:
                dets.append(self._det(*to_frame((x1, y1, x2, y2), region, scale), conf, cls))
        return merge(dets) if crops else dets
