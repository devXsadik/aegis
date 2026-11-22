"""RecognitionStage: a watchlist name needs 2 matching votes, crops, retries and pruning."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from core.pipeline.base import FrameContext
from core.pipeline.stages.recognition import RecognitionStage


class Track:
    def __init__(self, tid, box=(100, 20, 180, 300), coasting=False):
        self.track_id, self._box = tid, box
        self.time_since_update = 1 if coasting else 0

    def is_confirmed(self):
        return True

    def to_ltrb(self):
        return self._box


class FakeRecognizer:
    """Answers with the next name in `answers` (None = no face match)."""
    tolerance = 0.45

    def __init__(self, answers):
        self.answers, self.crops, self.lock = list(answers), [], threading.Lock()

    def recognize_detail(self, roi, source=None):
        with self.lock:
            self.crops.append(roi.shape)
            name = self.answers.pop(0) if self.answers else None
        return {"name": name, "distance": 0.3} if name else None

    def confidence(self, distance, tolerance):
        return round(1 - distance / tolerance, 2)


def _ctx(*tracks, h=480):
    return FrameContext(frame=np.zeros((h, 640, 3), np.uint8), tracks=list(tracks))


def _run(stage, tracks, frames, wait=0.02):
    out = None
    for _ in range(frames):
        out = stage.process(_ctx(*tracks))
        time.sleep(wait)
        stage.executor.shutdown(wait=True)              # let the queued face job finish
        stage.executor = ThreadPoolExecutor(max_workers=2)
    return out


def test_one_match_is_not_enough_two_confirm_the_watchlist_name():
    rec = FakeRecognizer(["Sadik", "Sadik"])
    stage = RecognitionStage(rec, criminal_names={"Sadik"}, retry_base=0.0)
    first = _run(stage, [Track(1)], 1)
    assert first.criminal_ids == set()                  # first vote only
    out = _run(stage, [Track(1)], 2)
    assert out.criminal_ids == {1} and out.active_criminals == ["Sadik"]
    assert out.identities[1] == "Sadik" and out.identity_conf[1] == 0.33


def test_two_different_names_never_confirm():
    stage = RecognitionStage(FakeRecognizer(["Sadik", "Tarik"]), {"Sadik", "Tarik"}, retry_base=0.0)
    out = _run(stage, [Track(1)], 3)
    assert out.criminal_ids == set() and out.identities[1] == "Unknown"


def test_tall_box_searches_only_the_top_and_large_crops_are_shrunk():
    rec = FakeRecognizer([])
    stage = RecognitionStage(rec, set())
    _run(stage, [Track(1, (100, 20, 180, 300))], 1)          # 280 px tall, 80 wide, not cut off
    assert rec.crops[0][0] == int(280 * 0.45)
    rec.crops.clear()
    stage2 = RecognitionStage(rec, set())
    stage2.process(FrameContext(frame=np.zeros((900, 900, 3), np.uint8), tracks=[Track(2, (0, 0, 600, 899))]))
    stage2.executor.shutdown(wait=True)
    assert rec.crops[0][0] == 400                            # cut off at the bottom: whole crop, resized


def test_coasting_tracks_keep_their_name_but_get_no_face_job():
    rec = FakeRecognizer(["Sadik", "Sadik"])
    stage = RecognitionStage(rec, {"Sadik"}, retry_base=0.0)
    _run(stage, [Track(1)], 3)
    calls = len(rec.crops)
    out = _run(stage, [Track(1, coasting=True)], 2)
    assert len(rec.crops) == calls and out.identities[1] == "Sadik"


def test_misses_back_off_and_gone_tracks_are_forgotten():
    rec = FakeRecognizer([])
    stage = RecognitionStage(rec, set(), retry_base=0.5, retry_max=2.0)
    _run(stage, [Track(1)], 3, wait=0)
    assert len(rec.crops) == 1                               # next try waits >= 0.5 s after a miss
    assert stage._next_try[1] - time.monotonic() > 0.5       # backed off (0.5 x 2)
    _run(stage, [], 1, wait=0)
    assert 1 not in stage._id_name_map and 1 not in stage._next_try
