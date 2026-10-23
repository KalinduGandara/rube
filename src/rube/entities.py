"""Entities: the declarative building blocks of a machine, plus their resolved build specs.

Layer 1 (pure Python, never imports ``bpy``). Entities are plain dataclasses with no Blender
code (SPEC section 3.1). Each one:

- stores its constructor arguments (positions coerced to ``Vec3`` when possible, design D-15),
- reports content problems from ``validate()`` as ``Issue`` values (never raises for them),
- exposes read-only **anchors** (``Vec3`` points) so authors can connect parts without
  trigonometry (SPEC section 5.2),
- resolves itself with ``body()`` to a ``BodySpec``: mesh vertices at true size, world
  transform as a 3x3 matrix, and every physics value Layer 2 needs (design D-2, D-4).

Physics defaults live in the single ``DEFAULTS`` table (SPEC section 5, assumption A-1): tune
values only there, only to pass acceptance tests, and log changes in ``specs/progress.md``.

Placement conventions (SPEC section 2): ``Ball.center`` is the sphere center; ``Block`` and
``Domino`` ``position`` is the **bottom-center** point on the supporting surface; ``Ramp``
``start``/``end`` are the top-surface centerline endpoints (``start`` high). Angles are
degrees; ``facing_deg`` is yaw about +Z with 0 = +X.

Later milestones add the internal ``SpiralTrack`` / ``SupportColumn`` /
``LeverPlank`` / ``Fulcrum`` and the ``Lever`` group here; concrete ``Entity`` subclasses
register themselves in ``ENTITY_TYPES`` automatically, so ``entity_from_dict`` needs no edits.

Implements: FR-004, FR-005, FR-006, FR-007, FR-008 (Ramp plank), FR-009 (Ramp rails),
FR-013 (entity-level checks), FR-020
(BodySpec / HingeSpec), FR-012 structure (Hinge, Group).
"""

from __future__ import annotations

import math
from dataclasses import KW_ONLY, dataclass, fields
from typing import Any, ClassVar

from rube.errors import Issue, RubeValidationError, error, has_errors
from rube.geometry import (
    AABB,
    MeshSpec,
    aabb,
    box_mesh,
    channel_mesh,
    recenter,
    transform_points,
    uv_sphere_mesh,
)
from rube.vec import (
    IDENTITY,
    Mat3,
    Vec3,
    as_vec3,
    is_number,
    mat_mul,
    mat_vec,
    rot_axis,
    rot_z,
    yaw_vector,
)

#: Gap (m) between a placed object and the surface below it, so nothing starts intersecting.
CLEARANCE = 0.002
#: Smallest allowed dimension (m); Bullet becomes unstable below this (SPEC section 9.1).
MIN_DIMENSION = 0.02
#: Floor slab thickness (m); its top face is z = 0.
FLOOR_THICKNESS = 0.2
#: Blender truncates object names longer than this many bytes; names must survive exactly.
MAX_NAME_BYTES = 63
#: Wall height (m) above the floor of a ``Ramp(rails=True)`` channel (same as the
#: ``spiral_ramp`` default ``wall_height``; SPEC gives no value, design D-24).
RAIL_HEIGHT = 0.08

#: Named preview colors (linear RGBA for Workbench object color).
COLORS: dict[str, tuple[float, float, float, float]] = {
    "red": (0.85, 0.10, 0.10, 1.0),
    "green": (0.15, 0.65, 0.20, 1.0),
    "blue": (0.15, 0.35, 0.85, 1.0),
    "yellow": (0.95, 0.80, 0.10, 1.0),
    "orange": (0.95, 0.50, 0.10, 1.0),
    "purple": (0.55, 0.25, 0.75, 1.0),
    "pink": (0.95, 0.50, 0.70, 1.0),
    "cyan": (0.10, 0.75, 0.85, 1.0),
    "white": (0.92, 0.92, 0.92, 1.0),
    "black": (0.08, 0.08, 0.08, 1.0),
    "gray": (0.50, 0.50, 0.50, 1.0),
    "brown": (0.50, 0.32, 0.18, 1.0),
    "wood": (0.72, 0.53, 0.33, 1.0),
}


@dataclass(frozen=True)
class PhysicsDefaults:
    """One row of ``DEFAULTS``: the per-class default physics values.

    Attributes:
        dynamic: ``True`` = falls/moves (Blender ``ACTIVE``), ``False`` = fixed (``PASSIVE``).
        mass: kg, or ``None`` to derive it from ``density`` x volume.
        density: kg/m^3, used only when ``mass`` is ``None``.
        friction: 0..1.
        bounciness: 0..1 (Blender ``restitution``).
        linear_damping: Blender ``linear_damping`` (Blender default 0.04).
        angular_damping: Blender ``angular_damping`` (Blender default 0.1).
        margin: Bullet ``collision_margin`` in meters (Blender default 0.04 is far too big).
        color: Default preview color name (key of ``COLORS``).
    """

    dynamic: bool
    mass: float | None
    density: float | None
    friction: float
    bounciness: float
    linear_damping: float
    angular_damping: float
    margin: float
    color: str


