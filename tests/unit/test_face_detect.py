"""HOG first, CNN only as a fallback; boxes come back in the original image's coordinates."""
import types

import numpy as np

from utils import face_detect


class FakeFR:
    def __init__(self, hog=(), cnn=()):
        self.hog, self.cnn, self.calls = list(hog), list(cnn), []

    def face_locations(self, img, model="hog", number_of_times_to_upsample=1):
        self.calls.append((model, img.shape[:2]))
        return self.hog if model == "hog" else self.cnn


def _img(h=720, w=1280):
    return np.zeros((h, w, 3), np.uint8)


def test_hog_hit_skips_cnn():
    fr = FakeFR(hog=[(10, 60, 70, 20)])
    assert face_detect.locate_faces(_img(), fr) == [(10, 60, 70, 20)]
    assert [c[0] for c in fr.calls] == ["hog"]


def test_cnn_fallback_runs_on_downscaled_copy_and_maps_back():
    fr = FakeFR(cnn=[(50, 150, 150, 50)])             # found at 640x360 (scale 0.5)
    boxes = face_detect.locate_faces(_img(720, 1280), fr, cnn_max_dim=640)
    assert boxes == [(100, 300, 300, 100)]            # mapped to the 1280x720 frame
    assert fr.calls[1] == ("cnn", (360, 640))


def test_cnn_fallback_can_be_disabled_per_call_and_globally(monkeypatch):
    fr = FakeFR(cnn=[(1, 2, 3, 4)])
    assert face_detect.locate_faces(_img(), fr, cnn_fallback=False) == []
    assert [c[0] for c in fr.calls] == ["hog"]
    monkeypatch.setattr(face_detect, "CNN_ENABLED", False)
    assert face_detect.locate_faces(_img(), FakeFR(cnn=[(1, 2, 3, 4)])) == []


def test_recognizer_limits_cnn_fallback_with_cooldown(monkeypatch):
    from core.recognition import face_recognizer_db as mod
    fr = FakeFR()                                      # never finds a face
    monkeypatch.setattr(mod, "face_recognition", types.SimpleNamespace(face_locations=fr.face_locations),
                        raising=False)
    rec = mod.FaceRecognizerDB(cnn_cooldown=60)
    roi = np.zeros((200, 200, 3), np.uint8)
    for _ in range(4):
        rec.recognize_detail(roi)
    models = [c[0] for c in fr.calls]
    assert models.count("cnn") == 1 and models.count("hog") == 4   # CNN only once per cooldown
