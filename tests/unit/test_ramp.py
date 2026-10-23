"""Unit tests for ``Ramp`` (plank): build spec, anchors and validation (FR-008)."""

import json
import math

import pytest

from rube.entities import CLEARANCE, DEFAULTS, ENTITY_TYPES, Ramp, entity_from_dict
from rube.errors import RubeValidationError
from rube.geometry import transform_points
from rube.machine import Machine
from rube.vec import Vec3, mat_vec


def assert_vec(actual, expected, tol=1e-9):
    """Component-wise Vec3 comparison."""
    assert list(actual) == pytest.approx(list(expected), abs=tol)


def slope_ramp(slope_deg=20.0, run=2.0, yaw_deg=0.0, start_xy=(0.0, 0.0), end_z=0.0):
    """A ramp descending ``slope_deg`` over ``run`` m of horizontal distance toward ``yaw_deg``."""
    h = Vec3(math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg)), 0.0)
    start = Vec3(start_xy[0], start_xy[1], end_z + run * math.tan(math.radians(slope_deg)))
    end = Vec3(start.x + h.x * run, start.y + h.y * run, end_z)
    return Ramp(start, end)


def codes(entity):
    """Set of issue codes reported by ``entity.validate()``."""
    return {i.code for i in entity.validate()}


# --- FR-008 defaults and build spec --------------------------------------------------------


def test_ramp_defaults_row():
    """FR-008 / FR-004: Ramp defaults are passive, friction 0.3, bounciness 0, margin 0.001."""
    row = DEFAULTS["Ramp"]
    assert (row.dynamic, row.friction, row.bounciness, row.margin) == (False, 0.3, 0.0, 0.001)
    ramp = Ramp((0, 0, 1), (2, 0, 0))
    assert (ramp.width, ramp.thickness, ramp.rails) == (0.4, 0.05, False)
    body = ramp.body()
    assert body.dynamic is False
    assert body.collision_shape == "BOX"
    assert body.margin == 0.001
    assert (body.use_deactivation, body.start_deactivated) == (False, False)
    assert ENTITY_TYPES["Ramp"] is Ramp


@pytest.mark.parametrize("yaw", [0.0, 37.0, 90.0, -135.0])
def test_ramp_top_surface_centerline_is_start_to_end(yaw):
    """FR-008: start/end are the top-surface centerline endpoints of a width x thickness plank."""
    ramp = slope_ramp(20.0, 2.0, yaw, start_xy=(1.0, -2.0))
    body = ramp.body()
    lx, ly, lz = (b - a for a, b in zip(*body.mesh.bounds(), strict=True))
    length = (ramp.end - ramp.start).length()
    assert (lx, ly, lz) == pytest.approx((length, 0.4, 0.05))
    # The top face (local +Z) centerline maps onto start and end.
    assert_vec(body.location + mat_vec(body.rotation, Vec3(-lx / 2, 0, lz / 2)), ramp.start)
    assert_vec(body.location + mat_vec(body.rotation, Vec3(lx / 2, 0, lz / 2)), ramp.end)
    # Local +Z is the upward surface normal, local +X points downhill.
    normal = mat_vec(body.rotation, Vec3(0, 0, 1))
    assert normal.z > 0
    assert normal.dot(ramp.direction) == pytest.approx(0.0, abs=1e-12)
    assert_vec(mat_vec(body.rotation, Vec3(1, 0, 0)), ramp.direction)
    # The plank is level across its width (local Y horizontal).
    assert mat_vec(body.rotation, Vec3(0, 1, 0)).z == pytest.approx(0.0, abs=1e-12)
    # All world vertices lie on or below the top surface plane.
    for v in transform_points(body.mesh.vertices, body.rotation, body.location):
        assert (v - ramp.start).dot(normal) <= 1e-9


# --- FR-008 anchors ------------------------------------------------------------------------


def test_ramp_anchors_top_bottom_direction_slope():
    """FR-008: .top = start, .bottom = end, .direction unit downhill, .slope_deg."""
    ramp = slope_ramp(20.0, 2.0, 90.0)
    assert_vec(ramp.top, ramp.start)
    assert_vec(ramp.bottom, ramp.end)
    assert ramp.direction.length() == pytest.approx(1.0)
    assert ramp.direction.z < 0
    assert ramp.direction.y > 0 and ramp.direction.x == pytest.approx(0.0, abs=1e-12)
    assert ramp.slope_deg == pytest.approx(20.0)
    assert slope_ramp(35.0, 1.0).slope_deg == pytest.approx(35.0)


