"""Face embeddings for watchlist matching (ArcFace-family).

Default: OpenCV's SFace (models/face_recognition_sface_2021dec.onnx, 128-d, cosine; trained with an
ArcFace-style margin loss) aligned with the YuNet landmarks the system already uses — it runs on
OpenCV alone, no extra runtime. A stronger ArcFace-class model (512-d, e.g. an ArcFace/AdaFace
ResNet-50 exported to ONNX) is used when FACE_EMBEDDER=arcface and the file exists
(FACE_ARCFACE_MODEL, default models/face_arcface.onnx): much better on small, blurry CCTV faces.
Check the licence of the weights you use (InsightFace's are non-commercial). After switching, run
scripts/reembed_faces.py once and re-tune the face thresholds in Settings. Vectors are L2-normalised; similarity is the
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


class _YuNetDetect:
    _det = None

    def detect(self, bgr: np.ndarray) -> Optional[np.ndarray]:
        """Largest face row from YuNet: [x, y, w, h, 5 landmarks (10), score]."""
        if self._det is None:
            from utils.face_detect import YUNET_MODEL
            if not YUNET_MODEL.is_file():
                return None
            self._det = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (320, 320), 0.6, 0.3, 20)
        h, w = bgr.shape[:2]
        self._det.setInputSize((w, h))
        _, faces = self._det.detect(bgr)
        if faces is None or len(faces) == 0:
            return None
        return max(faces, key=lambda f: f[2] * f[3])


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


ARCFACE_MODEL = Path(os.getenv("FACE_ARCFACE_MODEL") or Path(__file__).resolve().parents[2] / "models"
                     / "face_arcface.onnx")
# Standard ArcFace 112x112 positions of: eye (image left), eye (image right), nose, mouth corners.
ARCFACE_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                             [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


def align_112(bgr: np.ndarray, row: np.ndarray) -> Optional[np.ndarray]:
    """Similarity-transform the face so its 5 YuNet landmarks land on the ArcFace template."""
    pts = np.asarray(row[4:14], dtype=np.float32).reshape(5, 2)
    m, _ = cv2.estimateAffinePartial2D(pts, ARCFACE_TEMPLATE, method=cv2.LMEDS)
    if m is None:
        return None
    return cv2.warpAffine(bgr, m, (112, 112), borderValue=0)


class ArcFaceEmbedder(_YuNetDetect, Embedder):
    """512-d ArcFace-family ONNX model (input 1x3x112x112, RGB, (x-127.5)/127.5)."""

    dim = 512

    def __init__(self, path: Path = ARCFACE_MODEL):
        self.path = Path(path)
        self.name = os.getenv("FACE_ARCFACE_NAME") or f"arcface-{self.path.stem}"
        self._sess = None
        self._net = None

    def available(self) -> bool:
        return cv2 is not None and self.path.is_file()

    def _run(self, blob: np.ndarray) -> np.ndarray:
        if self._sess is None and self._net is None:
            try:
                import onnxruntime as ort
                self._sess = ort.InferenceSession(str(self.path), providers=ort.get_available_providers())
            except ImportError:
                self._net = cv2.dnn.readNetFromONNX(str(self.path))
        if self._sess is not None:
            return self._sess.run(None, {self._sess.get_inputs()[0].name: blob})[0]
        self._net.setInput(blob)
        return self._net.forward()

    def embed(self, bgr, face_row=None):
        row = face_row if face_row is not None else self.detect(bgr)
        if row is None:
            return None
        face = align_112(bgr, row)
        if face is None:
            return None
        blob = ((face[:, :, ::-1].astype(np.float32) - 127.5) / 127.5).transpose(2, 0, 1)[None]
        v = np.asarray(self._run(np.ascontiguousarray(blob))).ravel().astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-9)


_current: Optional[Embedder] = None


def choose() -> Embedder:
    """FACE_EMBEDDER=arcface uses the ArcFace model when its file exists, else SFace."""
    if os.getenv("FACE_EMBEDDER", "sface").lower() == "arcface":
        arc = ArcFaceEmbedder()
        if arc.available():
            return arc
    return SFaceEmbedder()


def get() -> Embedder:
    global _current
    if _current is None:
        _current = choose()
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
