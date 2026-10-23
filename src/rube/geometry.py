"""Mesh geometry and bounding boxes, computed without Blender.

Layer 1 (pure Python). All geometry is generated here so it is unit-testable (SPEC section 3.1,
design D-2); Layer 2 only turns a ``MeshSpec`` into a Blender mesh with ``from_pydata``.

Every primitive is built **at true size around its center of volume** (design D-3): the
object origin is the center of mass by construction and object scale stays ``(1, 1, 1)``,
so no ``transform_apply`` / ``origin_set`` is ever needed. Faces are wound counter-clockwise
seen from outside (outward normals) and every mesh is a closed solid, which Bullet's ``MESH``
shape and the BVH overlap check rely on.

Paths: ``catmull_rom`` turns waypoints into a dense polyline through them and
``ArcLengthTable`` maps arc length to points/tangents on it, so generators can place parts at
equal arc length (design section 6). A later milestone adds ``channel_mesh`` here.

Implements: FR-005, FR-006, FR-011 (spline + arc-length resampling), FR-020 (mesh data for
builders), FR-013 (AABB helpers for MASS_RATIO / auto camera).
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rube.vec import Mat3, Vec3, mat_vec

Point = tuple[float, float, float]
AABB = tuple[Vec3, Vec3]  # (min corner, max corner), world meters


@dataclass(frozen=True)
class MeshSpec:
    """Mesh data in the object's local frame (meters, origin = center of volume).

    Attributes:
        vertices: ``(x, y, z)`` tuples.
        faces: Vertex-index tuples (3 or more), counter-clockwise seen from outside.
    """

    vertices: tuple[Point, ...]
    faces: tuple[tuple[int, ...], ...]

    def bounds(self) -> AABB:
        """Local axis-aligned bounds ``(min, max)``."""
        return aabb(Vec3(*v) for v in self.vertices)


def box_mesh(sx: float, sy: float, sz: float) -> MeshSpec:
    """Axis-aligned box of size ``sx x sy x sz`` meters centered on the origin.

    Returns:
        8 vertices, 6 quad faces.
    """
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    verts = (
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
        (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz),
    )  # fmt: skip
    faces = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (3, 0, 4, 7), (1, 2, 6, 5))
    return MeshSpec(verts, faces)


def uv_sphere_mesh(radius: float, segments: int = 32, rings: int = 16) -> MeshSpec:
    """UV sphere matching Blender's default topology (32 segments x 16 rings).

    Args:
        radius: Sphere radius in meters.
        segments: Vertices around each latitude ring.
        rings: Latitude bands from pole to pole.

    Returns:
        ``segments * (rings - 1) + 2`` vertices; triangle fans at the poles, quads elsewhere.
    """
    verts: list[Point] = [(0.0, 0.0, radius)]
    for i in range(1, rings):
        theta = math.pi * i / rings  # polar angle from +Z
        r, z = radius * math.sin(theta), radius * math.cos(theta)
        for j in range(segments):
            phi = 2 * math.pi * j / segments
            verts.append((r * math.cos(phi), r * math.sin(phi), z))
    verts.append((0.0, 0.0, -radius))
    bottom = len(verts) - 1

    def ring(i: int, j: int) -> int:
        return 1 + (i - 1) * segments + (j % segments)

    faces: list[tuple[int, ...]] = []
    for j in range(segments):
        faces.append((0, ring(1, j), ring(1, j + 1)))
    for i in range(1, rings - 1):
        for j in range(segments):
            faces.append((ring(i, j), ring(i + 1, j), ring(i + 1, j + 1), ring(i, j + 1)))
    for j in range(segments):
        faces.append((bottom, ring(rings - 1, j + 1), ring(rings - 1, j)))
    return MeshSpec(tuple(verts), tuple(faces))


def cylinder_mesh(radius: float, depth: float, segments: int = 32) -> MeshSpec:
    """Vertical cylinder (axis +Z) of ``depth`` meters centered on the origin, n-gon caps.

    Returns:
        ``2 * segments`` vertices, ``segments`` side quads plus 2 caps.
    """
    hz = depth / 2
    ring = [
        (
            radius * math.cos(2 * math.pi * j / segments),
            radius * math.sin(2 * math.pi * j / segments),
        )
        for j in range(segments)
    ]
    verts = tuple((x, y, -hz) for x, y in ring) + tuple((x, y, hz) for x, y in ring)
    n = segments
    sides = tuple((j, (j + 1) % n, n + (j + 1) % n, n + j) for j in range(n))
    top = tuple(range(n, 2 * n))
    bottom = tuple(reversed(range(n)))
    return MeshSpec(verts, sides + (top, bottom))


def prism_mesh(width: float, depth: float, height: float) -> MeshSpec:
    """Triangular prism (lever fulcrum): isosceles triangle in XZ, apex up, extruded along Y.

    The base spans ``width`` on X, the apex is ``height`` above the base, extrusion ``depth``
    on Y. Why the base sits at ``z = -height/3``: a triangle's centroid is 1/3 of the way up,
    and the origin must be the center of volume (design D-3), not the bounding-box center.
    """
    hw, hd = width / 2, depth / 2
    zb, za = -height / 3, 2 * height / 3
    verts = (
        (-hw, -hd, zb), (hw, -hd, zb), (0.0, -hd, za),
        (-hw, hd, zb), (hw, hd, zb), (0.0, hd, za),
    )  # fmt: skip
    faces = ((0, 1, 2), (3, 5, 4), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0))
    return MeshSpec(verts, faces)


def mesh_volume_centroid(mesh: MeshSpec) -> tuple[float, Vec3]:
    """Signed volume and center of volume of a closed mesh (divergence theorem).

    Returns:
        ``(volume, centroid)``; volume is positive for outward-wound faces.
    """
    vol = 0.0
    acc = Vec3(0.0, 0.0, 0.0)
    pts = [Vec3(*v) for v in mesh.vertices]
    for face in mesh.faces:
        a = pts[face[0]]
        for k in range(1, len(face) - 1):
            b, c = pts[face[k]], pts[face[k + 1]]
            v = a.dot(b.cross(c)) / 6.0  # signed tetrahedron (origin, a, b, c)
            vol += v
            acc = acc + (a + b + c) * (v / 4.0)
    return vol, (acc / vol if vol else acc)


def transform_points(
    vertices: Iterable[Sequence[float]], rotation: Mat3, location: Vec3
) -> list[Vec3]:
    """Map local vertices to world space: ``location + rotation @ v``."""
    return [location + mat_vec(rotation, Vec3(*v)) for v in vertices]


def aabb(points: Iterable[Vec3]) -> AABB:
    """Axis-aligned bounding box ``(min, max)`` of a non-empty point set."""
    pts = list(points)
    return (
        Vec3(min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)),
        Vec3(max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)),
    )


def aabb_union(boxes: Iterable[AABB]) -> AABB:
    """Smallest AABB containing all given boxes (non-empty)."""
    return aabb(p for box in boxes for p in box)


def aabb_gap(a: AABB, b: AABB) -> float:
    """Euclidean distance between two AABBs; 0.0 when they touch or overlap (meters)."""
    d = [
        max(0.0, b[0].x - a[1].x, a[0].x - b[1].x),
        max(0.0, b[0].y - a[1].y, a[0].y - b[1].y),
        max(0.0, b[0].z - a[1].z, a[0].z - b[1].z),
    ]
    return math.sqrt(sum(c * c for c in d))


# --- paths ----------------------------------------------------------------------------------


def catmull_rom(points: Sequence[Vec3], samples_per_segment: int = 200) -> list[Vec3]:
    """Dense polyline along a uniform Catmull-Rom spline **through** every waypoint.

    The curve needs one phantom control point beyond each end. They are extrapolated
    quadratically (``P[-1] = 3 P0 - 3 P1 + P2``), so the end tangents follow the parabola
    through the first / last three waypoints (design D-23); with two waypoints the phantoms
    are extrapolated linearly and the curve is the straight segment.
    Why not duplicated end points: they force the end tangent onto the chord to the next
    waypoint, which makes the curve sag and then turn sharply near a corner waypoint (three
    points on a quarter circle would turn only 45 degrees instead of 90).
    Why uniform (not centripetal): flat, gently curving domino paths have no cusps or loops.

    Args:
        points: Two or more waypoints (meters), consecutive ones distinct.
        samples_per_segment: Polyline points per waypoint-to-waypoint segment.

    Returns:
        ``(len(points) - 1) * samples_per_segment + 1`` points; index
        ``k * samples_per_segment`` is waypoint ``k``.
    """
    if len(points) == 2:
        head, tail = points[0] * 2.0 - points[1], points[-1] * 2.0 - points[-2]
    else:
        head = points[0] * 3.0 - points[1] * 3.0 + points[2]
        tail = points[-1] * 3.0 - points[-2] * 3.0 + points[-3]
    ctrl = [head, *points, tail]
    out: list[Vec3] = []
    for i in range(1, len(ctrl) - 2):
        p0, p1, p2, p3 = ctrl[i - 1], ctrl[i], ctrl[i + 1], ctrl[i + 2]
        for j in range(samples_per_segment):
            t = j / samples_per_segment
            t2, t3 = t * t, t * t * t
            # Standard uniform Catmull-Rom basis (tension 0.5).
            out.append(
                (
                    p1 * 2.0
                    + (p2 - p0) * t
                    + (p0 * 2.0 - p1 * 5.0 + p2 * 4.0 - p3) * t2
                    + (p1 * 3.0 - p0 - p2 * 3.0 + p3) * t3
                )
                * 0.5
            )
    out.append(points[-1])
    return out


class ArcLengthTable:
    """Cumulative arc-length table of a polyline, inverted by binary search.

    Placing objects at equal *arc length* (not equal spline parameter, which bunches them up
    where the spline is slow) needs the inverse map s -> point; this is it (SPEC 6.1).

    Args:
        polyline: Two or more points (meters), e.g. from ``catmull_rom``.

    Attributes:
        length: Total length in meters.
    """

    def __init__(self, polyline: Sequence[Vec3]):
        self.points = list(polyline)
        self.cumulative = [0.0]
        for a, b in zip(self.points, self.points[1:], strict=False):
            self.cumulative.append(self.cumulative[-1] + (b - a).length())
        self.length = self.cumulative[-1]

    def _segment(self, s: float) -> tuple[int, float]:
        """Index ``i`` of the segment ``points[i] -> points[i + 1]`` holding ``s``, and the
        fraction along it; ``s`` is clamped to ``[0, length]``. Zero-length segments are
        skipped by ``bisect`` because their cumulative values are equal."""
        s = min(max(s, 0.0), self.length)
        i = bisect.bisect_right(self.cumulative, s) - 1
        i = min(max(i, 0), len(self.points) - 2)
        seg = self.cumulative[i + 1] - self.cumulative[i]
        return i, (s - self.cumulative[i]) / seg if seg > 0 else 0.0

    def point_at(self, s: float) -> Vec3:
        """Point at arc length ``s`` meters from the start (clamped to the path)."""
        i, f = self._segment(s)
        a, b = self.points[i], self.points[i + 1]
        return a + (b - a) * f

    def tangent_at(self, s: float) -> Vec3:
        """Unit direction of travel at arc length ``s`` (finite difference of the polyline)."""
        i, _ = self._segment(s)
        # Step back over zero-length segments so a duplicated point still yields a direction.
        while i > 0 and self.cumulative[i + 1] == self.cumulative[i]:
            i -= 1
        return (self.points[i + 1] - self.points[i]).normalized()
