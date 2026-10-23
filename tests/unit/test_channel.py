"""Unit tests for ``geometry.channel_mesh`` and ``Ramp(rails=True)`` (FR-009, T-015).

The U-channel must be a closed, consistently oriented solid (every edge shared by exactly two
faces) so Bullet's ``MESH`` shape and the BVH overlap check work (design section 6).
"""

import math

import pytest
from test_geometry import assert_closed_oriented

from rube.entities import DEFAULTS, Ramp, entity_from_dict
from rube.geometry import channel_mesh, mesh_volume_centroid, path_frames, recenter
from rube.machine import Machine
from rube.vec import Vec3, mat_vec


def assert_vec(actual, expected, tol=1e-9):
    """Component-wise Vec3 comparison."""
    assert list(actual) == pytest.approx(list(expected), abs=tol)


def helix(n=40, radius=1.0, drop=0.5, turns=1.0):
    """Points along a descending helix (a curved, sloped path)."""
    return [
        Vec3(
            radius * math.cos(2 * math.pi * turns * k / (n - 1)),
            radius * math.sin(2 * math.pi * turns * k / (n - 1)),
            1.0 - drop * k / (n - 1),
        )
        for k in range(n)
    ]


# --- channel_mesh ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        [Vec3(0, 0, 0), Vec3(2, 0, 0)],
        [Vec3(0, 0, 1), Vec3(1.5, 1.0, 0.2)],
        helix(),
        helix(n=97, turns=2.0),
    ],
)
def test_channel_mesh_is_closed_solid(path):
    """FR-009: channel mesh is closed and oriented outward (every edge in exactly 2 faces),
    with 8 profile vertices per path point and positive volume."""
    mesh = channel_mesh(path, width=0.25, wall_height=0.08, thickness=0.03)
    assert_closed_oriented(mesh)
    assert len(mesh.vertices) == 8 * len(path)
    # 8 side quads per path segment + 3 convex quads per end cap.
    assert len(mesh.faces) == 8 * (len(path) - 1) + 6
    volume, _ = mesh_volume_centroid(mesh)
    assert volume > 0


def test_channel_mesh_cross_section_straight():
    """FR-009: the path is the floor's top-surface centerline; ``width`` is the inner width
    between the walls, walls rise ``wall_height`` above the floor top and are ``thickness``
    thick, the floor is ``thickness`` thick below the path."""
    w, h, t, length = 0.3, 0.1, 0.04, 2.0
    mesh = channel_mesh([Vec3(0, 0, 0), Vec3(length, 0, 0)], w, h, t)
    lo, hi = mesh.bounds()
    assert_vec(lo, (0, -(w / 2 + t), -t))
    assert_vec(hi, (length, w / 2 + t, h))
    # Exact solid volume: floor slab + two walls.
    expected = length * ((w + 2 * t) * t + 2 * t * h)
    assert mesh_volume_centroid(mesh)[0] == pytest.approx(expected)
    # The inner floor corners of each section sit at +-w/2 across the path point.
    verts = [Vec3(*v) for v in mesh.vertices]
    for k, p in enumerate((Vec3(0, 0, 0), Vec3(length, 0, 0))):
        section = verts[8 * k : 8 * k + 8]
        floor_top = [v for v in section if abs(v.z) < 1e-12 and abs(abs(v.y) - w / 2) < 1e-12]
        assert len(floor_top) == 2
        assert_vec((floor_top[0] + floor_top[1]) / 2, p)


def test_path_frames_sloped_path():
    """FR-009: frames are (tangent, horizontal side, up normal), right-handed; the floor is
    level across the path and the normal tilts with the slope."""
    a, b = Vec3(0, 0, 1), Vec3(2, 0, 0)
    frames = path_frames([a, b])
    for tangent, side, up in frames:
        assert_vec(tangent, (b - a).normalized())
        assert side.z == pytest.approx(0.0)
        assert_vec(side, (0, 1, 0))
        assert up.z > 0
        assert_vec(tangent.cross(side), up)


