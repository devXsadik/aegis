"""Baseline vehicle attributes: body colour, night detection, re-ID vectors."""
import numpy as np
import pytest

from core.analysis import vehicle_attrs as va


def car(body_bgr, window_bgr=(30, 30, 30), road_bgr=(90, 90, 90)):
    img = np.zeros((100, 160, 3), np.uint8)
    img[:] = road_bgr
    img[10:45, 20:140] = window_bgr          # dark windows on top
    img[45:85, 10:150] = body_bgr            # body
    return img


@pytest.mark.parametrize("bgr,name", [((245, 245, 245), "white"), ((20, 20, 20), "black"), ((40, 40, 200), "red"),
                                      ((200, 80, 30), "blue"), ((40, 180, 40), "green"), ((150, 150, 150), "silver"),
                                      ((95, 95, 95), "grey"), ((20, 200, 230), "yellow"), ((30, 30, 100), "maroon")])
def test_body_colour_ignores_windows_and_road(bgr, name):
    color, share = va.dominant_color(car(bgr))
    assert color == name and share > 0.6


def test_night_detection():
    assert va.is_night(np.full((40, 40, 3), 120, np.uint8))          # IR: equal channels
    assert va.is_night(np.full((40, 40, 3), (10, 20, 15), np.uint8))  # very dark
    assert not va.is_night(car((40, 40, 200)))
    out = va.classify(np.full((100, 160, 3), 130, np.uint8), "car", 0.9)
    assert out["is_night"] and out["confidences"]["color"] < 0.4 and out["model"] == "baseline-v1"


def test_type_from_detector():
    assert va.type_from_detector("truck", 0.9)[0] == "truck"
    assert va.type_from_detector("person")[0] == "other"
    assert va.type_from_detector(None) == (None, 0.0)


def test_reid_same_vehicle_closer_than_other():
    a = car((245, 245, 245))
    a2 = car((240, 240, 240))
    b = car((40, 40, 200))
    va_, _ = va.reid_embedding(a)
    va2, name = va.reid_embedding(a2)
    vb, _ = va.reid_embedding(b)
    assert name == "hist-v1" and abs(np.linalg.norm(va_) - 1) < 1e-5
    assert va.cosine(va_, va2) > va.cosine(va_, vb)
    assert va.cosine(va_, None) is None
