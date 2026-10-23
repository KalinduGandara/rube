"""Blender API probe: re-verifies every row of SPEC section 1.1 (FR-026, milestone M0).

Layer: test tooling (runs INSIDE Blender, not under system Python). Self-contained: it
imports nothing from ``rube`` so it keeps working when the package is broken.

Run:  Blender -b --factory-startup --python-exit-code 1 --python probe_api.py

Each ``check_*`` function verifies one row of the SPEC 1.1 table and returns a list of
human-readable failure strings (empty = fact still holds). All failures are printed and the
process exits 1, naming every fact that changed, so an API drift is caught in one run.
"""

import math
import sys
import tempfile
from pathlib import Path

import bpy


def new_scene_with_world():
    """Reset to an empty factory scene and add a rigid body world.

    Returns:
        The active scene (rigid body world created).
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    bpy.ops.rigidbody.world_add()
    return sc


def add_rigid_body(obj, body_type):
    """Add a rigid body to ``obj`` using the pattern from SPEC 1.1 (temp_override, no selection).

    Args:
        obj: Blender object, already linked into the scene.
        body_type: ``'ACTIVE'`` or ``'PASSIVE'``.
    """
    with bpy.context.temp_override(
        object=obj, active_object=obj, selected_objects=[obj], selected_editable_objects=[obj]
    ):
        bpy.ops.rigidbody.object_add(type=body_type)


def make_cube(name, location, scale=(1.0, 1.0, 1.0)):
    """Create and link a unit cube mesh object via bpy.data (no ops).

    Args:
        name: Object name.
        location: (x, y, z) in meters.
        scale: Object scale.

    Returns:
        The new object.
    """
    verts = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
    faces = [
        (0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
        (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3),
    ]  # fmt: skip
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.scale = scale
    bpy.context.scene.collection.objects.link(obj)
    return obj


def check_world_steps():
    """Row 1: no ``steps_per_second``; ``substeps_per_frame`` default 10."""
    fails = []
    rw = new_scene_with_world().rigidbody_world
    if hasattr(rw, "steps_per_second"):
        fails.append("rigidbody_world.steps_per_second now EXISTS (spec says it does not)")
    if not hasattr(rw, "substeps_per_frame"):
        fails.append("rigidbody_world.substeps_per_frame is MISSING")
    elif rw.substeps_per_frame != 10:
        fails.append(f"substeps_per_frame default is {rw.substeps_per_frame}, expected 10")
    return fails


def check_solver_iterations():
    """Row 2: ``solver_iterations`` default 10."""
    rw = new_scene_with_world().rigidbody_world
    if not hasattr(rw, "solver_iterations"):
        return ["rigidbody_world.solver_iterations is MISSING"]
    if rw.solver_iterations != 10:
        return [f"solver_iterations default is {rw.solver_iterations}, expected 10"]
    return []


def check_rigid_body_props():
    """Rows 3-5 and 'Rigid body add': margin, restitution, damping defaults.

    Also covers the row on ``rigidbody.object_add`` working under ``temp_override``.
    """
    fails = []
    new_scene_with_world()
    obj = make_cube("ProbeBody", (0, 0, 1))
    try:
        add_rigid_body(obj, "ACTIVE")
    except Exception as exc:  # noqa: BLE001 - any failure means the fact changed
        return [f"rigidbody.object_add under temp_override raised: {exc!r}"]
    rb = obj.rigid_body
    if rb is None:
        return ["rigidbody.object_add under temp_override did not create obj.rigid_body"]
    if hasattr(rb, "margin"):
        fails.append("rigid_body.margin now EXISTS (spec says it does not)")
    if not hasattr(rb, "collision_margin"):
        fails.append("rigid_body.collision_margin is MISSING")
    elif not math.isclose(rb.collision_margin, 0.04, abs_tol=1e-6):
        fails.append(f"collision_margin default is {rb.collision_margin}, expected 0.04")
    if not hasattr(rb, "use_margin"):
        fails.append("rigid_body.use_margin is MISSING")
    if not hasattr(rb, "restitution"):
        fails.append("rigid_body.restitution is MISSING")
    elif rb.restitution != 0.0:
        fails.append(f"restitution default is {rb.restitution}, expected 0.0")
    if not math.isclose(rb.linear_damping, 0.04, abs_tol=1e-6):
        fails.append(f"linear_damping default is {rb.linear_damping}, expected 0.04")
    if not math.isclose(rb.angular_damping, 0.1, abs_tol=1e-6):
        fails.append(f"angular_damping default is {rb.angular_damping}, expected 0.1")
    return fails


def check_cache_range():
    """Row 6: point_cache.frame_end defaults to 250 independently of scene.frame_end."""
    sc = new_scene_with_world()
    sc.frame_end = 48
    pc = sc.rigidbody_world.point_cache
    if pc.frame_end != 250:
        return [f"point_cache.frame_end is {pc.frame_end} after scene.frame_end=48, expected 250"]
    return []


def check_bake_and_bullet(tmp):
    """Rows 7 and 11: ptcache.bake works headless; a bad scene does not raise.

    Args:
        tmp: Path of a scratch directory (unused here, kept for a uniform check signature).

    Scene: a cube dropped on a passive floor (good), plus a second cube spawned deep inside
    the floor (bad: deeply intersecting). Baking must succeed without a Python exception, and
    the good cube must really move (bake produced simulation data).
    """
    del tmp
    fails = []
    sc = new_scene_with_world()
    sc.frame_start, sc.frame_end = 1, 24
    rw = sc.rigidbody_world
    rw.point_cache.frame_start, rw.point_cache.frame_end = 1, 24

    floor = make_cube("ProbeFloor", (0, 0, -0.5), scale=(10, 10, 1))
    good = make_cube("ProbeGood", (0, 0, 2))
    bad = make_cube("ProbeBad", (3, 3, -0.4))  # overlaps the floor volume
    add_rigid_body(floor, "PASSIVE")
    add_rigid_body(good, "ACTIVE")
    add_rigid_body(bad, "ACTIVE")

    try:
        bpy.ops.ptcache.free_bake_all()  # fresh bake (SPEC section 6 step 6)
    except Exception as exc:  # noqa: BLE001
        fails.append(f"ptcache.free_bake_all raised: {exc!r}")
    sc.frame_set(1)
    try:
        with bpy.context.temp_override(scene=sc, point_cache=rw.point_cache):
            bpy.ops.ptcache.bake(bake=True)
    except Exception as exc:  # noqa: BLE001
        return fails + [f"ptcache.bake under temp_override raised: {exc!r} (bad scene or API)"]
    if not rw.point_cache.is_baked:
        fails.append("point_cache.is_baked is False after ptcache.bake")
    sc.frame_set(24)
    z = good.matrix_world.translation.z
    if not z < 1.5:
        fails.append(f"baked cube did not fall (z={z:.3f} at frame 24, expected < 1.5)")
    return fails


def check_opengl_background():
    """Row 8: ``render.opengl`` fails in background mode."""
    new_scene_with_world()
    try:
        bpy.ops.render.opengl(write_still=False)
    except RuntimeError:
        return []
    return ["bpy.ops.render.opengl() now WORKS in background mode (spec says it fails)"]


def check_workbench_render(tmp):
    """Row 8 (consequence): BLENDER_WORKBENCH + render.render(write_still) with an absolute path.

    Args:
        tmp: Path of a scratch directory; the PNG is written here with an absolute path.
    """
    sc = new_scene_with_world()
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x, sc.render.resolution_y = 64, 36
    sc.render.image_settings.file_format = "PNG"
    cam = bpy.data.objects.new("ProbeCam", bpy.data.cameras.new("ProbeCam"))
    cam.location = (0, -5, 1)
    cam.rotation_euler = (math.radians(90), 0, 0)
    sc.collection.objects.link(cam)
    sc.camera = cam
    out = Path(tmp) / "probe_render.png"
    sc.render.filepath = str(out)
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:  # noqa: BLE001
        return [f"Workbench render.render(write_still=True) raised: {exc!r}"]
    if not out.exists() or out.stat().st_size == 0:
        return [f"Workbench render wrote no file at {out}"]
    return []


def check_relative_output_path(tmp):
    """Row 9: ``//relative`` output paths fail when no .blend is saved.

    Args:
        tmp: Path of a scratch directory; the relative render must NOT produce a file there
            (and bpy.path.abspath of ``//x`` must not resolve into a saved-file directory).
    """
    sc = new_scene_with_world()
    if bpy.data.filepath:
        return [f"factory scene unexpectedly has a filepath: {bpy.data.filepath}"]
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x, sc.render.resolution_y = 16, 16
    cam = bpy.data.objects.new("ProbeCam2", bpy.data.cameras.new("ProbeCam2"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    sc.render.filepath = "//probe_rel.png"
    try:
        bpy.ops.render.render(write_still=True)
    except Exception:  # noqa: BLE001 - raising is the documented "fails" behavior
        return []
    # Not raising is only acceptable if nothing resolvable was written; otherwise the fact changed.
    resolved = Path(bpy.path.abspath("//probe_rel.png"))
    if resolved.exists():
        resolved.unlink()
        return [f"'//relative' render path now WORKS without a saved .blend (wrote {resolved})"]
    return []


CHECKS = [
    ("rigid body world: substeps_per_frame, no steps_per_second", check_world_steps, False),
    ("rigid body world: solver_iterations", check_solver_iterations, False),
    ("rigid body props + object_add under temp_override", check_rigid_body_props, False),
    ("point_cache.frame_end independent default 250", check_cache_range, False),
    ("ptcache.bake works headless; bad scenes do not raise", check_bake_and_bullet, True),
    ("render.opengl fails in background", check_opengl_background, False),
    ("Workbench render with absolute path", check_workbench_render, True),
    ("//relative output path fails without saved .blend", check_relative_output_path, True),
]


def main():
    """Run all checks, print a report, and exit non-zero if any SPEC 1.1 fact changed."""
    print(f"Blender {bpy.app.version_string}")
    all_fails = []
    with tempfile.TemporaryDirectory(prefix="rube_probe_") as tmp:
        for title, fn, wants_tmp in CHECKS:
            try:
                fails = fn(tmp) if wants_tmp else fn()
            except Exception as exc:  # noqa: BLE001 - a crashing check is also a changed fact
                fails = [f"check crashed: {exc!r}"]
            status = "ok" if not fails else "CHANGED"
            print(f"[{status}] {title}")
            for f in fails:
                print(f"    - {f}")
                all_fails.append(f"{title}: {f}")
    if all_fails:
        print(f"PROBE FAILED: {len(all_fails)} SPEC 1.1 fact(s) changed")
        sys.exit(1)
    print("PROBE OK: all SPEC 1.1 facts hold")


main()
