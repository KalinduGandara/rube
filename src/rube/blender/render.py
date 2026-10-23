"""Camera, Workbench previews (stills and video) and the ``.blend`` save inside Blender.

Layer 3 (runs inside Blender; imports ``bpy``, ``mathutils``). SPEC section 8 steps 8-9.
Previews use ``BLENDER_WORKBENCH`` with solid shading and per-object colors through
``bpy.ops.render.render`` (design D-9): ``render.opengl`` fails headless (SPEC section 1.1).
Paths are always absolute: ``//relative`` output paths fail when no ``.blend`` has been
saved (SPEC section 1.1).

Implements: FR-014 (placing the camera), FR-024 (stills, video, ``machine.blend``).
"""

from __future__ import annotations

from pathlib import Path

import bpy
from mathutils import Matrix

from rube.camera import RESOLUTION, SENSOR_WIDTH_MM, Camera, look_rotation

#: Name of the camera object (it is not a machine entity, so the name cannot clash).
CAMERA_NAME = "rube_camera"
#: Directory (inside ``out``) and file name pattern of the stills; the frame number is 4-digit.
FRAMES_DIR = "frames"
VIDEO_NAME = "video.mp4"


def frame_name(frame: int) -> str:
    """File name of the still for ``frame``: ``f_0049.png``."""
    return f"f_{frame:04d}.png"


def add_camera(scene: bpy.types.Scene, spec: Camera) -> bpy.types.Object:
    """Create the machine's camera and make it the scene camera (design D-8, D-12).

    ``static``: fixed location, rotation from ``look_rotation`` (level horizon, aimed at
    ``look_at``). ``follow``: ``COPY_LOCATION`` of the target with ``use_offset`` (so the
    camera's own location is the world-axis ``offset``) plus ``TRACK_TO`` the target. The
    camera is never parented to the body: a parent would pass the ball's spin on to the
    camera (SPEC section 7). Constraints read the baked motion at every frame.

    Args:
        scene: Target scene; the target entity's object must already exist in it.
        spec: Resolved camera (``Machine.camera`` after ``from_dict`` is never ``None``).

    Returns:
        The camera object (also ``scene.camera``).
    """
    data = bpy.data.cameras.new(CAMERA_NAME)
    data.lens = spec.lens_mm
    data.sensor_width = SENSOR_WIDTH_MM
    data.sensor_fit = "AUTO"  # the 36 mm sensor spans the longer (horizontal) side
    obj = bpy.data.objects.new(CAMERA_NAME, data)
    scene.collection.objects.link(obj)
    if spec.mode == "follow":
        obj.location = tuple(spec.offset)
        target = bpy.data.objects[spec.target.label]
        copy = obj.constraints.new("COPY_LOCATION")
        copy.target = target
        copy.use_offset = True
        track = obj.constraints.new("TRACK_TO")
        track.target = target
        track.track_axis = "TRACK_NEGATIVE_Z"  # cameras look along -Z
        track.up_axis = "UP_Y"
    else:
        matrix = Matrix(look_rotation(spec.position, spec.look_at)).to_4x4()
        matrix.translation = tuple(spec.position)
        obj.matrix_world = matrix
    scene.camera = obj
    return obj


def configure_render(scene: bpy.types.Scene) -> None:
    """Workbench engine, solid shading with object colors, 960x540 at 100 %."""
    render = scene.render
    render.engine = "BLENDER_WORKBENCH"
    render.resolution_x, render.resolution_y = RESOLUTION
    render.resolution_percentage = 100
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "OBJECT"  # use obj.color set by the builders


def render_stills(scene: bpy.types.Scene, frames: list[int], out_dir: Path) -> list[str]:
    """Render one PNG per frame into ``out_dir/frames/``.

    Args:
        scene: Scene with a baked rigid body cache and a camera.
        frames: Frame numbers to render.
        out_dir: Absolute output directory (``frames/`` is created).

    Returns:
        Paths relative to ``out_dir`` (``"frames/f_0001.png"``), in ``frames`` order.
    """
    (out_dir / FRAMES_DIR).mkdir(parents=True, exist_ok=True)
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    relative = []
    for frame in frames:
        path = out_dir / FRAMES_DIR / frame_name(frame)
        scene.frame_set(frame)  # evaluates the baked cache and the camera constraints
        scene.render.filepath = str(path)
        with bpy.context.temp_override(scene=scene):
            bpy.ops.render.render(write_still=True)
        relative.append(f"{FRAMES_DIR}/{path.name}")
    return relative


def render_video(scene: bpy.types.Scene, out_dir: Path) -> str:
    """Render the full frame range as an H.264 MP4 to ``out_dir/video.mp4``.

    Returns:
        The relative path ``"video.mp4"``.
    """
    image = scene.render.image_settings
    # Blender 5: the media type must be VIDEO before FFMPEG is an allowed file format.
    image.media_type = "VIDEO"
    image.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.filepath = str(out_dir / VIDEO_NAME)
    with bpy.context.temp_override(scene=scene):
        bpy.ops.render.render(animation=True)
    return VIDEO_NAME


def save_blend(scene: bpy.types.Scene, path: Path) -> None:
    """Save the current file (including the baked rigid body cache) to ``path``.

    Args:
        scene: Scene to save (used as the operator context).
        path: Absolute ``.blend`` path; overwritten if it exists.
    """
    with bpy.context.temp_override(scene=scene):
        bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