#: The single physics defaults table (SPEC section 5). Passive rows carry a placeholder mass
#: of 1.0 kg because Blender ignores mass for passive bodies. Keys are type names, except
#: ``RampRails`` (a ``Ramp`` with ``rails=True``: same values, MESH margin 0.005). Triangle
#: MESH shapes get the larger margin SPEC section 5 gives for the channel mesh.
DEFAULTS: dict[str, PhysicsDefaults] = {
    "Floor": PhysicsDefaults(False, 1.0, None, 0.6, 0.0, 0.04, 0.1, 0.001, "gray"),
    "Ball": PhysicsDefaults(True, 0.5, None, 0.4, 0.1, 0.04, 0.02, 0.001, "red"),
    "Block": PhysicsDefaults(True, None, 600.0, 0.5, 0.0, 0.04, 0.1, 0.001, "blue"),
    "Domino": PhysicsDefaults(True, None, 600.0, 0.5, 0.0, 0.04, 0.1, 0.001, "yellow"),
    "Ramp": PhysicsDefaults(False, 1.0, None, 0.3, 0.0, 0.04, 0.1, 0.001, "wood"),
    "RampRails": PhysicsDefaults(False, 1.0, None, 0.3, 0.0, 0.04, 0.1, 0.005, "wood"),
}


@dataclass(frozen=True)
class ResolvedPhysics:
    """Final physics values of one entity (author overrides merged onto ``DEFAULTS``)."""

    dynamic: bool
    mass: float
    friction: float
    bounciness: float
    linear_damping: float
    angular_damping: float
    margin: float
    color: str


@dataclass(frozen=True)
class BodySpec:
    """Everything Layer 2 needs to create one rigid body; Blender re-derives nothing.

    Attributes:
        name: Blender object name (= entity name).
        type: Public type name, e.g. ``"Domino"`` (stored as custom prop ``rube_type``).
        location: World position of the object origin (= center of volume), meters.
        rotation: 3x3 world rotation matrix, row-major (design D-4).
        mesh: Local-space mesh at true size; object scale stays (1, 1, 1).
        collision_shape: Blender shape: ``SPHERE``, ``BOX``, ``MESH`` or ``CONVEX_HULL``.
        dynamic: ``ACTIVE`` if True else ``PASSIVE``.
        mass: kg.
        friction: 0..1.
        restitution: 0..1 (author-facing name: ``bounciness``).
        linear_damping: Blender linear damping.
        angular_damping: Blender angular damping.
        margin: Bullet collision margin, meters (``use_margin`` is always on).
        use_deactivation: Blender ``use_deactivation``.
        start_deactivated: Blender ``use_start_deactivated``.
        color: RGBA preview color.
    """

    name: str
    type: str
    location: Vec3
    rotation: Mat3
    mesh: MeshSpec
    collision_shape: str
    dynamic: bool
    mass: float
    friction: float
    restitution: float
    linear_damping: float
    angular_damping: float
    margin: float
    use_deactivation: bool
    start_deactivated: bool
    color: tuple[float, float, float, float]

    def aabb(self) -> AABB:
        """World-space axis-aligned bounding box ``(min, max)``."""
        return aabb(transform_points(self.mesh.vertices, self.rotation, self.location))


@dataclass(frozen=True)
class HingeSpec:
    """Resolved hinge constraint for Layer 2 (design D-11).

    Attributes:
        name: Name of the Empty that carries the constraint.
        body_a: Name of the first body (e.g. a passive fulcrum).
        body_b: Name of the second body.
        pivot: World hinge point, meters.
        axis: Unit world hinge axis.
        disable_collisions: Bodies a and b do not collide with each other.
    """

    name: str
    body_a: str
    body_b: str
    pivot: Vec3
    axis: Vec3
    disable_collisions: bool


# --- validation helpers -------------------------------------------------------------------
# Shared by every Layer 1 spec module (entities, camera, generators): each appends issues to
# a list instead of raising, so validate() can report every problem at once (FR-013).


def _fmt(value: Any) -> str:
    """Compact number/value rendering for issue messages."""
    if is_number(value):
        return f"{value:g}"
    return repr(value)


def check_vec(issues: list[Issue], who: str, field: str, value: Any) -> None:
    """Report ``INVALID_ARGUMENT`` unless ``value`` was coerced to a ``Vec3``."""
    if not isinstance(value, Vec3):
        issues.append(
            error(
                "INVALID_ARGUMENT",
                who,
                f"{field} must be three numbers (x, y, z) in meters, got {value!r}",
                f"pass {field} as a tuple like (0.0, 0.0, 1.0)",
            )
        )


