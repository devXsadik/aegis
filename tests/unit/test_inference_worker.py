"""InferenceWorker: latest-frame-wins, never blocks the caller, survives bad frames."""
import time

import numpy as np

from core.runtime.camera_worker import InferenceWorker


class SlowPipeline:
    def __init__(self, delay=0.0, fail_on=()):
        self.delay, self.fail_on, self.seen = delay, set(fail_on), []

    def run(self, frame, **_):
        n = int(frame[0, 0, 0])
        self.seen.append(n)
        time.sleep(self.delay)
        if n in self.fail_on:
            raise RuntimeError("stage blew up")
        return type("Ctx", (), {"marker": n})()


class NoSync:
    def maybe_sync(self):
        pass


def _frame(n):
    return np.full((2, 2, 3), n, np.uint8)


def _wait(cond, timeout=3):
    end = time.time() + timeout
    while time.time() < end and not cond():
        time.sleep(0.01)
    return cond()


def test_submit_never_blocks_and_latest_frame_wins():
    pipe = SlowPipeline(delay=0.3)
    w = InferenceWorker(pipe, NoSync(), {}, "cam")
    w.start()
    t0 = time.time()
    for n in range(1, 30):          # a 30-frame burst while inference is slow
        w.submit(_frame(n))
    assert time.time() - t0 < 0.2   # caller was never blocked by the 0.3 s inference
    assert _wait(lambda: w.latest()[0] is not None and w.latest()[0].marker == 29, 5)
    assert len(pipe.seen) < 10      # stale frames were dropped, not queued
    w.stop(); w.join(timeout=2)
    assert not w.is_alive()


def test_bad_frame_is_skipped_but_repeated_failures_mark_worker_failed():
    pipe = SlowPipeline(fail_on={1})
    w = InferenceWorker(pipe, NoSync(), {}, "cam", max_consecutive_errors=3)
    w.start()
    w.submit(_frame(1))
    assert _wait(lambda: len(pipe.seen) == 1)
    w.submit(_frame(2))             # a good frame after one failure: worker carries on
    assert _wait(lambda: w.latest()[0] is not None)
    assert not w.failed

    bad = SlowPipeline(fail_on={7})
    w2 = InferenceWorker(bad, NoSync(), {}, "cam", max_consecutive_errors=3)
    w2.start()
    for _ in range(6):
        w2.submit(_frame(7))
        time.sleep(0.05)
    assert _wait(lambda: w2.failed)
    w.stop(); w.join(timeout=2)


def test_a_hung_inference_shows_as_stalled_and_ages_the_result():
    import threading
    gate = threading.Event()

    class Hung:
        def run(self, frame, **_):
            gate.wait(5)                # a model or face worker that stopped answering
            return object()

    w = InferenceWorker(Hung(), NoSync(), {}, "cam")
    w.start()
    assert w.stalled_for() == 0.0
    w.submit(_frame(1))
    assert _wait(lambda: w.stalled_for() > 0.2)
    assert w.result_age() > 0.2
    gate.set()                                       # it answers again
    assert _wait(lambda: w.stalled_for() == 0.0 and w.result_age() < 0.2)
    w.stop()


def test_camera_loop_stops_and_asks_for_restart_when_inference_hangs(monkeypatch):
    import threading
    import core.runtime.camera_worker as cw

    monkeypatch.setenv("INFERENCE_STALL_SECONDS", "0.3")
    monkeypatch.setenv("DVR_ENABLED", "false")
    gate = threading.Event()

    class Hung:
        stages = []

        def run(self, frame, **_):
            gate.wait(5)
            return object()

    class Cap:
        def release(self):
            pass

    monkeypatch.setattr(cw, "open_capture", lambda src: Cap())
    monkeypatch.setattr(cw, "read_frame_with_reconnect", lambda cap, src: (time.sleep(0.02) or cap, _frame(1)))
    monkeypatch.setattr(cw, "RuntimeConfigSync", lambda *a, **k: NoSync())
    for name in ("publish_frame", "publish_heartbeat", "publish_event_clip"):
        monkeypatch.setattr(cw, name, lambda *a, **k: None)

    stalled = threading.Event()
    t = threading.Thread(target=cw.run_camera_loop, kwargs=dict(
        pipeline=Hung(), criminal_names=set(), source=0, camera_id="cam", camera_location="Lab",
        show_window=False, on_stall=stalled.set))
    t.start()
    assert stalled.wait(5)
    gate.set()
    t.join(5)
    assert not t.is_alive()


def test_camera_loop_turns_a_tamper_finding_into_an_alert(monkeypatch):
    import threading
    import core.runtime.camera_worker as cw

    monkeypatch.setenv("DVR_ENABLED", "false")

    class Cap:
        def release(self):
            pass

    stop = threading.Event()
    sent = []
    monkeypatch.setattr(cw, "open_capture", lambda src: Cap())
    monkeypatch.setattr(cw, "read_frame_with_reconnect", lambda cap, src: (time.sleep(0.01) or cap, _frame(1)))
    monkeypatch.setattr(cw, "RuntimeConfigSync", lambda *a, **k: NoSync())
    for name in ("publish_frame", "publish_heartbeat", "publish_event_clip"):
        monkeypatch.setattr(cw, name, lambda *a, **k: None)
    monkeypatch.setattr(cw, "dispatch_alert", lambda **kw: (sent.append(kw), stop.set()))

    class Tamper:
        calls = 0

        def check(self, frame, now, people):
            Tamper.calls += 1
            return "covered" if Tamper.calls == 3 else None

    class Pipe:
        stages = []

        def run(self, frame, **_):
            return type("Ctx", (), {"human_detections": [], "live_flags": [], "threat_score": 0, "frame_number": 0})()

    t = threading.Thread(target=cw.run_camera_loop, kwargs=dict(
        pipeline=Pipe(), criminal_names=set(), source=0, camera_id="cam", camera_location="Lab",
        camera_name="Lab cam", show_window=False, stop_event=stop, tamper=Tamper()))
    t.start()
    t.join(5)
    assert not t.is_alive()
    (alert,) = sent
    assert alert["alert_type"] == "CAMERA_TAMPER" and alert["severity"] == "high"
    assert alert["message"].startswith("Camera view blocked") and alert["message"].endswith("Lab cam")
