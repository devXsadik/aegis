from core.analysis.weapon_confirm import UNASSIGNED, WeaponConfirmer, associate


class T:
    def __init__(self, tid, box):
        self.track_id, self._b = tid, box

    def is_confirmed(self):
        return True

    def to_ltrb(self):
        return self._b


def det(box, score=0.6):
    return {"bbox": box, "score": score, "class_id": 0}


def test_weapon_assigned_only_to_overlapping_person():
    tracks = [T(1, (0, 0, 100, 200)), T(2, (300, 0, 400, 200))]
    got = associate([det((10, 80, 40, 110))], tracks)
    assert list(got) == [1]


def test_unmatched_weapon_goes_to_unassigned():
    got = associate([det((500, 500, 520, 520))], [T(1, (0, 0, 100, 200))])
    assert list(got) == [UNASSIGNED]


def test_single_frame_never_confirms():
    c = WeaponConfirmer(window=5, min_hits=3)
    assert c.update({1: det((0, 0, 1, 1))}) == set()


def test_confirms_after_min_hits_and_decays():
    c = WeaponConfirmer(window=5, min_hits=3)
    hit = {1: det((0, 0, 1, 1))}
    assert c.update(hit) == set()
    assert c.update({}) == set()
    assert c.update(hit) == set()
    assert c.update(hit) == {1}
    for _ in range(5):
        c.update({})
    assert c.update(hit) == set()


# --- WeaponScreen: size and in-hand checks before confirmation -------------------------------
from core.analysis.weapon_confirm import WeaponScreen, held_in_hand  # noqa: E402

PERSON = (0, 0, 100, 200)          # 200 px tall: reach 0.25 → a wrist within 50 px counts


def pose(**wrists):
    return {"kpts": {name: (x, y, 0.9) for name, (x, y) in wrists.items()}}


def test_held_when_a_wrist_is_on_the_weapon():
    assert held_in_hand((40, 90, 70, 110), PERSON, pose(right_wrist=(50, 100))["kpts"]) is True


def test_not_held_when_wrists_visible_but_far():
    assert held_in_hand((40, 20, 70, 40), PERSON, pose(left_wrist=(20, 190), right_wrist=(80, 190))["kpts"]) is False


def test_unknown_without_visible_wrists():
    assert held_in_hand((40, 90, 70, 110), PERSON, None) is None
    assert held_in_hand((40, 90, 70, 110), PERSON, {"nose": (50, 10, 0.9)}) is None


def test_tiny_boxes_are_dropped():
    s = WeaponScreen(min_side_px=14)
    assert not s.big_enough(det((0, 0, 30, 10)))
    assert s.big_enough(det((0, 0, 30, 20)))


def test_screen_keeps_held_and_unknown_hits_and_marks_them():
    s = WeaponScreen(unheld_min_score=0.65)
    tracks = [T(1, PERSON), T(2, (300, 0, 400, 200))]
    got = s.screen({1: det((40, 90, 70, 110), 0.45), 2: det((340, 90, 370, 110), 0.45)}, tracks,
                   {1: pose(right_wrist=(50, 100))})
    assert got[1]["held"] is True and got[2]["held"] is None


def test_screen_needs_higher_score_when_not_in_hand_or_unassigned():
    s = WeaponScreen(unheld_min_score=0.65)
    tracks = [T(1, PERSON)]
    far = pose(left_wrist=(20, 190), right_wrist=(80, 190))
    assert s.screen({1: det((40, 20, 70, 40), 0.5)}, tracks, {1: far}) == {}
    assert s.screen({1: det((40, 20, 70, 40), 0.8)}, tracks, {1: far})[1]["held"] is False
    assert s.screen({UNASSIGNED: det((500, 500, 540, 540), 0.5)}, tracks) == {}
    assert UNASSIGNED in s.screen({UNASSIGNED: det((500, 500, 540, 540), 0.7)}, tracks)


def test_weak_unheld_hits_never_confirm_but_held_ones_do():
    s, c = WeaponScreen(), WeaponConfirmer(window=5, min_hits=3)
    tracks = [T(1, PERSON)]
    far = {1: pose(left_wrist=(20, 190), right_wrist=(80, 190))}
    for _ in range(5):
        assert c.update(s.screen({1: det((40, 20, 70, 40), 0.5)}, tracks, far)) == set()
    near = {1: pose(right_wrist=(50, 30))}
    hits = [c.update(s.screen({1: det((40, 20, 70, 40), 0.5)}, tracks, near)) for _ in range(3)]
    assert hits[-1] == {1}
