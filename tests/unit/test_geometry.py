"""Unit tests for ``rube.geometry`` mesh primitives and AABB helpers (FR-005, FR-006, FR-020).

Every primitive must be built at true size around its center of volume (design D-3), and be a
closed, consistently oriented solid so Bullet and the BVH overlap test behave (SPEC section 3.1).
"""

import math
from collections import Counter

import pytest

from rube.geometry import (
    MeshSpec,
    aabb,
    aabb_gap,
    box_mesh,
    cylinder_mesh,
    mesh_volume_centroid,
    prism_mesh,
    transform_points,
    uv_sphere_mesh,
)
from rube.vec import Vec3, rot_z


def assert_closed_oriented(mesh: MeshSpec):
    """Every edge is shared by exactly 2 faces, traversed once in each direction."""
    directed = Counter()
    for face in mesh.faces:
        assert len(face) >= 3
        for i, a in enumerate(face):
            b = face[(i + 1) % len(face)]
            directed[(a, b)] += 1
    for (a, b), n in directed.items():
        assert n == 1, f"directed edge {(a, b)} used {n} times"
        assert directed.get((b, a)) == 1, f"edge {(a, b)} not shared by exactly 2 faces"


def assert_true_size_centered(mesh: MeshSpec, size, volume):
    """Bounds span ``size``; signed volume ``volume`` (> 0 = outward faces); centroid at 0."""
    lo, hi = mesh.bounds()
    assert (hi - lo).to_list() == pytest.approx(list(size), abs=1e-9)
    vol, centroid = mesh_volume_centroid(mesh)
    assert vol == pytest.approx(volume, rel=0.03)
    assert centroid.length() < 1e-9


def test_box_mesh():
    """FR-006: box has 8 verts / 6 quads, true size, centered, closed."""
    m = box_mesh(0.1, 0.4, 0.8)
    assert len(m.vertices) == 8 and len(m.faces) == 6
    assert_true_size_centered(m, (0.1, 0.4, 0.8), 0.1 * 0.4 * 0.8)
    assert_closed_oriented(m)


def test_uv_sphere_mesh():
    """FR-005: UV sphere 32 x 16 like Blender's default: 482 verts, 512 faces, closed."""
    m = uv_sphere_mesh(0.1)
    assert len(m.vertices) == 32 * 15 + 2
    assert len(m.faces) == 32 * 16
    assert_true_size_centered(m, (0.2, 0.2, 0.2), 4 / 3 * math.pi * 0.1**3)
    assert_closed_oriented(m)


def test_cylinder_mesh():
    """FR-020: cylinder (support column) with n-gon caps, true size, closed."""
    m = cylinder_mesh(0.5, 2.0, segments=32)
    assert len(m.vertices) == 64 and len(m.faces) == 34
    assert_true_size_centered(m, (1.0, 1.0, 2.0), math.pi * 0.25 * 2.0)
    assert_closed_oriented(m)


def test_prism_mesh_centroid_at_origin():
    """FR-020: triangular prism (fulcrum), apex up; origin = center of volume, not bbox center."""
    m = prism_mesh(0.6, 0.3, 0.9)
    assert len(m.vertices) == 6 and len(m.faces) == 5
    assert_true_size_centered(m, (0.6, 0.3, 0.9), 0.5 * 0.6 * 0.9 * 0.3)
    lo, hi = m.bounds()
    assert lo.z == pytest.approx(-0.3) and hi.z == pytest.approx(0.6)  # base at -h/3
    assert_closed_oriented(m)


def test_transform_points_and_aabb():
    """FR-020: world AABB of a rotated, translated mesh."""
    m = box_mesh(2.0, 1.0, 1.0)
    pts = transform_points(m.vertices, rot_z(90), Vec3(10, 0, 0.5))
    lo, hi = aabb(pts)
    assert lo.to_list() == pytest.approx([9.5, -1.0, 0.0])
    assert hi.to_list() == pytest.approx([10.5, 1.0, 1.0])


def test_aabb_gap():
    """FR-013: gap between boxes is 0 when they overlap/touch, else the Euclidean gap."""
    a = (Vec3(0, 0, 0), Vec3(1, 1, 1))
    assert aabb_gap(a, (Vec3(0.5, 0.5, 0.5), Vec3(2, 2, 2))) == 0.0
    assert aabb_gap(a, (Vec3(1.03, 0, 0), Vec3(2, 1, 1))) == pytest.approx(0.03)
    assert aabb_gap(a, (Vec3(4, 5, 0), Vec3(5, 6, 1))) == pytest.approx(5.0)
