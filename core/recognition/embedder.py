"""Face embeddings for watchlist matching (ArcFace-family).

Default: OpenCV's SFace (models/face_recognition_sface_2021dec.onnx, 128-d, cosine; trained with an
ArcFace-style margin loss) aligned with the YuNet landmarks the system already uses — it runs on
OpenCV alone, no extra runtime. A heavier ArcFace (e.g. InsightFace w600k_r50) can be plugged in
by implementing `Embedder` and setting FACE_EMBEDDER. Vectors are L2-normalised; similarity is the
dot product. A vector is only comparable with vectors of the same `name`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

SFACE_MODEL = Path(os.getenv("FACE_SFACE_MODEL") or Path(__file__).resolve().parents[2] / "models"
                   / "face_recognition_sface_2021dec.onnx")
SFACE_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/"
             "face_recognition_sface_2021dec.onnx")


class Embedder:
    name = "none"
    dim = 0

    def available(self) -> bool:
        return False

    def embed(self, bgr: np.ndarray, face_row: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        raise NotImplementedError


class SFaceEmbedder(Embedder):
    name = "sface-2021dec"
    dim = 128

    def __init__(self):
        self._rec = None
        self._det = None

    def available(self) -> bool:
        return cv2 is not None and SFACE_MODEL.is_file() and hasattr(cv2, "FaceRecognizerSF")

    def _models(self):
        if self._rec is None:
            self._rec = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")
            from utils.face_detect import YUNET_MODEL
            if YUNET_MODEL.is_file():
                self._det = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (320, 320), 0.6, 0.3, 20)
        return self._rec, self._det

    def detect(self, bgr: np.ndarray) -> Optional[np.ndarray]:
        """Largest face row from YuNet: [x, y, w, h, 5 landmarks (10), score]."""
        _, det = self._models()
        if det is None:
            return None
        h, w = bgr.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(bgr)
        if faces is None or len(faces) == 0:
            return None
        return max(faces, key=lambda f: f[2] * f[3])

    def embed(self, bgr, face_row=None):
        rec, _ = self._models()
        row = face_row if face_row is not None else self.detect(bgr)
        if row is None:
            return None
        aligned = rec.alignCrop(bgr, row)
        v = rec.feature(aligned).ravel().astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-9)


_current: Optional[Embedder] = None


def get() -> Embedder:
    global _current
    if _current is None:
        _current = SFaceEmbedder()
    return _current


def set_embedder(e: Optional[Embedder]) -> None:
    """Tests and alternative models install their own."""
    global _current
    _current = e


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))


def to_bytes(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_bytes(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def best(vec: np.ndarray, matrix: np.ndarray) -> Tuple[int, float]:
    sims = matrix @ vec
    i = int(np.argmax(sims))
    return i, float(sims[i])
