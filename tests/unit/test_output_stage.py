"""OutputStage: which pipeline results become alerts, evidence and live flags.

Every alert the operator sees is raised here, so each path is pinned: watchlist match, weapon
(confirmation + in-hand screen), fall, suspicious behaviour, plates, zone anomalies.
"""

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import core.pipeline.stages.output as output_mod
from core.analysis.weapon_confirm import UNASSIGNED
from core.pipeline.base import FrameContext
from core.pipeline.stages.output import OutputStage


class Track:
    def __init__(self, tid, box=(100, 50, 200, 350)):
        self.track_id, self._box, self.time_since_update = tid, box, 0

    def is_confirmed(self):
        return True

    def to_ltrb(self):
        return self._box


class NoCrossCamera:
    targets: dict = {}

    def step(self, *a, **k):
        return {}


@pytest.fixture
def stage(monkeypatch):
    saved = MagicMock()
    monkeypatch.setattr(output_mod, "save_evidence_db", saved)
    monkeypatch.setattr(output_mod, "publish_vehicle_detection", MagicMock())
    s = OutputStage(camera_location="Gate", evidence_throttle_seconds=10.0)
    s.cross_camera = NoCrossCamera()
    s.capturer = MagicMock(include_suspicious=False)
    s.saved = saved
    with patch("utils.alerts.notification_hub.dispatch_alert") as dispatch:
        s.dispatch = dispatch
        yield s


def ctx(t=None, **kw):
    c = FrameContext(frame=np.zeros((480, 640, 3), np.uint8), timestamp=t or time.time(),
                     camera_id="gate_1", camera_location="Gate")
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def sent(stage):
    return [c.kwargs for c in stage.dispatch.call_args_list]


def _wait_saved(stage, n=1):
    end = time.time() + 2
    while stage.saved.call_count < n and time.time() < end:
        time.sleep(0.01)
    return stage.saved.call_count


def test_watchlist_match_alerts_saves_evidence_and_flags_the_tile(stage):
    out = stage.process(ctx(tracks=[Track(7)], criminal_ids={7}, identities={7: "Sadik"},
                            identity_conf={7: 0.81}, active_criminals=["Sadik"]))
    (a,) = sent(stage)
    assert (a["alert_type"], a["person_name"], a["track_id"], a["confidence"]) == ("CRIMINAL_DETECTED", "Sadik", 7, 0.81)
    assert _wait_saved(stage) == 1
    assert stage.capturer.capture.call_args.kwargs["alert_type"] == "CRIMINAL_DETECTED"
    assert out.live_flags == [{"type": "CRIMINAL_DETECTED", "label": "Sadik", "origin": ""}]
    assert out.threat_score == 5 + 50


def test_evidence_is_throttled_per_track(stage):
    now = time.time()
    for dt in (0, 1, 2):
        stage.process(ctx(now + dt, tracks=[Track(3)], suspicious_tracks={3: ["loitering"]}))
    assert _wait_saved(stage) == 1
    stage.process(ctx(now + 11, tracks=[Track(3)], suspicious_tracks={3: ["loitering"]}))
    assert _wait_saved(stage, 2) == 2


def _weapon(box=(150, 180, 180, 220), score=0.5):
    return {"bbox": box, "score": score, "class_id": 0}


def _hand_at(x, y):
    return {7: {"kpts": {"right_wrist": (x, y, 0.9)}}}


def test_held_weapon_alerts_on_the_fourth_of_six_frames(stage):
    now = time.time()
    for i in range(4):
        stage.process(ctx(now + i, tracks=[Track(7)], weapon_detections=[_weapon()], poses=_hand_at(160, 200)))
        assert len(sent(stage)) == (1 if i == 3 else 0)
    a = sent(stage)[0]
    assert a["alert_type"] == "WEAPON_DETECTED" and a["track_id"] == 7
    assert "(in hand)" in a["message"]


def test_weak_weapon_away_from_the_hands_never_alerts(stage):
    now = time.time()
    for i in range(5):
        stage.process(ctx(now + i, tracks=[Track(7)], weapon_detections=[_weapon((150, 60, 180, 90))],
                          poses={7: {"kpts": {"left_wrist": (110, 340, 0.9), "right_wrist": (190, 340, 0.9)}}}))
    assert sent(stage) == []


def test_tiny_weapon_boxes_never_alert(stage):
    now = time.time()
    for i in range(5):
        stage.process(ctx(now + i, tracks=[Track(7)], weapon_detections=[_weapon((150, 180, 158, 186), 0.9)]))
    assert sent(stage) == []


def test_confident_weapon_on_nobody_alerts_as_unassigned(stage):
    now = time.time()
    for i in range(4):
        stage.process(ctx(now + i, weapon_detections=[_weapon((500, 400, 560, 440), 0.8)]))
    (a,) = sent(stage)
    assert a["alert_type"] == "WEAPON_DETECTED" and a["track_id"] == UNASSIGNED


def test_fall_and_suspicious_behaviour_alert(stage):
    stage.process(ctx(tracks=[Track(4)], fall_tracks={4: {"bbox": (0, 0, 1, 1)}},
                      suspicious_tracks={4: ["staggering"]}))
    types = sorted(a["alert_type"] for a in sent(stage))
    assert types == ["FALL_SUSPECTED", "SUSPICIOUS_BEHAVIOR"]


def test_zone_anomalies_alert_but_line_crossings_only_count(stage):
    stage.process(ctx(anomalies=[
        {"type": "line_cross", "message": "crossed"},
        {"type": "intrusion", "message": "in restricted area", "zone": "Vault", "track_id": 2},
    ]))
    (a,) = sent(stage)
    assert a["alert_type"] == "INTRUSION" and a["zone"] == "Vault"


def test_watchlisted_plate_alerts_and_other_plates_are_stored_once(stage):
    car = {"bbox": (10, 10, 200, 120), "score": 0.9, "class_id": 2, "class_name": "car"}
    plate = {"plate_number": "DHA-1234", "track_id": 5, "vehicle_bbox": car["bbox"], "confidence": 0.9}
    stage.process(ctx(vehicle_detections=[car], watchlisted_plates=[plate], plate_detections=[plate]))
    (a,) = sent(stage)
    assert a["alert_type"] == "SUSPICIOUS_VEHICLE" and a["plate_number"] == "DHA-1234"
    other = {"plate_number": "DHA-9999", "track_id": 6, "vehicle_bbox": car["bbox"], "confidence": 0.8}
    for _ in range(3):
        stage.process(ctx(vehicle_detections=[car], plate_detections=[other]))
    output_mod.publish_vehicle_detection.assert_called_once()
    assert output_mod.publish_vehicle_detection.call_args.kwargs["vehicle_type"] == "car"
