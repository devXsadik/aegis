"""HUD drawing (the local window and the 'full' stream overlay): every part draws, nothing crashes."""

import time

import numpy as np

from core.pipeline.base import FrameContext
from core.visualization import hud


class Track:
    def __init__(self, tid, box):
        self.track_id, self._box, self.time_since_update = tid, box, 0

    def is_confirmed(self):
        return True

    def to_ltrb(self):
        return self._box


def _frame():
    return np.zeros((480, 640, 3), np.uint8)


def test_each_part_draws_on_the_frame():
    f = _frame()
    hud.draw_box(f, 10, 10, 100, 200, "Person", (0, 255, 0))
    hud.draw_sci_fi_box(f, 120, 10, 220, 200, (0, 0, 255))
    hud.draw_rec_indicator(f, 12.5)
    for score in (0, 30, 80):
        hud.draw_threat_level(f, score)
    hud.draw_radar(f, [Track(1, (100, 100, 150, 300)), Track(2, (400, 50, 450, 250))], 640, 480, 3.0, {2})
    assert f.any()


def test_identity_panels_with_and_without_a_face_crop():
    f = _frame()
    face = np.full((60, 50, 3), 128, np.uint8)
    hud.draw_hud_panel(f, "Sadik", "WATCHLIST MATCH", True, 0.82, face, panel_index=0, total_panels=2)
    hud.draw_hud_panel(f, "Unknown", "Scanning", False, 0.0, None, panel_index=1, total_panels=2)
    assert f.any()


def test_full_hud_for_a_busy_frame_and_for_an_empty_one():
    ctx = FrameContext(frame=_frame(), camera_id="cam", camera_location="Gate")
    ctx.tracks = [Track(1, (100, 80, 180, 400)), Track(2, (300, 60, 380, 420))]
    ctx.identities = {1: "Sadik", 2: "Unknown"}
    ctx.identity_conf = {1: 0.8}
    ctx.criminal_ids = {1}
    ctx.active_criminals = ["Sadik"]
    ctx.suspicious_tracks = {2: ["loitering"]}
    ctx.weapon_detections = [{"bbox": (150, 200, 180, 240), "score": 0.7, "class_id": 0}]
    ctx.confirmed_weapons = {1: ctx.weapon_detections[0]}
    ctx.weapon_present = True
    ctx.vehicle_detections = [{"bbox": (400, 300, 600, 460), "score": 0.9, "class_id": 2, "class_name": "car"}]
    ctx.fall_tracks = {2: {"bbox": (300, 60, 380, 420)}}
    ctx.threat_score = 85
    for thermal in (False, True):
        out = hud.render_full_hud(ctx.frame.copy(), ctx, time.time() - 30, {"Sadik"},
                                  perf_stats={"cpu": 40, "mem": 55, "fps": 7.5}, thermal_mode=thermal)
        assert out.shape == (480, 640, 3) and out.any()
    empty = FrameContext(frame=_frame())
    assert hud.render_full_hud(empty.frame.copy(), empty, time.time(), set()).shape == (480, 640, 3)
