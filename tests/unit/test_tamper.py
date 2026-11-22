"""TamperDetector on synthetic frames: each condition fires, normal life does not."""

import cv2
import numpy as np

from core.analysis.tamper import TamperDetector

RNG = np.random.default_rng(7)
# A "scene" like a real view: large shapes (walls, floor, objects) plus fine texture and edges.
_shapes = cv2.resize(RNG.integers(30, 220, (9, 16, 3), dtype=np.uint8), (640, 360), interpolation=cv2.INTER_NEAREST)
_texture = cv2.GaussianBlur(RNG.integers(0, 60, (360, 640, 3), dtype=np.uint8), (3, 3), 0)
SCENE = np.clip(_shapes.astype(np.int16) + _texture - 30, 0, 255).astype(np.uint8)


def noisy(img):
    """Sensor noise: consecutive frames of a still scene are never pixel-identical."""
    return np.clip(img.astype(np.int16) + RNG.integers(-3, 4, img.shape), 0, 255).astype(np.uint8)


def run(det, frames, start=0.0):
    """Feed one frame per second; return [(t, kind)] reported."""
    out = []
    for i, f in enumerate(frames):
        k = det.check(f, start + i)
        if k:
            out.append((start + i, k))
    return out


def warm(det, seconds=15):
    assert run(det, [noisy(SCENE) for _ in range(seconds)]) == []
    return seconds


def test_healthy_still_scene_never_alerts():
    det = TamperDetector()
    assert run(det, [noisy(SCENE) for _ in range(180)]) == []


def test_covered_lens_reports_once_after_it_persists():
    det = TamperDetector(persist=5)
    t = warm(det)
    got = run(det, [np.full_like(SCENE, 4) for _ in range(30)], start=t)
    assert got == [(t + 5, "covered")]


def test_uniform_bright_cover_also_counts():
    det = TamperDetector(persist=5)
    t = warm(det)
    assert run(det, [noisy(np.full_like(SCENE, 200)) for _ in range(8)], start=t)[0][1] == "covered"


def test_blurred_lens():
    det = TamperDetector(persist=5)
    t = warm(det)
    blurred = cv2.GaussianBlur(SCENE, (31, 31), 12)
    got = run(det, [noisy(blurred) for _ in range(10)], start=t)
    assert got and got[0][1] == "blurred"


def test_camera_turned_to_a_new_steady_view_reports_moved_once():
    det = TamperDetector(persist=5)
    t = warm(det)
    turned = np.ascontiguousarray(SCENE[::-1, ::-1])          # a different view of similar texture
    got = run(det, [noisy(turned) for _ in range(40)], start=t)
    assert [k for _, k in got] == ["moved"]                    # and the new view becomes normal


def test_person_walking_past_is_not_a_move():
    det = TamperDetector(persist=5)
    t = warm(det)
    frames = []
    for i in range(40):
        f = SCENE.copy()
        x = (i * 60) % 560
        f[60:340, x:x + 80] = (40, 40, 40)                      # a dark figure crossing the view
        frames.append(noisy(f))
    assert run(det, frames, start=t) == []


def test_frozen_picture():
    det = TamperDetector(frozen_seconds=20)
    t = warm(det)
    still = noisy(SCENE)
    got = run(det, [still] * 30, start=t)
    assert got == [(t + 21, "frozen")]                          # first identical pair at t+1


def test_samples_once_per_interval_and_respects_cooldown():
    det = TamperDetector(persist=2, cooldown=100)
    black = np.zeros_like(SCENE)
    assert det.check(black, 0.0) is None
    assert det.check(black, 0.5) is None                        # skipped: within `every`
    run(det, [black] * 5, start=1)
    assert det._fired["covered"] >= 2
    assert run(det, [black] * 50, start=10) == []               # still covered: no repeat inside cooldown


def test_from_config():
    assert TamperDetector.from_config({"enabled": False}) is None
    det = TamperDetector.from_config({"persist": 9, "checks": ["covered"]})
    assert det.persist == 9 and det.checks == {"covered"}
