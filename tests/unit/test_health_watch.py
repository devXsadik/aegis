"""HealthWatch: which outages raise an alert, once, and when they clear."""

from datetime import datetime

from backend.services.maintenance import HealthWatch, seconds_until


def test_quiet_start_gets_grace_then_one_camera_offline_alert():
    w = HealthWatch(down_after=120)
    on = {"gate", "lobby"}
    assert w.step(on, {}, now=1000) == []                         # just switched on: grace period
    seen = {"gate": 1100, "lobby": 1100}
    assert w.step(on, seen, now=1150) == []
    assert w.step(on, {"gate": 1290, "lobby": 1100}, now=1300) == [("CAMERA_OFFLINE", "lobby")]
    assert w.step(on, {"gate": 1320, "lobby": 1100}, now=1330) == []          # once per outage
    assert w.step(on, {"gate": 1350, "lobby": 1349}, now=1360) == [("CAMERA_RESTORED", "lobby")]


def test_everything_silent_is_one_system_alert_not_one_per_camera():
    w = HealthWatch(down_after=120)
    on = {"gate", "lobby"}
    w.step(on, {"gate": 0, "lobby": 0}, now=10)
    assert w.step(on, {"gate": 10, "lobby": 10}, now=200) == [("DETECTION_DOWN", None)]
    assert w.step(on, {"gate": 10, "lobby": 10}, now=260) == []
    assert w.step(on, {"gate": 300, "lobby": 300}, now=301) == [("DETECTION_RESTORED", None)]


def test_paused_or_stopped_cameras_never_count():
    w = HealthWatch(down_after=120)
    assert w.step(set(), {}, now=10_000) == []                    # nothing switched on: nothing to watch
    w.step({"gate"}, {"gate": 0}, now=10)
    assert w.step({"gate"}, {"gate": 0}, now=500) == [("DETECTION_DOWN", None)]
    assert w.step(set(), {"gate": 0}, now=510) == [("DETECTION_RESTORED", None)]   # stopped on purpose


def test_next_maintenance_time():
    assert seconds_until(3, datetime(2026, 11, 23, 2, 0)) == 3600
    assert seconds_until(3, datetime(2026, 11, 23, 3, 0)) == 24 * 3600


def test_after_a_system_outage_a_camera_still_silent_gets_its_own_alert():
    w = HealthWatch(down_after=120)
    on = {"gate", "lobby"}
    w.step(on, {"gate": 0, "lobby": 0}, now=10)
    w.step(on, {"gate": 10, "lobby": 10}, now=200)                      # DETECTION_DOWN
    assert w.step(on, {"gate": 300, "lobby": 10}, now=301) == [("DETECTION_RESTORED", None), ("CAMERA_OFFLINE", "lobby")]
