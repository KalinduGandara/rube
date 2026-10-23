"""Camera specs and default auto-framing.

Layer 1 (pure Python, never imports ``bpy``). Exactly one camera per machine (SPEC section 7):

- ``Camera.static(position, look_at)`` -- fixed camera aimed at a point.
- ``Camera.follow(target, offset)`` -- Layer 3 gives the camera ``COPY_LOCATION`` (target,
  with offset) + ``TRACK_TO`` (target). It is **never parented** to the rigid body, which
  would make the camera inherit the ball's spin (design D-8).
- No camera set: ``auto_frame`` computes a static 3/4 elevated view containing every
  non-floor entity; ``Machine.to_dict`` stores that concrete camera (design D-12).

Projection model shared with Layer 3: Blender camera, sensor width 36 mm, sensor fit AUTO
(the sensor width spans the longer image side), resolution 960 x 540.

Implements: FR-014.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from rube.entities import Entity, check_number, check_vec, coerce_vec, jsonable
from rube.errors import Issue, error
from rube.geometry import AABB, aabb_union
from rube.vec import Mat3, Vec3

#: Preview render resolution (width, height) in pixels (SPEC section 8.8).
RESOLUTION = (960, 540)
#: Blender's default camera sensor width, mm.
SENSOR_WIDTH_MM = 36.0
#: Allowed focal lengths, mm.
LENS_RANGE = (5.0, 300.0)
#: Auto-frame view direction (from the target toward the camera): 3/4 elevated view.
AUTO_DIRECTION = Vec3(-1.0, -1.0, 0.7)
#: Auto-frame: minimum framed radius (m) and extra margin factor.
AUTO_MIN_RADIUS = 1.0
AUTO_MARGIN = 1.1

_WHO = "camera"


@dataclass(eq=False)
class Camera:
    """The machine's camera. Create it with ``Camera.static`` or ``Camera.follow``.

    Attributes:
        mode: ``"static"`` or ``"follow"``.
        position: Static: camera location (m).
        look_at: Static: point the camera aims at (m).
        target: Follow: the entity to follow.
        offset: Follow: camera position relative to the target (m), constant in world axes.
        lens_mm: Focal length in mm (35 = moderate wide angle).
    """

    mode: str
    position: Vec3 | None = None
    look_at: Vec3 | None = None
    target: Entity | None = None
    offset: Vec3 | None = None
    lens_mm: float = 35

    @classmethod
    def static(cls, position: Any, look_at: Any, lens_mm: float = 35) -> Camera:
        """Fixed camera at ``position`` aimed at ``look_at`` (both (x, y, z) in meters)."""
        return cls(
            "static", position=coerce_vec(position), look_at=coerce_vec(look_at), lens_mm=lens_mm
        )

    @classmethod
    def follow(cls, target: Entity, offset: Any = (-3, -3, 2), lens_mm: float = 35) -> Camera:
        """Camera that keeps ``offset`` (m, world axes) from ``target`` and aims at it."""
        return cls("follow", target=target, offset=coerce_vec(offset), lens_mm=lens_mm)

    def validate(self) -> list[Issue]:
        """Problems in the camera's own arguments (entity ``"camera"``). Never raises.

        Whether a follow target is part of the machine is checked by ``Machine.validate``.
        """
        issues: list[Issue] = []
        check_number(
            issues, _WHO, "lens_mm", self.lens_mm, lo=LENS_RANGE[0], hi=LENS_RANGE[1],
            unit=" mm", hint="use lens_mm between 18 and 85 (35 is a good default)",
        )  # fmt: skip
        if self.mode == "static":
            check_vec(issues, _WHO, "position", self.position)
            check_vec(issues, _WHO, "look_at", self.look_at)
            if (
                isinstance(self.position, Vec3)
                and isinstance(self.look_at, Vec3)
                and (self.position - self.look_at).length() == 0
            ):
                issues.append(
                    error(
                        "INVALID_ARGUMENT",
                        _WHO,
                        f"position and look_at are the same point {tuple(self.position)}",
                        "place the camera a few meters away from what it looks at",
                    )
                )
        elif self.mode == "follow":
            if not isinstance(self.target, Entity):
                issues.append(
                    error(
                        "INVALID_ARGUMENT",
                        _WHO,
                        f"follow target must be an entity, got {self.target!r}",
                        "pass the entity object, e.g. Camera.follow(ball)",
                    )
                )
            check_vec(issues, _WHO, "offset", self.offset)
            if isinstance(self.offset, Vec3) and self.offset.length() == 0:
                issues.append(
                    error(
                        "INVALID_ARGUMENT",
                        _WHO,
                        "offset is (0, 0, 0): the camera would sit inside the target",
                        "use an offset such as (-3, -3, 2)",
                    )
                )
        else:
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    _WHO,
                    f"unknown camera mode {self.mode!r}",
                    "create cameras with Camera.static(...) or Camera.follow(...)",
                )
            )
        return issues

    def to_dict(self) -> dict:
        """JSON-safe record; a follow target is referenced by entity name."""
        if self.mode == "follow":
            return {
                "mode": "follow",
                "target": self.target.label,
                "offset": jsonable(self.offset),
                "lens_mm": self.lens_mm,
            }
        return {
            "mode": self.mode,
            "position": jsonable(self.position),
            "look_at": jsonable(self.look_at),
            "lens_mm": self.lens_mm,
        }

    @classmethod
    def from_dict(cls, d: dict, entities_by_name: dict[str, Entity]) -> Camera:
        """Inverse of ``to_dict``; ``entities_by_name`` resolves a follow target."""
        if d["mode"] == "follow":
            return cls.follow(entities_by_name[d["target"]], d["offset"], d["lens_mm"])
        return cls.static(d["position"], d["look_at"], d["lens_mm"])


def fov_tangents(lens_mm: float) -> tuple[float, float]:
    """``(tan(horizontal_fov/2), tan(vertical_fov/2))`` for the 960x540 preview."""
    tan_h = (SENSOR_WIDTH_MM / 2) / lens_mm
    return tan_h, tan_h * RESOLUTION[1] / RESOLUTION[0]


def look_rotation(position: Vec3, target: Vec3) -> Mat3:
    """World rotation of a Blender camera at ``position`` looking at ``target``.

    Blender cameras look along their local -Z with local +Y up; this returns the matrix
    whose columns are the camera's local X (right), Y (up) and Z (backward) in world space,
    keeping the image horizon level (right vector horizontal).
    """
    forward = (target - position).normalized()
    world_up = Vec3(0.0, 0.0, 1.0)
    right = forward.cross(world_up)
    if right.length() < 1e-9:  # looking straight up/down: any horizontal right works
        right = forward.cross(Vec3(0.0, 1.0, 0.0))
    right = right.normalized()
    up = right.cross(forward)
    back = -forward
    return (
        (right.x, up.x, back.x),
        (right.y, up.y, back.y),
        (right.z, up.z, back.z),
    )


def auto_frame(boxes: list[AABB], lens_mm: float = 35) -> Camera:
    """Static camera that frames the union of ``boxes`` from a 3/4 elevated view.

    The camera looks at the box center from direction ``AUTO_DIRECTION``. Why the distance
    ``r / sin(fov_v / 2) * 1.1``: a sphere of radius ``r`` (half the box diagonal, at least
    1 m) seen from that distance fits inside the narrower (vertical) field of view, so the
    whole box is in frame for any view direction.

    Args:
        boxes: World AABBs to frame (non-floor entities). Empty = a 2 x 2 x 1 m box at origin.
        lens_mm: Focal length.

    Returns:
        A ``Camera`` in ``static`` mode.
    """
    if boxes:
        lo, hi = aabb_union(boxes)
    else:
        lo, hi = Vec3(-1.0, -1.0, 0.0), Vec3(1.0, 1.0, 1.0)
    center = (lo + hi) / 2
    radius = max((hi - lo).length() / 2, AUTO_MIN_RADIUS)
    half_fov_v = math.atan(fov_tangents(lens_mm)[1])
    distance = radius / math.sin(half_fov_v) * AUTO_MARGIN
    return Camera.static(center + AUTO_DIRECTION.normalized() * distance, center, lens_mm)
