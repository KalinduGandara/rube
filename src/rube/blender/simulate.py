"""Simulation inside Blender: pre-bake overlap check, bake, per-frame sampling.

Layer 3 (runs inside Blender; imports ``bpy``, ``mathutils``). SPEC section 8 steps 5-7.
Bullet does not raise on a bad scene -- bodies tunnel or explode -- so the overlap check runs
*before* the bake (overlaps at frame 1 are the #1 cause of explosions), and the judgement of
the sampled motion is left to the pure ``rube.analysis`` (design D-6).

Implements: FR-021, FR-022, FR-023 (sampling).
"""

from __future__ import annotations

from itertools import combinations

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from rube.analysis import Track
from rube.blender.build import BuildContext
from rube.errors import Issue, error
from rube.vec import Vec3


class _Shape:
    """World-space triangles of one built body: AABB + BVH tree (design D-19)."""

    def __init__(self, obj: bpy.types.Object):
        world = obj.matrix_world
        # FromObject would give a tree in object-local space; trees of two different objects
        # are only comparable in world space, so transform the vertices first.
        self.vertices = [world @ v.co for v in obj.data.vertices]
        polygons = [tuple(p.vertices) for p in obj.data.polygons]
        self.tree = BVHTree.FromPolygons(self.vertices, polygons)
        self.lo = Vector(tuple(min(v[i] for v in self.vertices) for i in range(3)))
        self.hi = Vector(tuple(max(v[i] for v in self.vertices) for i in range(3)))

    def aabb_overlap(self, other: _Shape) -> tuple[float, float, float] | None:
        """Extent (m) of the AABB intersection per axis, or ``None`` if they are apart."""
        extent = tuple(
            min(self.hi[i], other.hi[i]) - max(self.lo[i], other.lo[i]) for i in range(3)
        )
        return extent if all(e > 0 for e in extent) else None

    def contains(self, point: Vector) -> bool:
        """True if ``point`` is inside this closed mesh (faces wound outward).

        The nearest surface point's face normal points away from the inside, so a point
        behind it is inside. Exact for convex shapes, which every v1 body is near contacts.
        """
        location, normal, _index, _distance = self.tree.find_nearest(point)
        return location is not None and (point - location).dot(normal) < 0


def _intersect(a: _Shape, b: _Shape) -> bool:
    """Surface triangles cross, or one body sits entirely inside the other."""
    if a.tree.overlap(b.tree):
        return True
    return b.contains(a.vertices[0]) or a.contains(b.vertices[0])


def check_overlaps(
    ctx: BuildContext, skip_pairs: frozenset[frozenset[str]] = frozenset()
) -> list[Issue]:
    """``OVERLAP`` errors for every pair of rigid bodies intersecting at frame 1.

    Pairs of two passive bodies are skipped (they never move, design D-18), as are pairs in
    ``skip_pairs`` (bodies joined by a constraint with ``disable_collisions``).

    Args:
        ctx: Built machine (objects at their frame-1 transforms).
        skip_pairs: ``frozenset({name_a, name_b})`` pairs to ignore.

    Returns:
        One error per intersecting pair, naming both entities in build order.
    """
    for view_layer in ctx.scene.view_layers:  # make matrix_world reflect the transforms just set
        view_layer.update()
    shapes = {spec.name: _Shape(ctx.objects[spec.name]) for spec in ctx.bodies}
    issues: list[Issue] = []
    for a, b in combinations(ctx.bodies, 2):
        if not (a.dynamic or b.dynamic) or frozenset((a.name, b.name)) in skip_pairs:
            continue
        extent = shapes[a.name].aabb_overlap(shapes[b.name])
        if extent is None or not _intersect(shapes[a.name], shapes[b.name]):
            continue
        dx, dy, dz = extent
        issues.append(
            error(
                "OVERLAP",
                f"{a.name},{b.name}",
                f"{a.name} and {b.name} intersect at the start (their bounding boxes overlap "
                f"by {dx:.3f} x {dy:.3f} x {dz:.3f} m); Bullet would push them apart violently",
                f"move {a.name} or {b.name} so they do not touch (a few mm of clearance is "
                "enough); use anchors such as ramp.ball_spawn(r) or block.top_center",
            )
        )
    return issues


def bake(scene: bpy.types.Scene) -> str | None:
    """Free old caches and bake the rigid body world over the scene range.

    Returns:
        ``None`` on success, else Blender's error message. A hang is not caught here: the
        CLI's process timeout handles it (SPEC section 8 step 6).
    """
    point_cache = scene.rigidbody_world.point_cache
    try:
        with bpy.context.temp_override(scene=scene):
            bpy.ops.ptcache.free_bake_all()
        scene.frame_set(scene.frame_start)
        with bpy.context.temp_override(scene=scene, point_cache=point_cache):
            bpy.ops.ptcache.bake(bake=True)
    except RuntimeError as exc:
        return str(exc).strip() or type(exc).__name__
    return None


def sample(ctx: BuildContext) -> list[Track]:
    """World transform of every dynamic body at every frame (baked cache must exist).

    Returns:
        One ``Track`` per dynamic body in build order; sample ``i`` is frame
        ``frame_start + i``.
    """
    scene = ctx.scene
    dynamic = [spec for spec in ctx.bodies if spec.dynamic]
    positions: dict[str, list[Vec3]] = {spec.name: [] for spec in dynamic}
    rotations: dict[str, list[tuple]] = {spec.name: [] for spec in dynamic}
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        for spec in dynamic:
            world = ctx.objects[spec.name].matrix_world
            positions[spec.name].append(Vec3(*(float(c) for c in world.translation)))
            rotations[spec.name].append(
                tuple(tuple(float(c) for c in row) for row in world.to_3x3())
            )
    return [Track(s.name, s.type, positions[s.name], rotations[s.name]) for s in dynamic]
