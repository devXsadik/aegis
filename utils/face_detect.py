"""Face localisation: fast HOG first, accurate CNN when HOG finds nothing.

dlib's HOG detector is fast but misses faces that are dim, low-contrast, slightly turned
or partly occluded; on this project's laptop webcam it found no face in any frame while
the CNN detector found it every time. The CNN costs seconds on CPU, so it only runs as
a fallback, on a downscaled copy, and callers can gate it.
"""

import os
from typing import List, Tuple

Box = Tuple[int, int, int, int]          # (top, right, bottom, left) like face_recognition

CNN_ENABLED = os.getenv("FACE_CNN_FALLBACK", "true").lower() == "true"
CNN_MAX_DIM = int(os.getenv("FACE_CNN_MAX_DIM", "640"))


def locate_faces(rgb, face_recognition, *, upsample: int = 1, cnn_fallback: bool = True,
                 cnn_max_dim: int = CNN_MAX_DIM) -> List[Box]:
    """Return face boxes in `rgb`'s own coordinates. The caller holds any dlib lock."""
    boxes = face_recognition.face_locations(rgb, model="hog", number_of_times_to_upsample=upsample)
    if boxes or not (cnn_fallback and CNN_ENABLED):
        return list(boxes)

    import cv2
    h, w = rgb.shape[:2]
    scale = min(1.0, cnn_max_dim / max(h, w))
    small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    found = face_recognition.face_locations(small, model="cnn", number_of_times_to_upsample=0)
    if scale >= 1:
        return list(found)
    inv = 1.0 / scale
    return [(max(0, int(t * inv)), min(w, int(r * inv)), min(h, int(b * inv)), max(0, int(l * inv)))
            for (t, r, b, l) in found]
