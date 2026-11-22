"""FightDetector: a sustained close, fast exchange is flagged; near-misses are not."""

import math

from core.analysis.fight import FightDetector


def pose(x, y, wrist_dx=0.0, wrist_dy=0.0, conf=0.9):
    """A 100x300 person box at (x, y) with wrists offset from the chest."""
    box = (x, y, x + 100, y + 300)
    kpts = {"left_wrist": (x + 20 + wrist_dx, y + 120 + wrist_dy, conf),
            "right_wrist": (x + 80 - wrist_dx, y + 120 - wrist_dy, conf)}
    return {"bbox": box, "kpts": kpts}


def swinging(t, x, phase=0.0):
    """Arms swinging ~2 body-heights per second (a punch is faster than that)."""
    return pose(x, 100, wrist_dx=120 * math.sin(6 * t + phase), wrist_dy=90 * math.cos(6 * t + phase))


def run(det, frames):
    out = set()
    for i, poses in enumerate(frames):
        out = det.update(i * 0.25, poses)
    return out


def test_two_people_trading_blows_are_flagged_after_it_lasts():
    det = FightDetector()
    frames = [{1: swinging(i * 0.25, 100), 2: swinging(i * 0.25, 180, 1.0)} for i in range(8)]
    assert run(det, frames[:3]) == set()                       # one exchange is not a fight
    assert run(det, frames) == {1, 2}


def test_far_apart_or_only_one_moving_or_still_is_not_a_fight():
    far = [{1: swinging(i * 0.25, 100), 2: swinging(i * 0.25, 600)} for i in range(8)]
    one = [{1: swinging(i * 0.25, 100), 2: pose(180, 100)} for i in range(8)]
    calm = [{1: pose(100, 100), 2: pose(180, 100)} for i in range(8)]
    depth = [{1: swinging(i * 0.25, 100), 2: {**swinging(i * 0.25, 160), "bbox": (160, 100, 200, 220)}} for i in range(8)]
    for frames in (far, one, calm, depth):
        assert run(FightDetector(), frames) == set()


def test_off_unless_configured():
    assert FightDetector.from_config(None) is None and FightDetector.from_config({"enabled": False}) is None
    assert FightDetector.from_config({"enabled": True, "min_hits": 5}).min_hits == 5
