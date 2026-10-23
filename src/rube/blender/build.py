"""Builder: resolved Layer 1 specs -> Blender objects, through one ``BUILDERS`` dispatch table.

Layer 2 (runs inside Blender; imports ``bpy``, ``mathutils``). Layer 1 already computed every
vertex and transform (``BodySpec``, design D-2), so building is mechanical: create the mesh
with ``mesh.from_pydata`` at true size around the origin (scale stays (1, 1, 1) and the
origin is the center of volume by construction, design D-3), set the world matrix, color and
custom props, then add the rigid body. Specs are built in registration order (determinism).

Implements: FR-020, FR-002 (Blender object gets exactly the entity name), FR-012 (hinge Empty).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import bpy
from mathutils import Matrix, Vector

from rube.blender.physics import add_hinge, add_rigid_body
from rube.entities import BodySpec, HingeSpec
from rube.machine import Machine


@dataclass
class BuildContext:
    """State shared by the builders while one machine is built.

    Attributes:
        scene: Target scene (rigid body world already created).
        objects: Built objects by entity name, in build order.
        bodies: The ``BodySpec`` of each built rigid body, in build order.
        hinges: The ``HingeSpec`` of each built constraint, in build order.
    """

    scene: bpy.types.Scene
    objects: dict[str, bpy.types.Object] = field(default_factory=dict)
    bodies: list[BodySpec] = field(default_factory=list)
    hinges: list[HingeSpec] = field(default_factory=list)


def world_matrix(spec: BodySpec) -> Matrix:
    """4x4 world matrix from the spec's row-major 3x3 rotation and location (meters)."""
    matrix = Matrix(spec.rotation).to_4x4()
    matrix.translation = tuple(spec.location)
    return matrix


def build_body(spec: BodySpec, ctx: BuildContext) -> list[bpy.types.Object]:
    """Create one rigid body object from a ``BodySpec``.

    Returns:
        ``[obj]``, also recorded in ``ctx.objects`` / ``ctx.bodies``.

    Raises:
        RuntimeError: if Blender renamed the object (the name must survive exactly, FR-002).
    """
    mesh = bpy.data.meshes.new(spec.name)
    mesh.from_pydata(
        [tuple(v) for v in spec.mesh.vertices], [], [tuple(f) for f in spec.mesh.faces]
    )
    mesh.validate()
    mesh.update()
    obj = bpy.data.objects.new(spec.name, mesh)
    if obj.name != spec.name:  # reset() emptied bpy.data, so this means a duplicate name
        raise RuntimeError(f"Blender renamed object {spec.name!r} to {obj.name!r}")
    ctx.scene.collection.objects.link(obj)
    obj.matrix_world = world_matrix(spec)
    obj.color = spec.color  # shown by Workbench with color_type='OBJECT'
    obj["rube_name"] = spec.name
    obj["rube_type"] = spec.type
    add_rigid_body(obj, spec, ctx.scene)
    ctx.objects[spec.name] = obj
    ctx.bodies.append(spec)
    return [obj]


def build_hinge(spec: HingeSpec, ctx: BuildContext) -> list[bpy.types.Object]:
    """Create the constraint Empty of a hinge (design D-11).

    The Empty sits at the pivot and is rotated so its local Z axis is the hinge axis, because
    Blender's ``HINGE`` constraint turns about the constraint object's Z. The bodies must
    already be built (``Machine.bodies()`` come before ``Machine.constraints()``).

    Returns:
        ``[empty]``, recorded in ``ctx.objects`` / ``ctx.hinges``.
    """
    empty = bpy.data.objects.new(spec.name, None)
    if empty.name != spec.name:
        raise RuntimeError(f"Blender renamed object {spec.name!r} to {empty.name!r}")
    ctx.scene.collection.objects.link(empty)
    rotation = Vector((0.0, 0.0, 1.0)).rotation_difference(Vector(tuple(spec.axis)))
    matrix = rotation.to_matrix().to_4x4()
    matrix.translation = tuple(spec.pivot)
    empty.matrix_world = matrix
    empty["rube_name"] = spec.name
    empty["rube_type"] = "Hinge"
    add_hinge(empty, ctx.objects[spec.body_a], ctx.objects[spec.body_b], spec, ctx.scene)
    ctx.objects[spec.name] = empty
    ctx.hinges.append(spec)
    return [empty]


#: Spec class -> builder.
BUILDERS: dict[type, Callable[[object, BuildContext], list[bpy.types.Object]]] = {
    BodySpec: build_body,
    HingeSpec: build_hinge,
}


def build_machine(machine: Machine, scene: bpy.types.Scene) -> BuildContext:
    """Build every body, then every constraint, of ``machine`` in registration order.

    Raises:
        NotImplementedError: a spec kind without a builder (framework bug -> internal_error).
    """
    ctx = BuildContext(scene)
    for spec in [*machine.bodies(), *machine.constraints()]:
        builder = BUILDERS.get(type(spec))
        if builder is None:
            raise NotImplementedError(f"no Blender builder for {type(spec).__name__}")
        builder(spec, ctx)
    return ctx
