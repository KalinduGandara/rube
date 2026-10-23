"""Blender-side check for A12 (FR-014, FR-024; design D-10): runs INSIDE Blender.

Layer: test tooling. Usage::

    Blender -b OUT/machine.blend --python check_camera.py -- --ball Ball_1 --frames 1 49 97 ...

For each frame it evaluates the scene (baked cache + camera constraints) and projects the
ball's center with ``bpy_extras.object_utils.world_to_camera_view``; the result must lie in
the middle 50 % of the image (0.25 .. 0.75 on both axes) and in front of the camera.
Prints one line per frame and exits 0 on success, 1 on the first failure.
"""

import argparse
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view


def main() -> int:
    """Check every requested frame; return the process exit code."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--ball", required=True, help="name of the followed entity")
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    args = parser.parse_args(argv)

    scene = bpy.context.scene
    camera = scene.camera
    ball = bpy.data.objects[args.ball]
    if camera is None:
        print("FAIL: scene has no active camera")
        return 1
    ok = True
    for frame in args.frames:
        scene.frame_set(frame)
        x, y, depth = world_to_camera_view(scene, camera, ball.matrix_world.translation)
        inside = depth > 0 and 0.25 <= x <= 0.75 and 0.25 <= y <= 0.75
        print(f"frame {frame}: x={x:.3f} y={y:.3f} depth={depth:.3f} {'ok' if inside else 'FAIL'}")
        ok = ok and inside
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