def check_number(
    issues: list[Issue],
    who: str,
    field: str,
    value: Any,
    *,
    lo: float | None = None,
    hi: float | None = None,
    lo_open: bool = False,
    hi_open: bool = False,
    unit: str = "",
    hint: str,
) -> bool:
    """Check a numeric argument and its range.

    Returns:
        True if ``value`` is a finite number within range (an issue is appended otherwise).
    """
    if not is_number(value):
        issues.append(
            error(
                "INVALID_ARGUMENT",
                who,
                f"{field} must be a number, got {value!r}",
                hint,
            )
        )
        return False
    below = lo is not None and (value <= lo if lo_open else value < lo)
    above = hi is not None and (value >= hi if hi_open else value > hi)
    if below or above:
        lo_txt = "" if lo is None else f"{'>' if lo_open else '>='} {lo:g}"
        hi_txt = "" if hi is None else f"{'<' if hi_open else '<='} {hi:g}"
        rule = " and ".join(t for t in (lo_txt, hi_txt) if t)
        issues.append(
            error(
                "OUT_OF_RANGE",
                who,
                f"{field} is {_fmt(value)}{unit}; it must be {rule}",
                hint,
            )
        )
        return False
    return True


def check_dimension(issues: list[Issue], who: str, field: str, value: Any, example: float) -> None:
    """A length in meters: must be > 0 (``OUT_OF_RANGE``) and >= MIN_DIMENSION (``TOO_SMALL``)."""
    hint = f"use a positive {field} such as {example:g} m"
    if not check_number(issues, who, field, value, lo=0.0, lo_open=True, unit=" m", hint=hint):
        return
    if value < MIN_DIMENSION:
        issues.append(
            error(
                "TOO_SMALL",
                who,
                f"{field} is {_fmt(value)} m, below the {MIN_DIMENSION:g} m minimum "
                "(Bullet is unstable for tiny bodies)",
                f"make {field} at least {MIN_DIMENSION:g} m",
            )
        )


def check_size3(
    issues: list[Issue],
    who: str,
    field: str,
    value: Any,
    axes: tuple[str, str, str],
    example: tuple,
) -> None:
    """A 3-tuple of lengths in meters (each checked like ``check_dimension``)."""
    if not (isinstance(value, tuple) and len(value) == 3 and all(is_number(v) for v in value)):
        issues.append(
            error(
                "INVALID_ARGUMENT",
                who,
                f"{field} must be three numbers {axes} in meters, got {value!r}",
                f"pass {field} as a tuple like {example}",
            )
        )
        return
    for axis, v in zip(axes, value, strict=True):
        check_dimension(issues, who, f"{field} {axis}", v, example[axes.index(axis)])


def coerce_vec(value: Any) -> Any:
    """``Vec3`` if coercible, else the raw value (``validate()`` reports it, design D-15)."""
    try:
        return as_vec3(value)
    except (TypeError, ValueError):
        return value


def coerce_size(value: Any) -> Any:
    """Float 3-tuple if coercible (lists from JSON become tuples), else the raw value."""
    try:
        return tuple(as_vec3(value))
    except (TypeError, ValueError):
        return value


def jsonable(value: Any) -> Any:
    """Convert stored argument values to JSON-safe data (Vec3/tuple -> list)."""
    if isinstance(value, Vec3):
        return value.to_list()
    if isinstance(value, (tuple, list)):
        return [jsonable(v) for v in value]
    return value


# --- entities ---------------------------------------------------------------------------

#: Type name -> concrete Entity class, filled automatically; used by ``entity_from_dict``.
ENTITY_TYPES: dict[str, type[Entity]] = {}


@dataclass(eq=False)
class PhysicsProps:
    """Author-facing physics fields shared by every entity (keyword-only, SPEC section 5).

    ``None`` means "use the class default from ``DEFAULTS``".

    Attributes:
        dynamic: Falls/moves (True) or stays fixed (False).
        mass: kg; ignored when not dynamic.
        friction: 0..1.
        bounciness: 0..1.
        color: Preview color name, one of ``COLORS``.
    """

    _: KW_ONLY
    dynamic: bool | None = None
    mass: float | None = None
    friction: float | None = None
    bounciness: float | None = None
    color: str | None = None


