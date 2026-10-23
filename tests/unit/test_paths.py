"""Unit tests for path math in ``rube.geometry``: catmull_rom and ArcLengthTable (FR-011)."""

import math

import pytest

from rube.geometry import ArcLengthTable, catmull_rom
from rube.vec import Vec3


def test_catmull_rom_passes_through_waypoints():
    """FR-011: the spline passes through every waypoint (unlike Bezier control points)."""
    pts = [Vec3(0, 0, 0), Vec3(2, 0, 0), Vec3(3, 2, 0), Vec3(1, 4, 0)]
    curve = catmull_rom(pts, samples_per_segment=50)
    assert len(curve) == 3 * 50 + 1
    for k, p in enumerate(pts):
        assert list(curve[k * 50]) == pytest.approx(list(p))


def test_catmull_rom_two_points_is_straight_line():
    """FR-011: two waypoints give a straight line between them."""
    curve = catmull_rom([Vec3(0, 0, 0), Vec3(3, 4, 0)], samples_per_segment=20)
    for p in curve:
        # Collinear with (3, 4, 0) and within the segment.
        assert p.x * 4 - p.y * 3 == pytest.approx(0.0, abs=1e-12)
        assert -1e-12 <= p.x <= 3 + 1e-12


def test_arc_length_table_length_and_inversion():
    """FR-011: cumulative length table gives total length and points at arc length s."""
    # A quarter circle of radius 2, densely sampled.
    poly = [Vec3(2 * math.cos(a), 2 * math.sin(a), 0) for a in
            (math.pi / 2 * i / 2000 for i in range(2001))]  # fmt: skip
    table = ArcLengthTable(poly)
    assert table.length == pytest.approx(math.pi, abs=1e-5)
    p = table.point_at(math.pi / 2)  # half way along = 45 degrees
    assert list(p) == pytest.approx([math.sqrt(2), math.sqrt(2), 0], abs=1e-5)
    assert list(table.point_at(0)) == pytest.approx([2, 0, 0])
    assert list(table.point_at(table.length)) == pytest.approx([0, 2, 0], abs=1e-12)
    # Clamped outside [0, length].
    assert list(table.point_at(-1)) == pytest.approx([2, 0, 0])
    assert list(table.point_at(99)) == pytest.approx([0, 2, 0], abs=1e-12)


def test_arc_length_table_tangent():
    """FR-011: tangent_at(s) is the unit path direction at arc length s."""
    poly = [Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(1, 1, 0)]
    table = ArcLengthTable(poly)
    assert list(table.tangent_at(0.5)) == pytest.approx([1, 0, 0])
    assert list(table.tangent_at(1.5)) == pytest.approx([0, 1, 0])
    assert list(table.tangent_at(2.0)) == pytest.approx([0, 1, 0])


def test_catmull_rom_three_arc_points_follow_the_arc():
    """FR-011 / D-23: quadratic end phantoms make 3 quarter-circle waypoints turn ~90 deg."""
    r = 4.0
    pts = [Vec3(0, 0, 0), Vec3(r * math.sin(math.pi / 4), r - r * math.cos(math.pi / 4), 0),
           Vec3(r, r, 0)]  # fmt: skip
    curve = catmull_rom(pts, samples_per_segment=100)
    center = Vec3(0, r, 0)
    assert max(abs((p - center).length() - r) for p in curve) < 0.05 * r
    table = ArcLengthTable(curve)
    start, end = table.tangent_at(0), table.tangent_at(table.length)
    assert math.degrees(math.atan2(start.y, start.x)) == pytest.approx(0.0, abs=6.0)
    assert math.degrees(math.atan2(end.y, end.x)) == pytest.approx(90.0, abs=6.0)
