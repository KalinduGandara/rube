"""Rigid body helpers: turn a ``BodySpec``'s physics values into Blender rigid body settings.

Layer 2 (runs inside Blender; imports ``bpy``). The rigid body is added with the whitelisted
``rigidbody.object_add`` under ``temp_override`` with explicit objects, so real selection and
the active object never matter (SPEC section 1.1, NFR-003). Hinge constraints are added the
same way with ``rigidbody.constraint_add`` on an Empty (design D-11).

Implements: FR-020 (rigid body part), FR-012 (hinge constraint).
"""

from __future__ import annotations

import bpy

from rube.entities import BodySpec, HingeSpec


def add_rigid_body(obj: bpy.types.Object, spec: BodySpec, scene: bpy.types.Scene) -> None:
    """Make ``obj`` a rigid body with every physics value from ``spec``.

    Args:
        obj: Mesh object already linked into ``scene`` (which has a rigid body world).
        spec: Resolved physics: type, shape, mass (kg), friction, restitution, damping,
            collision margin (m), deactivation flags.
    """
    with bpy.context.temp_override(
        scene=scene,
        object=obj,
        active_object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
    ):
        bpy.ops.rigidbody.object_add(type="ACTIVE" if spec.dynamic else "PASSIVE")
    rb = obj.rigid_body
    rb.collision_shape = spec.collision_shape
    rb.mass = spec.mass  # ignored by Bullet for PASSIVE bodies
    rb.friction = spec.friction
    rb.restitution = spec.restitution  # the author-facing name is "bounciness"
    rb.linear_damping = spec.linear_damping
    rb.angular_damping = spec.angular_damping
    # Blender's default margin (0.04 m) visibly floats small bodies; always use ours.
    rb.use_margin = True
    rb.collision_margin = spec.margin
    rb.use_deactivation = spec.use_deactivation
    rb.use_start_deactivated = spec.start_deactivated


def add_hinge(
    empty: bpy.types.Object,
    body_a: bpy.types.Object,
    body_b: bpy.types.Object,
    spec: HingeSpec,
    scene: bpy.types.Scene,
) -> None:
    """Turn ``empty`` into a ``HINGE`` rigid body constraint between two rigid bodies.

    Blender hinges rotate about the constraint object's local Z axis, so the caller must have
    placed ``empty`` at the pivot with its Z axis along the hinge axis (design D-11).

    Args:
        empty: Empty object already linked into ``scene`` at the pivot.
        body_a: First body (the passive fulcrum).
        body_b: Second body (the dynamic plank).
        spec: Resolved hinge; ``disable_collisions`` is applied to the pair.
        scene: Scene with a rigid body world.
    """
    with bpy.context.temp_override(
        scene=scene,
        object=empty,
        active_object=empty,
        selected_objects=[empty],
        selected_editable_objects=[empty],
    ):
        # Also creates the "RigidBodyConstraints" collection in rigidbody_world.constraints.
        bpy.ops.rigidbody.constraint_add(type="HINGE")
    constraint = empty.rigid_body_constraint
    constraint.object1 = body_a
    constraint.object2 = body_b
    constraint.disable_collisions = spec.disable_collisions
