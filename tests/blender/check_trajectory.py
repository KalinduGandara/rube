"""Blender-side check for A6 (FR-010; design D-10 pattern): runs INSIDE Blender.

Layer: test tooling. Usage::

    Blender -b OUT/machine.blend --python check_trajectory.py -- --object Ball_1 --point X Y Z

``report.json`` holds only initial/final positions, so "the ball passes within 0.3 m of
``spiral.exit``" is measured here: the script steps through every frame of the saved scene
(baked cache), reads the object's world position and prints the smallest distance to the
point as ``min_distance=<m> frame=<n>``. Exits 0 after printing, 1 if the object is missing.
"""

import argparse
import sys

import bpy
from mathutils import Vector


def main() -> int:
    """Print the closest approach of ``--object`` to ``--point``; return the exit code."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--object", required=True, help="name of the moving entity")
    parser.add_argument("--point", type=float, nargs=3, required=True, help="world x y z (m)")
    args = parser.parse_args(argv)

    scene = bpy.context.scene
    obj = bpy.data.objects.get(args.object)
    if obj is None:
        print(f"FAIL: no object {args.object!r}")
        return 1
    target = Vector(args.point)
    best, best_frame = float("inf"), None
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        d = (obj.matrix_world.translation - target).length
        if d < best:
            best, best_frame = d, frame
    print(f"min_distance={best:.6f} frame={best_frame}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
