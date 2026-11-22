from unittest.mock import MagicMock

from core.analysis.anomaly_detector import AnomalyDetector
from core.analysis.zones import crossed, point_in_polygon

SHAPE = (480, 640, 3)


def track(tid, cx, foot_y):
    t = MagicMock()
    t.track_id = tid
    t.is_confirmed.return_value = True
    t.to_ltrb.return_value = (cx - 20, foot_y - 80, cx + 20, foot_y)
    return t


def test_point_in_polygon():
    sq = [(0.2, 0.2), (0.6, 0.2), (0.6, 0.6), (0.2, 0.6)]
    assert point_in_polygon(0.4, 0.4, sq)
    assert not point_in_polygon(0.8, 0.4, sq)


def test_line_cross_direction_and_segment_bounds():
    a, b = (0.5, 0.0), (0.5, 1.0)
    assert crossed((0.4, 0.5), (0.6, 0.5), a, b) == -crossed((0.6, 0.5), (0.4, 0.5), a, b) != 0
    assert crossed((0.4, 0.5), (0.45, 0.5), a, b) == 0
    assert crossed((0.4, 1.5), (0.6, 1.5), a, b) == 0     # beyond the finite segment


def test_restricted_zone_intrusion_reported_once_per_entry():
    zones = [{"name": "door", "type": "restricted",
              "polygon": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.9], [0.1, 0.9]]}]
    d = AnomalyDetector(zones=zones)
    inside = track(1, 200, 300)
    first = d.update([inside], SHAPE, now=0)
    assert [a["type"] for a in first] == ["intrusion"]
    assert d.update([inside], SHAPE, now=1) == []
    d.update([], SHAPE, now=2)                           # leaves → state reset
    assert [a["type"] for a in d.update([inside], SHAPE, now=3)] == ["intrusion"]


def test_dwell_fires_once_and_resets_after_leaving():
    d = AnomalyDetector(dwell_seconds=10)
    t = track(1, 100, 100)
    assert d.update([t], SHAPE, now=0) == []
    assert [a["type"] for a in d.update([t], SHAPE, now=11)] == ["dwell"]
    assert d.update([t], SHAPE, now=12) == []             # no per-frame repeats
    d.update([], SHAPE, now=13)
    assert d.update([t], SHAPE, now=14) == []             # timer restarted


def test_line_crossing_event():
    d = AnomalyDetector(lines=[{"name": "gate", "p1": [0.5, 0], "p2": [0.5, 1]}])
    d.update([track(1, 280, 200)], SHAPE, now=0)
    ev = d.update([track(1, 360, 200)], SHAPE, now=1)
    assert [a["type"] for a in ev] == ["line_cross"]


# --- Active hours and occupancy limits --------------------------------------------------------
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from core.analysis.zones import schedule_active, validate_geometry  # noqa: E402

NIGHTS = {"days": [0, 1, 2, 3, 4], "start": "19:00", "end": "07:00"}      # Mon-Fri nights
SQUARE = [[0, 0], [1, 0], [1, 1], [0, 1]]


def at(day, hhmm):          # 2026-11-23 is a Monday
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 11, 23 + day, h, m)


@pytest.mark.parametrize("when, armed", [
    (at(0, "18:59"), False), (at(0, "19:00"), True), (at(0, "23:30"), True),
    (at(1, "06:59"), True),                       # Monday's night runs into Tuesday morning
    (at(1, "07:00"), False), (at(4, "22:00"), True),
    (at(5, "03:00"), True),                       # Friday night into Saturday
    (at(5, "22:00"), False), (at(6, "03:00"), False),   # weekend nights are not armed
])
def test_overnight_schedule(when, armed):
    assert schedule_active(NIGHTS, when) is armed


def test_day_schedule_and_no_schedule():
    office = {"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"}
    assert schedule_active(office, at(2, "12:00")) and not schedule_active(office, at(2, "17:00"))
    assert not schedule_active(office, at(6, "12:00"))
    assert schedule_active(None, at(6, "03:00"))


def _ts(day, hhmm):
    return at(day, hhmm).timestamp()


def test_disarmed_zone_counts_people_but_raises_nothing():
    det = AnomalyDetector(zones=[{"name": "vault", "type": "restricted", "polygon": SQUARE, "schedule": NIGHTS}])
    assert det.update([track(1, 100, 100)], (480, 640), now=_ts(2, "12:00")) == []
    assert det.zone_counts["vault"] == 1
    got = det.update([track(1, 100, 100)], (480, 640), now=_ts(2, "20:00"))   # armed: still inside
    assert [a["type"] for a in got] == ["intrusion"]


def test_occupancy_limit_alerts_once_per_crossing():
    det = AnomalyDetector(zones=[{"name": "lobby", "type": "monitor", "polygon": SQUARE, "max_people": 2}])
    two = [track(i, 100 + i * 50, 100) for i in range(2)]
    three = [track(i, 100 + i * 50, 100) for i in range(3)]
    assert det.update(two, (480, 640), now=1.0) == []
    (a,) = det.update(three, (480, 640), now=2.0)
    assert (a["type"], a["count"], a["limit"]) == ("occupancy", 3, 2)
    assert det.update(three, (480, 640), now=3.0) == []          # still over: no repeat
    det.update(two, (480, 640), now=4.0)
    assert [x["type"] for x in det.update(three, (480, 640), now=5.0)] == ["occupancy"]


def test_validation_of_schedule_and_limit():
    ok = validate_geometry([{"name": "door", "polygon": SQUARE, "schedule": {**NIGHTS, "days": [4, 0, 0]},
                             "max_people": "8"}], [])
    assert ok["zones"][0]["schedule"]["days"] == [0, 4] and ok["zones"][0]["max_people"] == 8
    for bad, msg in [({"schedule": {"days": [], "start": "19:00", "end": "07:00"}}, "pick at least one day"),
                     ({"schedule": {"days": [1], "start": "7pm", "end": "07:00"}}, "times like"),
                     ({"schedule": {"days": [1], "start": "07:00", "end": "07:00"}}, "same time"),
                     ({"max_people": 0.5}, "between 1 and 500"), ({"max_people": "many"}, "whole number")]:
        with pytest.raises(ValueError, match=msg):
            validate_geometry([{"name": "door", "polygon": SQUARE, **bad}], [])