@pytest.mark.parametrize(("slope", "yaw", "r"), [(20.0, 0.0, 0.1), (30.0, 120.0, 0.05)])
def test_ball_spawn_rests_just_above_surface_near_top(slope, yaw, r):
    """FR-008: ball_spawn(r) = center 1.5 r in from the top edge, r + CLEARANCE off the surface."""
    ramp = slope_ramp(slope, 2.0, yaw)
    p = ramp.ball_spawn(r)
    normal = mat_vec(ramp.body().rotation, Vec3(0, 0, 1))
    rel = p - ramp.start
    assert rel.dot(normal) == pytest.approx(r + CLEARANCE)
    assert rel.dot(ramp.direction) == pytest.approx(1.5 * r)
    side = normal.cross(ramp.direction)
    assert rel.dot(side) == pytest.approx(0.0, abs=1e-12)


def test_exit_is_ground_level_beyond_bottom_end():
    """FR-008: exit(distance) = ground point (z = 0) `distance` m past the end, horizontally."""
    ramp = slope_ramp(20.0, 2.0, 90.0, start_xy=(1.0, 0.0), end_z=0.0)
    assert_vec(ramp.exit(), (1.0, 2.0, 0.0))
    assert_vec(ramp.exit(0.5), (1.0, 2.5, 0.0))
    raised = Ramp((0, 0, 1.5), (1, 0, 0.5))
    assert_vec(raised.exit(1.0), (2.0, 0.0, 0.0))


# --- FR-008 validation ---------------------------------------------------------------------


def test_ramp_start_must_be_higher_than_end():
    """FR-008: start.z <= end.z -> INVALID_ARGUMENT with a hint to swap them."""
    for start, end in [((0, 0, 0), (2, 0, 1)), ((0, 0, 1), (2, 0, 1))]:
        issues = [i for i in Ramp(start, end).validate() if i.code == "INVALID_ARGUMENT"]
        assert len(issues) == 1
        assert "swap" in issues[0].hint


@pytest.mark.parametrize(
    ("kwargs", "code", "needle"),
    [
        ({"start": (0, 0, 1), "end": (0, 0, 0)}, "INVALID_ARGUMENT", "horizontal"),
        ({"start": (0, 0), "end": (1, 0, 0)}, "INVALID_ARGUMENT", "(0, 0)"),
        ({"start": (0, 0, 1), "end": (2, 0, 0), "width": 0.01}, "TOO_SMALL", "0.01"),
        ({"start": (0, 0, 1), "end": (2, 0, 0), "thickness": 0}, "OUT_OF_RANGE", "0"),
        ({"start": (0, 0, 1), "end": (2, 0, 0), "rails": "yes"}, "INVALID_ARGUMENT", "rails"),
        ({"start": (0, 0, 1), "end": (2, 0, 0), "friction": 2}, "OUT_OF_RANGE", "2"),
    ],
)
def test_ramp_validation_codes(kwargs, code, needle):
    """FR-008 / FR-013: bad ramp arguments are reported with their actual values."""
    issues = [i for i in Ramp(**kwargs).validate() if i.code == code]
    assert issues, Ramp(**kwargs).validate()
    assert any(needle in i.message for i in issues)


def test_ramp_anchors_raise_on_invalid_geometry():
    """FR-008 / D-15: anchors need valid geometry and raise RubeValidationError otherwise."""
    with pytest.raises(RubeValidationError):
        _ = Ramp((0, 0, 0), (1, 0, 1)).direction
    with pytest.raises(RubeValidationError):
        Ramp((0, 0, 1), (1, 0, 0)).ball_spawn(-0.1)


def test_ramp_dict_roundtrip_and_machine():
    """FR-015 / FR-001: a ramp serializes, round-trips, and validates cleanly in a machine."""
    ramp = Ramp((0, 0, 0.8), (2, 0, 0), width=0.5, name="R", color="green")
    d = ramp.to_dict()
    json.dumps(d)
    assert entity_from_dict(d).to_dict() == d
    m = Machine(duration=3)
    m.add(ramp)
    assert m.validate() == []
    assert Machine.from_dict(m.to_dict()).to_dict() == m.to_dict()
