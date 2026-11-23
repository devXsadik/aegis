"""PTZ follow: steering maths, subject choice, rate limit, stop / home, and follow-off back-off."""
import numpy as np

from core.analysis.ptz_follow import PtzFollower, follow_command

FRAME = (1000, 1000, 3)


def test_follow_command():
    assert follow_command((450, 300, 550, 700), FRAME) == (0.0, 0.0, 0.0)          # centred, good size
    pan, tilt, _ = follow_command((850, 400, 950, 600), FRAME)
    assert pan > 0 and tilt == 0                                                     # right of centre → pan right
    _, tilt, _ = follow_command((450, 0, 550, 150), FRAME)
    assert tilt > 0                                                                  # above centre → tilt up
    assert follow_command((480, 450, 520, 550), FRAME)[2] > 0                        # small → zoom in
    assert follow_command((300, 50, 700, 950), FRAME)[2] < 0                         # huge → zoom out


class T:
    def __init__(self, tid, box):
        self.track_id, self._b = tid, box

    def is_confirmed(self):
        return True

    def to_ltrb(self):
        return self._b


class Ctx:
    def __init__(self, tracks, weapons=(), criminals=()):
        self.frame = np.zeros(FRAME, np.uint8)
        self.tracks = tracks
        self.confirmed_weapons = {t: {} for t in weapons}
        self.criminal_ids = set(criminals)
        self.tracked = {}


def test_follower_picks_armed_subject_rate_limits_and_homes():
    sent = []
    f = PtzFollower("ptz1", rate_hz=2, lost_seconds=3, home_seconds=10, send=lambda cam, cmd, off: sent.append(cmd))
    ctx = Ctx([T(1, (100, 400, 200, 600)), T(2, (800, 400, 900, 600))], weapons=[2], criminals=[1])
    assert f.update(ctx, now=0.0)["pan"] > 0                     # the armed one (right side) wins
    assert f.update(ctx, now=0.2) is None                        # rate limit
    assert f.update(ctx, now=0.6)["action"] == "move"
    centred = Ctx([T(2, (450, 300, 550, 700))], weapons=[2])
    assert f.update(centred, now=1.2) == {"action": "stop"}
    empty = Ctx([])
    assert f.update(empty, now=2.0) is None
    assert f.update(empty, now=12.0) == {"action": "home"}
    assert [c["action"] for c in sent] == ["move", "move", "stop", "home"]
    assert f.update(Ctx([T(5, (100, 100, 200, 300))]), now=20.0) is None         # nobody important: nothing


def test_follow_off_backs_off():
    f = PtzFollower("ptz1", send=lambda cam, cmd, off: off())
    ctx = Ctx([T(2, (850, 400, 950, 600))], weapons=[2])
    assert f.update(ctx) is not None
    assert f.update(ctx) is None                                  # told follow is off: quiet for 10 s
