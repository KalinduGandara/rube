"""Output files inside Blender: the ``.blend`` save (stills / video arrive in milestone M4).

Layer 3 (runs inside Blender; imports ``bpy``). Paths are always absolute: ``//relative``
output paths fail when no ``.blend`` has been saved (SPEC section 1.1).

Implements: FR-024 (``machine.blend`` part; rendering is T-014).
"""

from __future__ import annotations

from pathlib import Path

import bpy


def save_blend(scene: bpy.types.Scene, path: Path) -> None:
    """Save the current file (including the baked rigid body cache) to ``path``.

    Args:
        scene: Scene to save (used as the operator context).
        path: Absolute ``.blend`` path; overwritten if it exists.
    """
    with bpy.context.temp_override(scene=scene):
        bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
