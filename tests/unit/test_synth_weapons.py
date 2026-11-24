"""Synthetic CCTV weapon data: labels must match what was pasted, splits must not mix."""
import random

import cv2
import numpy as np

from training import synth_weapons as sw


def knife(h=40, w=160):
    """A bright elongated blade on a plain photo background."""
    img = np.full((h, w, 3), 30, np.uint8)
    cv2.rectangle(img, (10, h // 2 - 5), (w - 10, h // 2 + 5), (230, 230, 230), -1)
    return img


def test_cutout_keeps_the_blade_and_drops_the_background():
    rgba = sw.cutout(knife())
    assert rgba.shape[2] == 4
    assert rgba[20, 80, 3] > 200            # blade kept
    assert rgba[3, 3, 3] < 60               # corner background removed


def test_squarish_failed_cutout_is_rejected():
    flat = np.full((80, 80, 3), 120, np.uint8)      # nothing to separate
    assert sw.cutout(flat) is None


def test_paste_returns_the_box_of_the_visible_weapon():
    rng = random.Random(1)
    frame = np.full((540, 960, 3), 90, np.uint8)
    person = ((400.0, 100.0, 520.0, 460.0), {"left_wrist": (420.0, 300.0), "right_wrist": None})
    rgba = sw.cutout(knife())
    box = None
    for _ in range(20):
        box = sw.paste(frame, rgba, "churi", person, rng)
        if box:
            break
    assert box is not None
    x1, y1, x2, y2 = box
    length = max(x2 - x1, y2 - y1)
    assert 0.05 * 360 <= length <= 0.25 * 360     # churi: 10-20 % of the person's height
    assert abs((x1 + x2) / 2 - 420) < 120 and abs((y1 + y2) / 2 - 300) < 120   # at the hand
    assert frame[y1:y2, x1:x2].max() > 150        # something bright was really pasted there


def test_person_view_maps_labels_into_the_enlarged_crop():
    img = np.zeros((540, 960, 3), np.uint8)
    labels = [(0, (430, 290, 450, 300)), (1, (10, 10, 20, 20))]       # one in the crop, one far away
    crop, out = sw.person_view(img, labels, (400, 100, 520, 460))
    assert max(crop.shape[:2]) == 640
    assert len(out) == 1 and out[0][0] == 0
    x1, y1, x2, y2 = out[0][1]
    assert (x2 - x1) > 20 * 1.3                   # enlarged (crop 446 px tall → 640)


def test_time_slices_do_not_overlap():
    edges = [sw.CUTS[s] for s in sw.SPLITS]
    assert edges[0][1] == edges[1][0] and edges[1][1] == edges[2][0] and edges[2][1] == 1.0


def test_class_schemes_cover_every_source_class():
    for n, (names, mapping) in sw.SCHEMES.items():
        assert len(names) == n and set(mapping) == set(sw.SRC_NAMES)
        assert set(mapping.values()) == set(range(n))