@dataclass(eq=False)
class Entity(PhysicsProps):
    """Base class of every rigid body. Not used directly.

    Attributes:
        name: Unique name (keyword-only). ``None`` = auto ``<Type>_<n>`` when added to a
            ``Machine``. The Blender object gets exactly this name.

    Subclasses set ``COLLISION_SHAPE`` and implement ``_geometry_issues``, ``_pose``,
    ``_mesh`` and (for density-based mass) ``_volume``. Equality is identity (``eq=False``)
    because entities are mutable objects referenced by machines and hinges.
    """

    _: KW_ONLY
    name: str | None = None

    COLLISION_SHAPE: ClassVar[str] = "BOX"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.__name__.startswith("_"):
            ENTITY_TYPES[cls.__name__] = cls

    # -- identity -----------------------------------------------------------------------

    @classmethod
    def type_name(cls) -> str:
        """Public type name used in names, reports and ``spec.json`` (e.g. ``"Domino"``)."""
        return cls.__name__

    @property
    def label(self) -> str:
        """Name for messages: the entity name, or its type name before it is named."""
        return self.name if isinstance(self.name, str) and self.name else self.type_name()

    # -- validation ---------------------------------------------------------------------

    def validate(self) -> list[Issue]:
        """All content problems of this entity (geometry, then physics). Never raises."""
        return self._geometry_issues() + self._physics_issues()

    def _geometry_issues(self) -> list[Issue]:
        """Problems that make anchors/geometry unusable. Overridden by subclasses."""
        return []

    def _physics_issues(self) -> list[Issue]:
        """Problems in name and the common physics fields."""
        issues: list[Issue] = []
        who = self.label
        if self.name is not None:
            if not isinstance(self.name, str) or not self.name.strip():
                issues.append(
                    error(
                        "INVALID_ARGUMENT",
                        who,
                        f"name must be a non-empty string, got {self.name!r}",
                        "omit name to get an automatic one, or pass e.g. name='ball_1'",
                    )
                )
            elif len(self.name.encode("utf-8")) > MAX_NAME_BYTES:
                issues.append(
                    error(
                        "INVALID_ARGUMENT",
                        who,
                        f"name is {len(self.name.encode('utf-8'))} bytes long; Blender keeps "
                        f"at most {MAX_NAME_BYTES}",
                        f"shorten the name to at most {MAX_NAME_BYTES} characters",
                    )
                )
        if self.dynamic is not None and not isinstance(self.dynamic, bool):
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    who,
                    f"dynamic must be True or False, got {self.dynamic!r}",
                    "use dynamic=True (moves) or dynamic=False (fixed)",
                )
            )
        if self.mass is not None:
            check_number(
                issues, who, "mass", self.mass, lo=0.0, lo_open=True, unit=" kg",
                hint="use a positive mass in kg, e.g. mass=0.5",
            )  # fmt: skip
        for field in ("friction", "bounciness"):
            value = getattr(self, field)
            if value is not None:
                check_number(
                    issues, who, field, value, lo=0.0, hi=1.0,
                    hint=f"use {field} between 0 and 1",
                )  # fmt: skip
        if self.color is not None and self.color not in COLORS:
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    who,
                    f"unknown color {self.color!r}",
                    f"use one of: {', '.join(COLORS)}",
                )
            )
        return issues

    def _require_geometry(self) -> None:
        """Raise ``RubeValidationError`` if geometry arguments are unusable (for anchors)."""
        issues = self._geometry_issues()
        if has_errors(issues):
            raise RubeValidationError(issues)

    # -- physics & build spec -----------------------------------------------------------

    def resolved_physics(self) -> ResolvedPhysics:
        """Author overrides merged onto ``DEFAULTS[type]``; mass derived from density if unset."""
        row = DEFAULTS[self._defaults_key()]
        mass = self.mass
        if mass is None:
            mass = row.mass if row.mass is not None else row.density * self._volume()
        return ResolvedPhysics(
            dynamic=row.dynamic if self.dynamic is None else self.dynamic,
            mass=float(mass),
            friction=row.friction if self.friction is None else self.friction,
            bounciness=row.bounciness if self.bounciness is None else self.bounciness,
            linear_damping=row.linear_damping,
            angular_damping=row.angular_damping,
            margin=row.margin,
            color=row.color if self.color is None else self.color,
        )

    def body(self) -> BodySpec:
        """Resolve to the ``BodySpec`` Layer 2 builds.

        Raises:
            RubeValidationError: if ``validate()`` reports errors.
        """
        issues = self.validate()
        if has_errors(issues):
            raise RubeValidationError(issues)
        phys = self.resolved_physics()
        center, rotation = self._pose()
        use_deactivation, start_deactivated = self._deactivation()
        return BodySpec(
            name=self.label,
            type=self.type_name(),
            location=center + Vec3(0.0, 0.0, self._lift()),
            rotation=rotation,
            mesh=self._mesh(),
            collision_shape=self._collision_shape(),
            dynamic=phys.dynamic,
            mass=phys.mass,
            friction=float(phys.friction),
            restitution=float(phys.bounciness),
            linear_damping=phys.linear_damping,
            angular_damping=phys.angular_damping,
            margin=phys.margin,
            use_deactivation=use_deactivation,
            start_deactivated=start_deactivated,
            color=COLORS[phys.color],
        )

    def _defaults_key(self) -> str:
        """Row of ``DEFAULTS`` to use; the type name unless a variant has its own row."""
        return self.type_name()

    def _collision_shape(self) -> str:
        """Bullet collision shape; ``COLLISION_SHAPE`` unless the shape depends on arguments."""
        return self.COLLISION_SHAPE

    def _pose(self) -> tuple[Vec3, Mat3]:
        """Resting pose: world center of volume and rotation matrix. Subclasses implement."""
        raise NotImplementedError

    def _mesh(self) -> MeshSpec:
        """Local mesh at true size around the center of volume. Subclasses implement."""
        raise NotImplementedError

    def _volume(self) -> float:
        """Volume in m^3 for density-based mass. Subclasses with a density default implement."""
        raise NotImplementedError

    def _lift(self) -> float:
        """Extra z offset applied in ``body()`` on top of the resting pose (design D-14)."""
        return 0.0

    def _deactivation(self) -> tuple[bool, bool]:
        """``(use_deactivation, start_deactivated)``; off by default."""
        return (False, False)

    # -- serialization ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """JSON-safe record of the constructor arguments (unset physics stay ``None``)."""
        d: dict[str, Any] = {"type": self.type_name(), "name": self.name}
        for f in fields(self):
            if f.name != "name":
                d[f.name] = jsonable(getattr(self, f.name))
        return d


