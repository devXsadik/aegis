"""Wrong-way vehicles, unattended bags, crowd surges."""
from core.analysis.scene_events import AbandonedObjectDetector, CrowdSurgeDetector, WrongWayDetector, angle_diff
from core.analysis.zones import parse_zones, validate_geometry

FRAME = (1000, 1000, 3)
ROAD = parse_zones([{"name": "Airport Rd northbound", "type": "one_way", "direction": 270,   # up the picture
                     "polygon": [[0.2, 0], [0.8, 0], [0.8, 1], [0.2, 1]]}])


class T:
    def __init__(self, tid, box):
        self.track_id, self._b = tid, box

    def is_confirmed(self):
        return True

    def to_ltrb(self):
        return self._b


def _drive(det, tid, ys):
    out = []
    for y in ys:
        out += det.update([T(tid, (450, y - 80, 550, y))], FRAME, ROAD)
    return out


def test_angle_diff():
    assert angle_diff(10, 350) == 20 and angle_diff(90, 270) == 180


def test_wrong_way_only_against_the_flow_and_once():
    det = WrongWayDetector()
    assert _drive(det, "ok", range(900, 300, -50)) == []                 # going up: allowed
    hits = _drive(det, "bad", range(200, 900, 50))                       # going down: wrong way
    assert len(hits) == 1 and hits[0]["type"] == "wrong_way" and hits[0]["zone"] == "Airport Rd northbound"
    assert _drive(det, "slow", [500, 502, 504, 506, 508]) == []         # barely moving: no judgement


def test_one_way_zone_needs_direction():
    import pytest
    poly = [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]
    with pytest.raises(ValueError, match="direction"):
        validate_geometry([{"name": "x", "type": "one_way", "polygon": poly}], [])
    zones = validate_geometry([{"name": "x", "type": "one_way", "direction": 450, "polygon": poly}], [])["zones"]
    assert zones[0]["direction"] == 90


def test_bag_left_alone_alerts_once_and_carried_bag_does_not():
    det = AbandonedObjectDetector(still_seconds=20, alone_seconds=10)
    bag = [{"bbox": (500, 800, 540, 850), "class_name": "backpack"}]
    owner = [([480, 500, 560, 850], 0.9, 0)]
    out = []
    for t in range(0, 15):                      # owner stands next to it
        out += det.update(bag, owner, FRAME, t)
    for t in range(15, 40):                     # owner walked away
        out += det.update(bag, [], FRAME, t)
    assert len(out) == 1 and out[0]["object"] == "backpack" and out[0]["type"] == "abandoned_object"
    det2 = AbandonedObjectDetector(still_seconds=20, alone_seconds=10)
    moving = []
    for t in range(0, 60):
        x = 100 + t * 25                       # carried across the picture
        moving += det2.update([{"bbox": (x, 800, x + 40, 850), "class_name": "suitcase"}], [], FRAME, t)
    assert moving == []


def test_crowd_surge():
    det = CrowdSurgeDetector(window_seconds=60, min_people=10, factor=2)
    out = []
    for t, n in [(0, 4), (10, 5), (20, 6), (30, 12), (35, 14)]:
        out += det.update({"gate": n}, t)
    assert len(out) == 1 and out[0]["count"] == 12 and out[0]["from"] == 4
    assert det.update({"gate": 30}, 200) == []                           # steady high: no new surge
