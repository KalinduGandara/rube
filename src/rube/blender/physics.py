"""Rigid body helpers: turn a ``BodySpec``'s physics values into Blender rigid body settings.

Layer 2 (runs inside Blender; imports ``bpy``). The rigid body is added with the whitelisted
``rigidbody.object_add`` under ``temp_override`` with explicit objects, so real selection and
the active object never matter (SPEC section 1.1, NFR-003). Hinge constraints are added here
in milestone M6.

Implements: FR-020 (rigid body part).
"""

from __future__ import annotations

import bpy

from rube.entities import BodySpec


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