def entity_from_dict(d: dict) -> Entity:
    """Rebuild an entity from ``Entity.to_dict()`` output via ``ENTITY_TYPES``.

    Raises:
        ValueError: unknown ``type`` (``spec.json`` is machine-generated, so this is a bug).
    """
    cls = ENTITY_TYPES.get(d.get("type"))
    if cls is None:
        raise ValueError(f"unknown entity type {d.get('type')!r}; known: {sorted(ENTITY_TYPES)}")
    return cls(**{k: v for k, v in d.items() if k != "type"})


@dataclass(eq=False)
class Floor(Entity):
    """Passive ground slab ``size x size x 0.2`` m centered on the origin, top face at z = 0.

    ``Machine(floor=True)`` adds one automatically.

    Args:
        size: Edge length in meters.
    """

    size: float = 20.0

    def _geometry_issues(self) -> list[Issue]:
        issues: list[Issue] = []
        check_dimension(issues, self.label, "size", self.size, 20.0)
        return issues

    @property
    def half_size(self) -> float:
        """Half the edge length: the floor covers ``|x|, |y| <= half_size``."""
        self._require_geometry()
        return self.size / 2

    def _pose(self) -> tuple[Vec3, Mat3]:
        return Vec3(0.0, 0.0, -FLOOR_THICKNESS / 2), IDENTITY

    def _mesh(self) -> MeshSpec:
        return box_mesh(self.size, self.size, FLOOR_THICKNESS)


@dataclass(eq=False)
class Ball(Entity):
    """Dynamic sphere (UV sphere 32x16, collision ``SPHERE``).

    Args:
        center: Sphere center (x, y, z) in meters.
        radius: Meters (default 0.1).

    Anchors:
        bottom: Lowest point of the sphere.
    """

    center: Vec3
    radius: float = 0.1

    COLLISION_SHAPE: ClassVar[str] = "SPHERE"

    def __post_init__(self) -> None:
        self.center = coerce_vec(self.center)

    def _geometry_issues(self) -> list[Issue]:
        issues: list[Issue] = []
        check_vec(issues, self.label, "center", self.center)
        hint = "use a positive radius such as 0.1 m"
        r = self.radius
        if check_number(
            issues, self.label, "radius", r, lo=0.0, lo_open=True, unit=" m", hint=hint
        ):
            # The ball's physical dimension is its diameter.
            if 2 * r < MIN_DIMENSION:
                issues.append(
                    error(
                        "TOO_SMALL",
                        self.label,
                        f"diameter is {_fmt(2 * r)} m (radius {_fmt(r)} m), below the "
                        f"{MIN_DIMENSION:g} m minimum",
                        f"use radius >= {MIN_DIMENSION / 2:g} m",
                    )
                )
        return issues

    @property
    def bottom(self) -> Vec3:
        """Lowest point of the sphere (``center - (0, 0, radius)``)."""
        self._require_geometry()
        return self.center - Vec3(0.0, 0.0, self.radius)

    def _pose(self) -> tuple[Vec3, Mat3]:
        return self.center, IDENTITY

    def _mesh(self) -> MeshSpec:
        return uv_sphere_mesh(self.radius)


@dataclass(eq=False)
class _BottomPlacedBox(Entity):
    """Shared logic of boxes placed by their bottom-center that can tilt toward ``facing_deg``.

    Local frame: +X = facing direction, Y = width, Z = up. The tilt rotates the box by
    ``_tilt_deg()`` about its bottom front edge (the edge on the facing side), which stays
    on the support plane. Underscore name: not registered as a public entity type.
    """

    def __post_init__(self) -> None:
        self.position = coerce_vec(self.position)
        self.size = coerce_size(self.size)

    def _tilt_deg(self) -> float:
        return 0.0

    def _box_geometry_issues(self, axes: tuple[str, str, str], example: tuple) -> list[Issue]:
        issues: list[Issue] = []
        check_vec(issues, self.label, "position", self.position)
        check_size3(issues, self.label, "size", self.size, axes, example)
        check_number(
            issues, self.label, "facing_deg", self.facing_deg,
            hint="use an angle in degrees, e.g. facing_deg=90 to face +Y",
        )  # fmt: skip
        return issues

    def _pose(self) -> tuple[Vec3, Mat3]:
        sx, _, sz = self.size
        facing = yaw_vector(self.facing_deg)
        yaw = rot_z(self.facing_deg)
        upright_center = self.position + Vec3(0.0, 0.0, sz / 2)
        tilt = self._tilt_deg()
        if tilt == 0:
            return upright_center, yaw
        # Rotating about axis z x f moves +Z toward f (right-hand rule): the box leans
        # toward facing_deg while pivoting on its bottom front edge.
        pivot = self.position + facing * (sx / 2)
        tilt_r = rot_axis(Vec3(0.0, 0.0, 1.0).cross(facing), tilt)
        return pivot + mat_vec(tilt_r, upright_center - pivot), mat_mul(tilt_r, yaw)

    def _mesh(self) -> MeshSpec:
        return box_mesh(*self.size)

    def _volume(self) -> float:
        sx, sy, sz = self.size
        return sx * sy * sz

    def _lift(self) -> float:
        # Start 2 mm above the support so frame 1 has no contact/overlap (design D-14).
        return CLEARANCE

    @property
    def top_center(self) -> Vec3:
        """Center of the top face in the resting pose (follows tilt)."""
        self._require_geometry()
        center, rotation = self._pose()
        return center + mat_vec(rotation, Vec3(0.0, 0.0, self.size[2] / 2))

    @property
    def front(self) -> Vec3:
        """Bottom point on the facing side (center of the bottom front edge)."""
        self._require_geometry()
        return self.position + yaw_vector(self.facing_deg) * (self.size[0] / 2)


