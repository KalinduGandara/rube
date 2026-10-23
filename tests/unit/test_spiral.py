"""Unit tests for ``spiral_ramp`` / ``SpiralRamp`` (FR-010, T-016): helix channel, support
column, anchors (entry, exit, ball_spawn), slope and track validation, serialization."""

import math

import pytest
from test_geometry import assert_closed_oriented

from rube import spiral_ramp
from rube.entities import (
    CLEARANCE,
    DEFAULTS,
    ENTITY_TYPES,
    SPIRAL_SEGMENTS_PER_TURN,
    SpiralTrack,
    SupportColumn,
)
from rube.errors import RubeValidationError
from rube.generators import SpiralRamp
from rube.geometry import mesh_volume_centroid
from rube.machine import Machine
from rube.vec import Vec3


def assert_vec(actual, expected, tol=1e-9):
    """Component-wise Vec3 comparison."""
    assert list(actual) == pytest.approx(list(expected), abs=tol)


def codes(group):
    """Issue codes reported by a group's ``validate()``."""
    return [i.code for i in group.validate()]


def spiral(**kw):
    """A valid 2-turn spiral (slope about 8.5 deg) with overridable arguments."""
    args = {"center": (1, 2, 0), "radius": 0.8, "height": 1.5, "turns": 2}
    args.update(kw)
    return spiral_ramp(args.pop("center"), args.pop("radius"), args.pop("height"),
                       args.pop("turns"), **args)  # fmt: skip


# --- structure ---------------------------------------------------------------------------------


def test_spiral_members_and_defaults():
    """FR-010: a passive MESH track (margin 0.005) plus a passive support column, defaults
    track_width 0.25, wall_height 0.08, thickness 0.03, counter-clockwise."""
    s = spiral()
    assert isinstance(s, SpiralRamp)
    track, column = s.members
    assert isinstance(track, SpiralTrack) and isinstance(column, SupportColumn)
    assert (track.track_width, track.wall_height, track.thickness, track.clockwise) == (
        0.25, 0.08, 0.03, False,
    )  # fmt: skip
    body = track.body()
    assert body.collision_shape == "MESH" and body.margin == 0.005 and body.dynamic is False
    assert DEFAULTS["SpiralTrack"].margin == 0.005
    assert column.body().dynamic is False
    assert ENTITY_TYPES["SpiralTrack"] is SpiralTrack
    assert ENTITY_TYPES["SupportColumn"] is SupportColumn
    assert s.validate() == []


def test_spiral_track_mesh_closed_and_segments():
    """FR-010: >= 48 segments per turn; the channel mesh is a closed solid centered on its
    center of volume."""
    s = spiral(turns=2.5)
    track = s.members[0]
    assert SPIRAL_SEGMENTS_PER_TURN >= 48
    assert track.segments >= 48 * 2.5
    body = track.body()
    assert len(body.mesh.vertices) == 8 * (track.segments + 1)
    assert_closed_oriented(body.mesh)
    vol, centroid = mesh_volume_centroid(body.mesh)
    assert vol > 0
    assert_vec(centroid, (0, 0, 0), tol=1e-9)


def test_support_column_size_and_placement():
    """FR-010: column radius = radius - track_width/2 - 0.01, standing on center up to the
    entry height."""
    s = spiral(radius=0.9, track_width=0.3)
    column = s.members[1]
    assert column.radius == pytest.approx(0.9 - 0.15 - 0.01)
    lo, hi = column.body().aabb()
    assert lo.z == pytest.approx(0.0) and hi.z == pytest.approx(1.5)
    assert (lo.x + hi.x) / 2 == pytest.approx(1.0) and (lo.y + hi.y) / 2 == pytest.approx(2.0)


# --- anchors -----------------------------------------------------------------------------------


def test_entry_and_exit_heights():
    """FR-010: the track descends from center.z + height to center.z + thickness; entry is on
    the +X side of the axis at the helix radius."""
    s = spiral(center=(1, 2, 0.5), turns=2)
    assert_vec(s.entry, (1.8, 2, 2.0))
    assert_vec(s.exit, (1.8, 2, 0.53))  # 2 whole turns end above the entry


@pytest.mark.parametrize("clockwise", [False, True])
def test_exit_angle_follows_turns_and_direction(clockwise):
    """FR-010: exit lies `turns` turns around the axis, counter-clockwise unless clockwise."""
    s = spiral(center=(0, 0, 0), radius=1.0, height=1.0, turns=1.25, clockwise=clockwise)
    sign = -1 if clockwise else 1
    assert_vec(s.exit, (0, sign * 1.0, 0.03))
    # Direction of travel at the entry: +Y counter-clockwise, -Y clockwise.
    tangent, side, up = s.members[0].frame_at(0.0)
    assert tangent.y * sign > 0 and tangent.z < 0
    assert side.z == pytest.approx(0) and up.z > 0


def test_entry_exit_on_mesh_floor():
    """FR-010: entry and exit are the floor's top-surface centerline points of the mesh."""
    s = spiral()
    track = s.members[0]
    body = track.body()
    verts = [Vec3(*v) + body.location for v in body.mesh.vertices]
    first, last = verts[0:8], verts[-8:]
    assert_vec((first[4] + first[5]) / 2, s.entry)
    assert_vec((last[4] + last[5]) / 2, s.exit)