def test_recenter_moves_origin_to_center_of_volume():
    """FR-020 / design D-3: recentered mesh has its center of volume at the origin."""
    mesh = channel_mesh(helix(), 0.25, 0.08, 0.03)
    centered, offset = recenter(mesh)
    vol, centroid = mesh_volume_centroid(centered)
    assert vol == pytest.approx(mesh_volume_centroid(mesh)[0])
    assert_vec(centroid, (0, 0, 0), tol=1e-9)
    assert_vec(offset, mesh_volume_centroid(mesh)[1])
    assert_vec(Vec3(*centered.vertices[5]) + offset, Vec3(*mesh.vertices[5]))


# --- Ramp(rails=True) ------------------------------------------------------------------------


def rails_ramp(**kw):
    """A 20 degree rails ramp with 2 m of run toward +X."""
    return Ramp((0, 0, 2 * math.tan(math.radians(20))), (2, 0, 0), rails=True, **kw)


def test_rails_ramp_body_is_mesh_channel():
    """FR-009: rails=True builds a passive U-channel, collision MESH, margin 0.005."""
    ramp = rails_ramp()
    assert ramp.validate() == []
    body = ramp.body()
    assert body.collision_shape == "MESH"
    assert body.margin == 0.005
    assert body.dynamic is False
    assert DEFAULTS["RampRails"].margin == 0.005
    assert_closed_oriented(body.mesh)
    # Origin = center of volume (design D-3).
    assert_vec(mesh_volume_centroid(body.mesh)[1], (0, 0, 0), tol=1e-9)
    # The plank ramp keeps BOX / 0.001.
    plain = Ramp((0, 0, 1), (2, 0, 0)).body()
    assert (plain.collision_shape, plain.margin) == ("BOX", 0.001)


def test_rails_ramp_floor_top_centerline_is_start_to_end():
    """FR-009 / FR-008: start/end stay the top-surface centerline of the channel floor; the
    inner width is ``width`` and the walls rise RAIL_HEIGHT above the floor."""
    from rube.entities import RAIL_HEIGHT

    ramp = rails_ramp(width=0.3, thickness=0.04)
    body = ramp.body()
    world = [body.location + mat_vec(body.rotation, Vec3(*v)) for v in body.mesh.vertices]
    for k, end in enumerate((ramp.start, ramp.end)):
        section = world[8 * k : 8 * k + 8]
        # Profile order: index 4 and 5 are the inner floor corners, 3 and 6 the inner wall tops.
        assert_vec((section[4] + section[5]) / 2, end)
        assert (section[4] - section[5]).length() == pytest.approx(0.3)
        assert (section[3] - section[4]).length() == pytest.approx(RAIL_HEIGHT)
    lo, hi = body.aabb()
    assert hi.z == pytest.approx(ramp.start.z + RAIL_HEIGHT * math.cos(math.radians(20)))
    assert hi.y - lo.y == pytest.approx(0.3 + 2 * 0.04)


def test_rails_ramp_anchors_unchanged():
    """FR-008/009: rails do not move the anchors (ball_spawn, exit, slope)."""
    plain = Ramp((0, 0, 1), (2, 0, 0))
    rails = Ramp((0, 0, 1), (2, 0, 0), rails=True)
    assert_vec(rails.ball_spawn(0.1), plain.ball_spawn(0.1))
    assert_vec(rails.exit(0.5), plain.exit(0.5))
    assert rails.slope_deg == pytest.approx(plain.slope_deg)


def test_rails_ramp_round_trip_and_machine():
    """FR-015 / FR-009: a rails ramp serializes and validates inside a machine."""
    m = Machine()
    ramp = m.add(rails_ramp())
    assert m.validate() == []
    d = ramp.to_dict()
    assert d["rails"] is True
    again = entity_from_dict(d)
    assert again.to_dict() == d
    assert again.body().collision_shape == "MESH"
    assert Machine.from_dict(m.to_dict()).to_dict() == m.to_dict()


def test_rails_must_be_bool():
    """FR-013: rails must be True or False."""
    issues = Ramp((0, 0, 1), (2, 0, 0), rails="yes").validate()
    assert [i.code for i in issues] == ["INVALID_ARGUMENT"]