@dataclass(eq=False)
class Block(_BottomPlacedBox):
    """Box (collision ``BOX``), dynamic by default, mass from density 600 kg/m^3.

    Args:
        position: Bottom-center point (x, y, z) on the supporting surface, meters.
        size: ``(x, y, z)`` edge lengths in meters in the block's own frame (default 0.2 cube).
        facing_deg: Yaw in degrees; the block's local +X points this way.

    Anchors:
        top_center: Center of the top face.
        front: Bottom point on the +facing side.
    """

    position: Vec3
    size: tuple[float, float, float] = (0.2, 0.2, 0.2)
    facing_deg: float = 0.0

    def _geometry_issues(self) -> list[Issue]:
        return self._box_geometry_issues(("x", "y", "z"), (0.2, 0.2, 0.2))


@dataclass(eq=False)
class Domino(_BottomPlacedBox):
    """Domino (collision ``BOX``) that falls toward ``facing_deg``.

    Args:
        position: Bottom-center point (x, y, z) on the supporting surface, meters.
        facing_deg: Direction it falls toward, degrees (0 = +X).
        tilt_deg: Pre-tilt toward ``facing_deg`` about the bottom front edge, in [0, 90).
            A tilted domino starts active and falls on its own: the v1 way to start a chain.
        size: ``(thickness, width, height)`` in meters.

    Anchors:
        top_center: Center of the top face (follows tilt).
        front: Center of the bottom front edge (the tilt pivot).
    """

    position: Vec3
    facing_deg: float = 0.0
    tilt_deg: float = 0.0
    size: tuple[float, float, float] = (0.1, 0.4, 0.8)

    def _geometry_issues(self) -> list[Issue]:
        issues = self._box_geometry_issues(("thickness", "width", "height"), (0.1, 0.4, 0.8))
        check_number(
            issues, self.label, "tilt_deg", self.tilt_deg, lo=0.0, hi=90.0, hi_open=True,
            unit=" deg", hint="use tilt_deg between 0 and 90 (10 is enough to start a chain); "
            "to lean the other way, add 180 to facing_deg",
        )  # fmt: skip
        return issues

    def _tilt_deg(self) -> float:
        return float(self.tilt_deg)

    def _deactivation(self) -> tuple[bool, bool]:
        # Start deactivated so long chains do not jitter before being hit (SPEC 5.1) --
        # except a tilted domino: a start-deactivated body ignores gravity until struck.
        return (True, self.tilt_deg == 0)


