"""Scene preparation inside Blender: reset, scene settings, rigid body world.

Layer 3 (runs inside Blender; imports ``bpy``). Called by ``bootstrap`` before anything is
built (SPEC section 8 steps 1-3).

Implements: FR-019.
"""

from __future__ import annotations

import bpy

from rube.machine import FPS

#: Bullet substeps per frame (20 x 24 fps = 480 Hz) and constraint solver iterations.
SUBSTEPS_PER_FRAME = 20
SOLVER_ITERATIONS = 20
#: Gravity, m/s^2 along Z (SPEC section 2).
GRAVITY = (0.0, 0.0, -9.81)


def reset() -> None:
    """Delete every object, mesh, material, camera, light and collection from ``bpy.data``.

    Why not ``wm.read_factory_settings``: it can invalidate the running script's context and
    is redundant with ``--factory-startup`` (SPEC section 8 step 1). Objects go first so the
    data blocks they use have no users left when they are removed.
    """
    for datablocks in (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.collections,
    ):
        for block in list(datablocks):
            datablocks.remove(block)


def configure(scene: bpy.types.Scene, frame_end: int) -> None:
    """Metric units at scale 1, 24 fps, frames ``1 .. frame_end``, gravity -9.81 on Z.

    Args:
        scene: The scene to configure.
        frame_end: Last frame, ``1 + ceil(duration * 24)`` (``Machine.frame_end``).
    """
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.fps = FPS
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.use_gravity = True
    scene.gravity = GRAVITY


def add_rigid_body_world(scene: bpy.types.Scene) -> bpy.types.RigidBodyWorld:
    """Create the rigid body world with rube's solver settings and cache range.

    Call after ``configure``: the point cache range is copied from the scene range because
    ``point_cache.frame_end`` defaults to 250 independently of ``scene.frame_end`` and the
    simulation would silently stop there (SPEC section 1.1).

    Returns:
        ``scene.rigidbody_world``.
    """
    if scene.rigidbody_world is None:
        with bpy.context.temp_override(scene=scene):
            bpy.ops.rigidbody.world_add()
    world = scene.rigidbody_world
    world.enabled = True
    world.time_scale = 1.0
    # The attribute is substeps_per_frame; "steps_per_second" does not exist in 5.2 (SPEC 1.1).
    world.substeps_per_frame = SUBSTEPS_PER_FRAME
    world.solver_iterations = SOLVER_ITERATIONS
    world.use_split_impulse = True
    world.point_cache.frame_start = scene.frame_start
    world.point_cache.frame_end = scene.frame_end
    return world
