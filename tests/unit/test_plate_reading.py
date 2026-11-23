"""Plate reading with a plate detector: crop, two-line join, plausibility."""
import numpy as np

from core.analysis.anpr import LicensePlateRecognizer, join_lines, prepare_plate


def _box(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def test_join_lines_orders_two_line_bd_plate():
    reads = [(_box(10, 40, 90, 60), "১২-৩৪৫৬", 0.9), (_box(50, 5, 90, 25), "গ", 0.8), (_box(5, 6, 45, 24), "ঢাকা মেট্রো", 0.7)]
    text, conf = join_lines(reads)
    assert text == "ঢাকামেট্রোগ123456"
    assert conf == 0.7


def test_prepare_plate_upscales_and_greys():
    out = prepare_plate(np.zeros((20, 60, 3), np.uint8))
    assert out.ndim == 2 and out.shape[0] == 64


class _Det:
    def detect(self, roi):
        return [((20, 30, 80, 50), 0.9)]


class _Reader:
    def __init__(self):
        self.shapes = []

    def readtext(self, img):
        self.shapes.append(img.shape)
        return [(_box(0, 0, 50, 20), "DHA 11", 0.8), (_box(0, 30, 50, 50), "2345", 0.9)]


def test_detector_path_reads_only_the_plate_crop():
    r = LicensePlateRecognizer(plate_detector=_Det())
    r._reader = _Reader()
    plates = r.detect_plates(np.zeros((100, 120, 3), np.uint8))
    assert plates[0]["plate_number"] == "DHA112345"
    assert plates[0]["confidence"] == round(0.8 * 0.9, 4)
    x1, y1, x2, y2 = plates[0]["bbox"]
    assert 15 <= x1 <= 20 and x2 <= 85 and r._reader.shapes[0][0] == 64