@dataclass(eq=False)
class Ramp(Entity):
    """Straight inclined plank (passive, collision ``BOX``) for balls to roll down.

    ``start`` and ``end`` are the endpoints of the **top surface centerline**; ``start`` is the
    high end. The plank hangs below that line by ``thickness`` and is level across its width.
    With ``rails=True`` it is a U-channel instead (``geometry.channel_mesh`` along the straight
    start -> end path, collision ``MESH``, margin 0.005, FR-009): the floor's top centerline
    is still start -> end, the groove is ``width`` wide, and walls ``thickness`` thick rise
    ``RAIL_HEIGHT`` (0.08 m) above the floor outside the groove, so balls cannot fall off.

    Args:
        start: High end of the top-surface centerline (x, y, z), meters.
        end: Low end of the top-surface centerline (x, y, z), meters. Tip: ``end.z = 0`` lets
            the top surface meet the floor so a ball rolls off smoothly (the plank may dip
            into the floor; passive bodies never collide with each other).
        width: Plank width across the slope, meters.
        thickness: Plank thickness, meters.
        rails: ``True`` = U-channel with side walls (keeps a ball on the ramp).

    Anchors:
        top: ``start``. bottom: ``end``.
        direction: Unit vector pointing downhill along the surface (3D).
        slope_deg: Inclination in degrees (0 = level).
        ball_spawn(radius): Where to put a ball's center so it starts rolling from the top.
        exit(distance): Ground point (z = 0) ``distance`` m beyond the bottom end.

    Local frame of the plank: +X = ``direction`` (downhill), +Y = horizontal across the
    plank, +Z = surface normal pointing up out of the top face.
    """

    start: Vec3
    end: Vec3
    width: float = 0.4
    thickness: float = 0.05
    rails: bool = False

    def __post_init__(self) -> None:
        self.start = coerce_vec(self.start)
        self.end = coerce_vec(self.end)

    def _geometry_issues(self) -> list[Issue]:
        issues: list[Issue] = []
        who = self.label
        check_vec(issues, who, "start", self.start)
        check_vec(issues, who, "end", self.end)
        check_dimension(issues, who, "width", self.width, 0.4)
        check_dimension(issues, who, "thickness", self.thickness, 0.05)
        if not isinstance(self.rails, bool):
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    who,
                    f"rails must be True or False, got {self.rails!r}",
                    "use rails=True for side walls or rails=False for a plain plank",
                )
            )
        if isinstance(self.start, Vec3) and isinstance(self.end, Vec3):
            run = _horizontal(self.end - self.start).length()
            if self.start.z <= self.end.z:
                issues.append(
                    error(
                        "INVALID_ARGUMENT",
                        who,
                        f"start z ({self.start.z:g}) must be higher than end z "
                        f"({self.end.z:g}); start is the high end of the ramp",
                        "swap start and end",
                    )
                )
            elif run < MIN_DIMENSION:
                issues.append(
                    error(
                        "INVALID_ARGUMENT",
                        who,
                        f"start and end are only {run:g} m apart horizontally; a ramp cannot "
                        "be vertical",
                        "move end sideways, e.g. a 20 deg ramp dropping 0.7 m needs ~2 m of "
                        "horizontal run",
                    )
                )
        return issues

    # -- frame --------------------------------------------------------------------------

    def _frame(self) -> tuple[Vec3, Vec3, Vec3]:
        """``(direction, side, normal)``: right-handed unit axes of the plank (local X, Y, Z)."""
        direction = (self.end - self.start).normalized()
        side = Vec3(0.0, 0.0, 1.0).cross(_horizontal(direction)).normalized()
        return direction, side, direction.cross(side)

    def _defaults_key(self) -> str:
        return "RampRails" if self.rails is True else "Ramp"

    def _collision_shape(self) -> str:
        # The U-channel is concave, so only a triangle MESH shape keeps the groove open.
        return "MESH" if self.rails is True else "BOX"

    def _channel(self) -> tuple[MeshSpec, Vec3]:
        """Rails variant: centered channel mesh and its world center of volume."""
        return recenter(
            channel_mesh([self.start, self.end], self.width, RAIL_HEIGHT, self.thickness)
        )

    def _pose(self) -> tuple[Vec3, Mat3]:
        if self.rails is True:
            # The channel mesh is generated in world axes, so only a translation is needed.
            return self._channel()[1], IDENTITY
        direction, side, normal = self._frame()
        # Columns of the rotation matrix are the local axes expressed in world space.
        rotation = tuple(zip(direction, side, normal, strict=True))
        # The box center sits half a thickness below the midpoint of the top centerline.
        center = (self.start + self.end) / 2 - normal * (self.thickness / 2)
        return center, rotation  # type: ignore[return-value]

    def _mesh(self) -> MeshSpec:
        if self.rails is True:
            return self._channel()[0]
        return box_mesh((self.end - self.start).length(), self.width, self.thickness)

    def _volume(self) -> float:
        return (self.end - self.start).length() * self.width * self.thickness

    # -- anchors ------------------------------------------------------------------------

    @property
    def top(self) -> Vec3:
        """High end of the top-surface centerline (= ``start``)."""
        self._require_geometry()
        return self.start

    @property
    def bottom(self) -> Vec3:
        """Low end of the top-surface centerline (= ``end``)."""
        self._require_geometry()
        return self.end

    @property
    def direction(self) -> Vec3:
        """Unit vector pointing downhill along the top surface (has a negative z)."""
        self._require_geometry()
        return self._frame()[0]

    @property
    def slope_deg(self) -> float:
        """Inclination of the ramp in degrees (0 = level, 90 = vertical)."""
        self._require_geometry()
        drop = self.start.z - self.end.z
        return math.degrees(math.atan2(drop, _horizontal(self.end - self.start).length()))

    def ball_spawn(self, radius: float = 0.1) -> Vec3:
        """Center for a ball of ``radius`` m that starts rolling from the top of the ramp.

        The center is ``1.5 * radius`` downhill from the top edge (along the surface) and
        ``radius + CLEARANCE`` above the surface along its normal, so the ball starts just
        clear of the plank (no frame-1 overlap) on any slope.

        Raises:
            RubeValidationError: invalid ramp geometry or a non-positive ``radius``.
        """
        self._require_geometry()
        issues: list[Issue] = []
        check_number(
            issues, self.label, "ball_spawn radius", radius, lo=0.0, lo_open=True, unit=" m",
            hint="pass the ball's radius, e.g. ramp.ball_spawn(0.1)",
        )  # fmt: skip
        if issues:
            raise RubeValidationError(issues)
        direction, _, normal = self._frame()
        return self.start + direction * (1.5 * radius) + normal * (radius + CLEARANCE)

    def exit(self, distance: float = 0.0) -> Vec3:
        """Ground point (z = 0) ``distance`` m beyond the bottom end, along the ramp's heading.

        Use it to place what the rolling ball should hit next, e.g. the first domino.

        Raises:
            RubeValidationError: invalid ramp geometry.
        """
        self._require_geometry()
        heading = _horizontal(self._frame()[0]).normalized()
        p = self.end + heading * distance
        return Vec3(p.x, p.y, 0.0)


