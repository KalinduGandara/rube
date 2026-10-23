"""Blender-side settings check for FR-019, FR-020, FR-002, FR-007, FR-012, FR-014, FR-024.

Layer: test tooling; runs INSIDE Blender on a saved ``machine.blend``. Usage::

    Blender -b OUT/machine.blend --python check_scene.py -- --expect expected.json

``expected.json`` is written by ``test_acceptance.expected_scene`` from the requirement
texts and the ``DEFAULTS`` table (never read back from the build output), as::

    {"frame_end": int, "fps": 24,
     "bodies": {name: {"type", "shape", "dynamic", "friction", "restitution",
                       "linear_damping", "angular_damping", "margin", "mass"|null,
                       "use_deactivation", "use_start_deactivated"}},
     "hinges": {name: {"disable_collisions": bool}},
     "camera": "follow" | "static" | null, "video": bool}

Prints one ``FAIL: ...`` line per mismatch and exits 1 if there is any, else exits 0.
"""

import argparse
import json
import math
import sys

import bpy


def check(expected: dict) -> list[str]:
    """Compare the open .blend with ``expected``; returns the list of mismatch messages."""
    failures: list[str] = []

    def eq(what, actual, want):
        if isinstance(want, float):
            good = math.isclose(actual, want, rel_tol=1e-5, abs_tol=1e-6)
        else:
            good = actual == want
        if not good:
            failures.append(f"FAIL: {what} = {actual!r}, expected {want!r}")

    scene = bpy.context.scene
    # FR-019: units, frame range, rigid body world.
    eq("unit_settings.system", scene.unit_settings.system, "METRIC")
    eq("unit_settings.scale_length", scene.unit_settings.scale_length, 1.0)
    eq("render.fps", scene.render.fps, expected["fps"])
    eq("render.fps_base", scene.render.fps_base, 1.0)
    eq("frame_start", scene.frame_start, 1)
    eq("frame_end", scene.frame_end, expected["frame_end"])
    world = scene.rigidbody_world
    if world is None:
        return [*failures, "FAIL: scene has no rigidbody_world"]
    eq("rigidbody_world.substeps_per_frame", world.substeps_per_frame, 20)
    eq("rigidbody_world.solver_iterations", world.solver_iterations, 20)
    eq("rigidbody_world.use_split_impulse", world.use_split_impulse, True)
    eq("point_cache.frame_start", world.point_cache.frame_start, 1)
    eq("point_cache.frame_end", world.point_cache.frame_end, expected["frame_end"])

    # FR-002 / FR-020 / FR-007: one Blender object per entity, named exactly like it.
    for name, want in expected["bodies"].items():
        obj = bpy.data.objects.get(name)
        if obj is None:
            failures.append(f"FAIL: no Blender object named {name!r}")
            continue
        rb = obj.rigid_body
        if rb is None:
            failures.append(f"FAIL: {name} has no rigid_body")
            continue
        eq(f"{name}.rigid_body.type", rb.type, "ACTIVE" if want["dynamic"] else "PASSIVE")
        eq(f"{name}.collision_shape", rb.collision_shape, want["shape"])
        eq(f"{name}.use_margin", rb.use_margin, True)
        eq(f"{name}.collision_margin", rb.collision_margin, want["margin"])
        eq(f"{name}.friction", rb.friction, want["friction"])
        eq(f"{name}.restitution", rb.restitution, want["restitution"])
        eq(f"{name}.linear_damping", rb.linear_damping, want["linear_damping"])
        eq(f"{name}.angular_damping", rb.angular_damping, want["angular_damping"])
        if want["dynamic"] and want.get("mass") is not None:
            eq(f"{name}.mass", rb.mass, want["mass"])
        eq(f"{name}.use_deactivation", rb.use_deactivation, want["use_deactivation"])
        eq(f"{name}.use_start_deactivated", rb.use_start_deactivated, want["use_start_deactivated"])
        eq(f"{name}['rube_name']", obj.get("rube_name"), name)
        eq(f"{name}['rube_type']", obj.get("rube_type"), want["type"])
        eq(f"{name}.scale", tuple(round(s, 6) for s in obj.scale), (1.0, 1.0, 1.0))

    # FR-012: hinge constraints.
    for name, want in expected["hinges"].items():
        obj = bpy.data.objects.get(name)
        con = obj.rigid_body_constraint if obj is not None else None
        if con is None:
            failures.append(f"FAIL: no rigid body constraint on {name!r}")
            continue
        eq(f"{name}.constraint.type", con.type, "HINGE")
        eq(f"{name}.disable_collisions", con.disable_collisions, want["disable_collisions"])
        eq(f"{name}.in constraints collection", obj in list(world.constraints.objects), True)
        eq(f"{name}.rube_type", obj.get("rube_type"), "Hinge")

    # FR-014: a follow camera is constrained, never parented.
    if expected["camera"] == "follow":
        cam = scene.camera
        if cam is None:
            failures.append("FAIL: scene has no camera")
        else:
            eq("camera.parent", cam.parent, None)
            kinds = [c.type for c in cam.constraints]
            eq("camera constraint types", kinds, ["COPY_LOCATION", "TRACK_TO"])
            for c in cam.constraints:
                if c.type == "COPY_LOCATION":
                    eq("COPY_LOCATION.use_offset", c.use_offset, True)
                elif c.type == "TRACK_TO":
                    eq("TRACK_TO.track_axis", c.track_axis, "TRACK_NEGATIVE_Z")
                    eq("TRACK_TO.up_axis", c.up_axis, "UP_Y")
    elif expected["camera"] == "static":
        eq("static camera constraints", len(scene.camera.constraints), 0)

    # FR-024: H.264 when a video was rendered.
    if expected["video"]:
        eq("ffmpeg.codec", scene.render.ffmpeg.codec, "H264")
    return failures


def main() -> int:
    """Run the checks named by ``--expect``; return the process exit code."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect", required=True, help="path of the expectations JSON")
    args = parser.parse_args(argv)
    with open(args.expect, encoding="utf-8") as handle:
        failures = check(json.load(handle))
    for line in failures:
        print(line)
    print(f"checked: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
