"""Guards against the false alarms seen on a webcam: a body or coat taken for a weapon, a coat on a
hook taken for a person, one-frame "raised arms", and an armed subject "tracked" on their own camera."""

import numpy as np

from core.analysis.behavior import ReasonSustain
from core.analysis.weapon_confirm import UNASSIGNED, WeaponScreen, associate
from core.pipeline.stages.tracking import TrackingStage
from core.tracking.cross_camera import CrossCameraTracker


class T:
    def __init__(self, tid, box, conf=0.9):
        self.track_id, self.box, self.det_conf = tid, box, conf

    def is_confirmed(self):
        return True

    def to_ltrb(self):
        return self.box


PERSON = (300, 50, 900, 720)
FRAME = (720, 1280, 3)


def det(box, score=0.6, name="churi"):
    return {"bbox": box, "score": score, "class_name": name}


def test_a_box_the_size_of_the_body_or_frame_is_not_a_weapon():
    s = WeaponScreen()
    body = det((10, 0, 1050, 720), 0.8)                             # what the model called "churi" on a webcam
    assert not s.fits_frame(body, FRAME)
    torso = det((320, 60, 880, 700), 0.8)                           # inside the frame limit, but it is the person
    kept = s.screen(associate([torso], [T(1, PERSON)]), [T(1, PERSON)])
    assert kept == {}
    knife = det((820, 300, 900, 420), 0.8)                          # a knife-sized box in the hand area
    assert s.fits_frame(knife, FRAME)
    assert 1 in s.screen(associate([knife], [T(1, PERSON)]), [T(1, PERSON)])


def test_hidden_hands_and_weak_classes_need_more_confidence():
    s = WeaponScreen(class_min_score={"rod": 0.6})
    weak = det((820, 300, 900, 420), 0.45)
    assert s.screen(associate([weak], [T(1, PERSON)]), [T(1, PERSON)]) == {}       # no pose: was kept at any score
    assert not s.fits_frame(det((820, 300, 900, 420), 0.55, "rod"), FRAME)
    unheld = det((1000, 100, 1100, 300), 0.6)                                         # off the person
    assert UNASSIGNED not in s.screen(associate([unheld], [T(1, PERSON)]), [T(1, PERSON)])


def test_only_confident_person_tracks_are_passed_on():
    class Tracker:
        def __init__(self):
            self.frames = []

        def track(self, dets, frame):
            return self.frames.pop(0)

    tr = Tracker()
    stage = TrackingStage(tr, person_confirm_conf=0.6)
    coat = T(2, (1000, 50, 1100, 650), 0.54)
    person = T(1, PERSON, 0.45)
    tr.frames = [[person, coat], [T(1, PERSON, 0.92), coat], [T(1, PERSON, None), coat]]
    assert stage._sure(tr.track(None, None)) == []                  # neither sure yet
    assert [t.track_id for t in stage._sure(tr.track(None, None))] == [1]
    assert [t.track_id for t in stage._sure(tr.track(None, None))] == [1]   # stays a person while coasting


def test_raised_arms_must_last_before_it_counts():
    s = ReasonSustain()
    assert s.update(1, ["raised_arms"], 0.0) == []
    assert s.update(1, ["raised_arms"], 1.0) == []
    assert s.update(1, ["raised_arms"], 2.0) == []                  # phone held up for 2 s
    assert s.update(1, ["raised_arms"], 3.0) == ["raised_arms"]
    assert s.update(1, ["raised_arms"], 10.0) == []                 # gap: starts again
    assert s.update(1, ["loitering"], 10.0) == ["loitering"]        # time-based already


def test_armed_subject_is_not_tracked_on_their_own_track():
    xt = CrossCameraTracker(embed_fn=lambda crop: np.ones(8, np.float32), threshold=0.5, votes=1)
    xt.enabled = True
    frame = np.zeros((720, 1280, 3), np.uint8)
    xt.step("cam", "Desk", 10.0, frame, [(1, PERSON, "armed:cam:1", "Armed person", "WEAPON_DETECTED", None)], [])
    # Next frames: the weapon is not re-confirmed, the same track is now among the others.
    found = {}
    for t in (13.0, 14.5, 16.0):
        found = xt.step("cam", "Desk", t, frame, [], [(1, PERSON)])
    assert found == {}
    # A different track that looks the same (left and came back, or another camera) is still followed.
    for t in (17.5, 19.0):
        found = xt.step("cam2", "Gate", t, frame, [], [(5, PERSON)])
    assert 5 in found