def _horizontal(v: Vec3) -> Vec3:
    """``v`` projected onto the XY plane."""
    return Vec3(v.x, v.y, 0.0)


# --- groups and constraints -------------------------------------------------------------


@dataclass(eq=False)
class Hinge:
    """Hinge constraint between two entities (not a rigid body; used by ``Lever``).

    Args:
        body_a: First entity (e.g. a passive fulcrum).
        body_b: Second entity (e.g. the dynamic plank).
        pivot: World hinge point (x, y, z), meters.
        axis: World hinge axis direction (any non-zero length).
        disable_collisions: If True, ``body_a`` and ``body_b`` do not collide.
        name: Name of the constraint Empty; ``None`` = auto ``Hinge_<n>``.
    """

    body_a: Entity
    body_b: Entity
    pivot: Vec3
    axis: Vec3
    disable_collisions: bool = True
    name: str | None = None

    def __post_init__(self) -> None:
        self.pivot = coerce_vec(self.pivot)
        self.axis = coerce_vec(self.axis)

    @classmethod
    def type_name(cls) -> str:
        """``"Hinge"``."""
        return cls.__name__

    @property
    def label(self) -> str:
        """Name for messages."""
        return self.name if isinstance(self.name, str) and self.name else "Hinge"

    def validate(self) -> list[Issue]:
        """Problems with the hinge's own arguments (registration is checked by ``Machine``)."""
        issues: list[Issue] = []
        who = self.label
        for field in ("body_a", "body_b"):
            if not isinstance(getattr(self, field), Entity):
                issues.append(
                    error(
                        "INVALID_ARGUMENT",
                        who,
                        f"{field} must be an entity, got {getattr(self, field)!r}",
                        "pass the entity objects the hinge connects",
                    )
                )
        if isinstance(self.body_a, Entity) and self.body_a is self.body_b:
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    who,
                    f"body_a and body_b are the same entity ({self.body_a.label})",
                    "connect two different entities",
                )
            )
        check_vec(issues, who, "pivot", self.pivot)
        check_vec(issues, who, "axis", self.axis)
        if isinstance(self.axis, Vec3) and self.axis.length() == 0:
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    who,
                    "axis is the zero vector",
                    "use a direction such as (0, 1, 0)",
                )
            )
        return issues

    def spec(self) -> HingeSpec:
        """Resolved ``HingeSpec`` (axis normalized, bodies by name)."""
        issues = self.validate()
        if has_errors(issues):
            raise RubeValidationError(issues)
        return HingeSpec(
            name=self.label,
            body_a=self.body_a.label,
            body_b=self.body_b.label,
            pivot=self.pivot,
            axis=self.axis.normalized(),
            disable_collisions=bool(self.disable_collisions),
        )

    def to_dict(self) -> dict:
        """JSON-safe record; bodies are referenced by name."""
        return {
            "type": "Hinge",
            "name": self.name,
            "body_a": self.body_a.label,
            "body_b": self.body_b.label,
            "pivot": jsonable(self.pivot),
            "axis": jsonable(self.axis),
            "disable_collisions": self.disable_collisions,
        }

    @classmethod
    def from_dict(cls, d: dict, entities_by_name: dict[str, Entity]) -> Hinge:
        """Inverse of ``to_dict``; ``entities_by_name`` resolves the body names."""
        return cls(
            entities_by_name[d["body_a"]],
            entities_by_name[d["body_b"]],
            d["pivot"],
            d["axis"],
            disable_collisions=d["disable_collisions"],
            name=d["name"],
        )


class Group:
    """Several entities (and constraints) added to a machine together.

    Returned by generators (``domino_chain``, ``spiral_ramp``) and ``Lever``. Adding a group
    registers its members in order. Groups exist only in system Python: ``to_dict()``
    flattens them (design D-5), so group-level checks belong in ``validate()``.

    Args:
        members: Entities and ``Hinge`` constraints, in build order.
        name: Group name; ``None`` = auto ``<Type>_<n>`` when added to a ``Machine``.
    """

    def __init__(self, members: list[Entity | Hinge], name: str | None = None):
        self.members: list[Entity | Hinge] = list(members)
        self.name = name

    @classmethod
    def type_name(cls) -> str:
        """Public type name, e.g. ``"DominoChain"``."""
        return cls.__name__

    def entities(self) -> list[Entity]:
        """Member entities in order."""
        return [m for m in self.members if isinstance(m, Entity)]

    def hinges(self) -> list[Hinge]:
        """Member constraints in order."""
        return [m for m in self.members if isinstance(m, Hinge)]

    def validate(self) -> list[Issue]:
        """Group-level problems (e.g. chain spacing). Members validate themselves."""
        return []
