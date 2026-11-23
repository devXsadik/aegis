"""Compass direction from in-frame movement and camera heading (spec 9.1)."""
import pytest

from core.tracking.direction import compass8, exit_bearing, from_points, side


def path(x0, y0, x1, y1, n=10):
    return [(x0 + (x1 - x0) * i / (n - 1), y0 + (y1 - y0) * i / (n - 1)) for i in range(n)]


def test_spec_example_north_camera_exit_left_is_west():
    d = from_points(path(0.6, 0.5, 0.02, 0.5), heading=0)
    assert (d.direction, d.exit_side, round(d.bearing)) == ("W", "left", 270)


@pytest.mark.parametrize("heading,move,expected", [
    (0, (0.5, 0.9, 0.5, 0.1), "N"),      # away from a north-facing camera
    (0, (0.5, 0.1, 0.5, 0.9), "S"),      # toward it
    (0, (0.1, 0.5, 0.9, 0.5), "E"),
    (90, (0.5, 0.9, 0.5, 0.1), "E"),     # east-facing camera, moving away
    (90, (0.1, 0.5, 0.9, 0.5), "S"),     # east-facing, moving right → south
    (225, (0.5, 0.9, 0.5, 0.1), "SW"),
    (180, (0.9, 0.9, 0.1, 0.1), "SE"),   # south-facing, up-left → 180 + (-45) = 135
])
def test_heading_rotates_image_motion(heading, move, expected):
    assert from_points(path(*move), heading).direction == expected


def test_no_heading_or_no_motion_gives_no_direction():
    assert from_points(path(0.5, 0.5, 0.52, 0.5), heading=0).direction is None
    assert from_points(path(0.1, 0.5, 0.9, 0.5), heading=None).direction is None
    assert from_points([], heading=0).direction is None


def test_jitter_does_not_flip_direction():
    pts = path(0.2, 0.5, 0.8, 0.5, n=20)
    pts[-1] = (0.6, 0.5)                    # one bad last box
    assert from_points(pts, heading=0).direction == "E"


def test_helpers():
    assert side(0.03, 0.5) == "left" and side(0.5, 0.97) == "bottom" and side(0.5, 0.5) is None
    assert exit_bearing(0, "left") == 270 and exit_bearing(350, "right") == 80
    assert compass8(22.4) == "N" and compass8(22.6) == "NE" and compass8(-10) == "N"
