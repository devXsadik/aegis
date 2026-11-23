"""Geometry helpers and the incident status machine."""
import pytest

from backend.services import geo
from backend.services import incident_status as fsm

SQUARE = {"type": "Polygon", "coordinates": [[[90.40, 23.78], [90.42, 23.78], [90.42, 23.80], [90.40, 23.80], [90.40, 23.78]]]}
WITH_HOLE = {"type": "Polygon", "coordinates": [
    SQUARE["coordinates"][0],
    [[90.405, 23.785], [90.415, 23.785], [90.415, 23.795], [90.405, 23.795], [90.405, 23.785]],
]}


def test_point_in_polygon_and_hole():
    assert geo.contains(SQUARE, 23.79, 90.41)
    assert not geo.contains(SQUARE, 23.81, 90.41)
    assert not geo.contains(WITH_HOLE, 23.79, 90.41)        # inside the hole
    assert geo.contains(WITH_HOLE, 23.781, 90.401)
    multi = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]}
    assert geo.contains(multi, 23.79, 90.41)
    assert geo.contains({"type": "Feature", "geometry": SQUARE}, 23.79, 90.41)
    assert not geo.contains(None, 23.79, 90.41) and not geo.contains("not json", 1, 1)


def test_distance_bearing_compass():
    # ~1.11 km per 0.01° latitude
    assert 1100 < geo.haversine_m(23.78, 90.41, 23.79, 90.41) < 1125
    assert geo.compass8(geo.bearing_deg(23.78, 90.41, 23.79, 90.41)) == "N"
    assert geo.compass8(geo.bearing_deg(23.78, 90.41, 23.78, 90.42)) == "E"
    assert geo.compass8(geo.bearing_deg(23.79, 90.42, 23.78, 90.41)) == "SW"
    assert geo.compass8(359) == "N" and geo.compass8(337.6) == "N" and geo.compass8(337.4) == "NW"
    assert geo.angle_diff(350, 10) == 20 and geo.angle_diff(90, 270) == 180


def test_centroid_and_validation():
    lat, lng = geo.centroid(SQUARE)
    assert abs(lat - 23.79) < 1e-9 and abs(lng - 90.41) < 1e-9
    assert geo.valid_polygon(SQUARE)
    assert not geo.valid_polygon({"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]})
    assert not geo.valid_polygon({"type": "Point", "coordinates": [90, 23]})
    assert not geo.valid_polygon({"type": "Polygon", "coordinates": [[[200, 0], [1, 1], [1, 0], [200, 0]]]})


@pytest.mark.parametrize("cur,target", [("new", "acknowledged"), ("acknowledged", "verified_match"),
                                        ("verified_match", "officer_dispatched"), ("officer_dispatched", "target_located"),
                                        ("target_located", "resolved"), ("open", "in_progress")])
def test_allowed_transitions(cur, target):
    fsm.check(cur, target, role="operator", note=None)


def test_rules():
    with pytest.raises(fsm.TransitionError) as e:
        fsm.check("new", "resolved", role="admin", note="x")
    assert e.value.code == 409
    with pytest.raises(fsm.TransitionError) as e:
        fsm.check("new", "false_alarm", role="operator", note="  ")
    assert e.value.code == 400
    fsm.check("new", "false_alarm", role="operator", note="Lookalike, checked ID")
    with pytest.raises(fsm.TransitionError) as e:
        fsm.check("closed", "in_progress", role="operator", note="reopen")
    assert e.value.code == 403
    fsm.check("closed", "in_progress", role="supervisor", note="reopen")
    with pytest.raises(fsm.TransitionError):
        fsm.check("new", "bogus", role="admin", note=None)
    fsm.check("investigating", "in_progress", role="operator", note=None)   # legacy = same status


def test_spec_is_consistent():
    spec = fsm.spec()
    ids = {s["id"] for s in spec["statuses"]}
    assert set(spec["transitions"]) == ids
    assert all(set(t) <= ids for t in spec["transitions"].values())
    assert set(spec["note_required"]) <= ids