def test_ball_spawn_above_floor_near_entry():
    """FR-010: ball_spawn(r) is 1.5 r along the track from the entry and r + CLEARANCE above
    the floor along its normal, i.e. resting in the groove centerline."""
    s = spiral()
    track = s.members[0]
    r = 0.08
    p = s.ball_spawn(r)
    f = 1.5 * r / track.length
    _, _, up = track.frame_at(f)
    assert_vec(p, track.point_at(f) + up * (r + CLEARANCE))
    assert (p - s.entry).length() == pytest.approx(math.hypot(1.5 * r, r + CLEARANCE), abs=1e-3)


def test_anchors_raise_on_unusable_arguments():
    """FR-013 / D-15: anchors of a spiral with unusable arguments raise RubeValidationError."""
    s = spiral(radius="big")
    assert s.members == []
    with pytest.raises(RubeValidationError):
        _ = s.entry
    with pytest.raises(RubeValidationError):
        s.ball_spawn(0.1)
    with pytest.raises(RubeValidationError):
        spiral().ball_spawn(-1)


# --- validation --------------------------------------------------------------------------------


def test_slope_too_shallow():
    """FR-010: slope = height / (2 pi radius turns) < tan 4 deg -> SLOPE_TOO_SHALLOW with a
    height range hint."""
    s = spiral(radius=1.0, height=0.5, turns=2)  # slope 0.04 ~ 2.3 deg
    issues = s.validate()
    assert [i.code for i in issues] == ["SLOPE_TOO_SHALLOW"]
    lo = math.tan(math.radians(4)) * 2 * math.pi * 1.0 * 2
    assert f"{lo:.2f}" in issues[0].hint


def test_slope_too_steep():
    """FR-010: slope > tan 25 deg -> SLOPE_TOO_STEEP."""
    s = spiral(radius=0.5, height=4.0, turns=2)  # slope 0.64 ~ 32.5 deg
    assert codes(s) == ["SLOPE_TOO_STEEP"]


@pytest.mark.parametrize(
    "height, expected",
    [
        (math.tan(math.radians(4)) * 2 * math.pi * 0.8 * 2 + 1e-6, []),
        (math.tan(math.radians(25)) * 2 * math.pi * 0.8 * 2 - 1e-6, []),
    ],
)
def test_slope_bounds_inclusive(height, expected):
    """FR-010: slopes just inside [tan 4, tan 25] are accepted."""
    assert codes(spiral(height=height)) == expected


def test_track_too_narrow_only_after_ball_spawn():
    """FR-010: TRACK_TOO_NARROW only when ball_spawn(r) was used and track_width < 2.5 r or
    wall_height < 0.6 r."""
    s = spiral()
    assert codes(s) == []
    s.ball_spawn(0.1)  # 2.5 r = 0.25 = track_width; 0.6 r = 0.06 <= 0.08
    assert codes(s) == []
    s.ball_spawn(0.11)
    issues = s.validate()
    assert [i.code for i in issues] == ["TRACK_TOO_NARROW"]
    assert "0.275" in issues[0].hint
    tall = spiral(wall_height=0.05)
    tall.ball_spawn(0.1)
    assert codes(tall) == ["TRACK_TOO_NARROW"]


@pytest.mark.parametrize(
    "kw, code, field",
    [
        ({"radius": "big"}, "INVALID_ARGUMENT", "radius"),
        ({"radius": 0.15}, "OUT_OF_RANGE", "radius"),
        ({"turns": 0}, "OUT_OF_RANGE", "turns"),
        ({"height": 0.02}, "OUT_OF_RANGE", "height"),
        ({"track_width": 0.01}, "TOO_SMALL", "track_width"),
        ({"thickness": -1}, "OUT_OF_RANGE", "thickness"),
        ({"clockwise": "yes"}, "INVALID_ARGUMENT", "clockwise"),
        ({"center": (0, 0)}, "INVALID_ARGUMENT", "center"),
    ],
)
def test_argument_issues_reported_once_by_group(kw, code, field):
    """FR-013: unusable arguments give one issue under the group name and no members."""
    m = Machine()
    s = m.add(spiral(**kw))
    issues = [i for i in m.validate() if i.severity == "error"]
    assert [i.code for i in issues] == [code]
    assert field in issues[0].message
    assert issues[0].entity == s.name == "SpiralRamp_1"
    assert s.members == []


# --- machine / serialization -------------------------------------------------------------------


def test_spiral_in_machine_names_and_round_trip():
    """FR-002 / FR-015: members get <Type>_<n> names; to_dict/from_dict round-trips."""
    m = Machine()
    s = m.add(spiral())
    from rube import Ball

    m.add(Ball(center=s.ball_spawn(0.08), radius=0.08))
    assert m.validate() == []
    assert [e.name for e in m.entities] == ["Floor_1", "SpiralTrack_1", "SupportColumn_1", "Ball_1"]
    d = m.to_dict()
    assert Machine.from_dict(d).to_dict() == d
    assert d["entities"][1]["type"] == "SpiralTrack"
