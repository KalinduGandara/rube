"""Rube: declarative Rube Goldberg machines simulated in Blender.

Layer 1 (public API). This module re-exports the public API only; it never imports
``bpy`` (NFR-001). See ``SPEC.md`` and ``specs/design.md`` for the architecture.

Author scripts use::

    from rube import Ball, Domino, Machine, Camera, Ramp, domino_chain, spiral_ramp

A later milestone adds ``Lever`` here.
"""

__version__ = "0.1.0"

from rube.camera import Camera  # noqa: E402 - __version__ first: rube.report imports it
from rube.entities import CLEARANCE, COLORS, Ball, Block, Domino, Floor, Ramp  # noqa: E402
from rube.errors import Issue, RubeValidationError  # noqa: E402
from rube.generators import DominoChain, SpiralRamp, domino_chain, spiral_ramp  # noqa: E402
from rube.machine import Machine  # noqa: E402
from rube.vec import Vec3  # noqa: E402

__all__ = [
    "CLEARANCE",
    "COLORS",
    "Ball",
    "Block",
    "Camera",
    "Domino",
    "DominoChain",
    "Floor",
    "Issue",
    "Machine",
    "Ramp",
    "RubeValidationError",
    "SpiralRamp",
    "Vec3",
    "__version__",
    "domino_chain",
    "spiral_ramp",
]
