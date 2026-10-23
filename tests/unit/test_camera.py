"""Unit tests for ``rube.camera`` (FR-014: static/follow cameras, auto-framing)."""

import math

import pytest

from rube.camera import RESOLUTION, SENSOR_WIDTH_MM, Camera, auto_frame, look_rotation
from rube.entities import Ball
from rube.machine import Machine
from rube.vec import Vec3, mat_transpose, mat_vec


def corners(box):
    """The 8 corners of an AABB."""
    lo, hi = box
    return [Vec3(x, y, z) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]


def assert_in_frame(cam: Camera, points):
    """Project points through a pinhole camera (Blender sensor fit AUTO, landscape)."""
    rot = look_rotation(cam.position, cam.look_at)
    tan_h = (SENSOR_WIDTH_MM / 2) / cam.lens_mm
    tan_v = tan_h * RESOLUTION[1] / RESOLUTION[0]
    for p in points:
        x, y, z = mat_vec(mat_transpose(rot), p - cam.position)
        assert z < 0, "point behind the camera"
        assert abs(x) / -z <= tan_h and abs(y) / -z <= tan_v, f"{p} outside frame"


def test_static_and_follow_constructors():
    """FR-014: Camera.static(position, look_at, lens_mm=35); Camera.follow(target, offset, lens)."""
    s = Camera.static((5, -5, 3), (0, 0, 0.5))
    assert (s.mode, s.position, s.look_at, s.lens_mm) == (
        "static",
        Vec3(5, -5, 3),
        Vec3(0, 0, 0.5),
        35,
    )
    ball = Ball((0, 0, 1))
    f = Camera.follow(ball)
    assert (f.mode, f.target, f.offset, f.lens_mm) == ("follow", ball, Vec3(-3, -3, 2), 35)
    assert s.validate() == [] and f.validate() == []


def test_look_rotation_blender_camera_axes():
    """FR-014: camera local -Z points at the target, local Y is up-ish, local X horizontal."""
    rot = look_rotation(Vec3(0, -5, 0), Vec3(0, 0, 0))
    forward = -mat_vec(rot, Vec3(0, 0, 1))
    assert list(forward) == pytest.approx([0, 1, 0])
    assert list(mat_vec(rot, Vec3(0, 1, 0))) == pytest.approx([0, 0, 1])
    assert list(mat_vec(rot, Vec3(1, 0, 0))) == pytest.approx([1, 0, 0])
    # Straight down still yields a valid orthonormal frame.
    down = look_rotation(Vec3(0, 0, 5), Vec3(0, 0, 0))
    assert list(-mat_vec(down, Vec3(0, 0, 1))) == pytest.approx([0, 0, -1])


@pytest.mark.parametrize(
    "box",
    [
        (Vec3(-1, -1, 0), Vec3(1, 1, 1)),
        (Vec3(-6, -0.2, 0), Vec3(6, 0.2, 0.8)),  # long domino row
        (Vec3(2, 3, 0), Vec3(2.2, 3.2, 4)),  # tall thin tower off-center
        (Vec3(0, 0, 0), Vec3(0.1, 0.1, 0.1)),  # tiny -> min radius 1 m
    ],
)
def test_auto_frame_contains_bbox(box):
    """FR-014: auto camera is a 3/4 elevated static view with the whole box in frame."""
    cam = auto_frame([box])
    assert cam.mode == "static"
    center = (box[0] + box[1]) / 2
    assert list(cam.look_at) == pytest.approx(list(center))
    d = cam.position - center
    assert d.x < 0 and d.y < 0 and d.z > 0  # from (-1, -1, +0.7) direction
    assert math.degrees(math.atan2(d.z, math.hypot(d.x, d.y))) == pytest.approx(
        math.degrees(math.atan2(0.7, math.sqrt(2)))
    )
    assert_in_frame(cam, corners(box))


def test_auto_frame_union_of_boxes_and_empty():
    """FR-014: several boxes are framed together; no boxes -> frame around the origin."""
    boxes = [(Vec3(-3, 0, 0), Vec3(-2, 1, 1)), (Vec3(4, -2, 0), Vec3(5, -1, 2))]
    cam = auto_frame(boxes)
    assert_in_frame(cam, [c for b in boxes for c in corners(b)])
    assert auto_frame([]).validate() == []


@pytest.mark.parametrize(
    ("cam", "code"),
    [
        (Camera.static((0, 0, 0), (0, 0, 0)), "INVALID_ARGUMENT"),
        (Camera.static((0, 0), (1, 0, 0)), "INVALID_ARGUMENT"),
        (Camera.static((5, 0, 0), (0, 0, 0), lens_mm=1), "OUT_OF_RANGE"),
        (Camera.follow("ball"), "INVALID_ARGUMENT"),
        (Camera.follow(Ball((0, 0, 1)), offset=(0, 0, 0)), "INVALID_ARGUMENT"),
    ],
)
def test_camera_validation(cam, code):
    """FR-014 / FR-013: camera argument problems are issues with entity 'camera'."""
    issues = cam.validate()
    assert code in {i.code for i in issues}
    assert all(i.entity == "camera" and i.hint for i in issues)


def test_machine_camera_follow_target_must_be_registered():
    """FR-014: following an entity that is not in the machine -> INVALID_ARGUMENT."""
    m = Machine()
    m.set_camera(Camera.follow(Ball((0, 0, 1))))
    assert {i.code for i in m.validate()} == {"INVALID_ARGUMENT"}
    with pytest.raises(TypeError):
        m.set_camera("top view")
