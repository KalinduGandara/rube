"""Machine: the one container an author script builds.

Layer 1 (pure Python, never imports ``bpy``). A ``Machine`` holds every entity, constraint
and group in **registration order** (= build order, needed for determinism), names unnamed
entities ``<Type>_<n>``, and validates the whole machine in one pass, returning all issues
(SPEC section 4, 9.1). ``bodies()`` / ``constraints()`` resolve it to the build specs Layer 2
consumes.

Timing (SPEC section 2): fixed 24 fps; ``frames = ceil(duration * 24)``; the scene runs from
frame 1 to ``1 + frames``.

Implements: FR-001, FR-002, FR-003 (timing), FR-013 (machine-level checks), FR-015.
"""

from __future__ import annotations

import math
from collections import Counter
from itertools import combinations

from rube.entities import BodySpec, Entity, Floor, Group, Hinge, HingeSpec
from rube.errors import Issue, RubeValidationError, error, has_errors, warning
from rube.geometry import aabb_gap
from rube.vec import is_number

#: Frames per second (fixed in v1).
FPS = 24
#: Rigid body limit (bake time grows quickly beyond this).
MAX_BODIES = 500
#: Allowed simulation duration, seconds.
DURATION_RANGE = (1.0, 60.0)
#: MASS_RATIO: warn above this ratio between dynamic bodies closer than MASS_RATIO_GAP.
MASS_RATIO_LIMIT = 100.0
MASS_RATIO_GAP = 0.05


def frame_count(duration: float) -> int:
    """Number of simulated frames for ``duration`` seconds: ``ceil(duration * 24)``.

    Why the epsilon: ``1.0000000000000002 * 24`` must not round up to an extra frame.
    """
    return math.ceil(duration * FPS - 1e-9)


class Machine:
    """A Rube Goldberg machine: entities + constraints + camera + timing.

    Args:
        name: Machine name (used for output files).
        duration: Simulated time in seconds, 1..60.
        floor: Add a passive ``Floor`` first (top at z = 0). Without a floor, objects fall
            forever, so keep this on unless you build your own ground.
        floor_size: Floor edge length in meters (centered on the origin).

    Attributes:
        entities: Registered entities in build order (the auto floor first).
        hinges: Registered ``Hinge`` constraints in order.
        groups: Registered groups (their members are already in ``entities`` / ``hinges``).
    """

    def __init__(
        self,
        name: str = "machine",
        duration: float = 10.0,
        floor: bool = True,
        floor_size: float = 20.0,
    ):
        self.name = name
        self.duration = duration
        self.floor = floor
        self.floor_size = floor_size
        self.entities: list[Entity] = []
        self.hinges: list[Hinge] = []
        self.groups: list[Group] = []
        self._counters: Counter[str] = Counter()
        self._taken: set[str] = set()
        if floor:
            self.add(Floor(size=floor_size))

    # -- registration -------------------------------------------------------------------

    def add(self, item: Entity | Group) -> Entity | Group:
        """Register an entity or a group (all members, in order) and return it unchanged.

        Unnamed items are named ``<Type>_<n>`` now, so ``item.name`` is usable right away.

        Raises:
            TypeError: if ``item`` is not an ``Entity`` or ``Group`` (a script bug, reported
                as ``SCRIPT_ERROR`` with the line number).
        """
        if isinstance(item, Group):
            self._name(item)
            self.groups.append(item)
            for member in item.members:
                self._register(member)
        elif isinstance(item, Entity):
            self._register(item)
        else:
            raise TypeError(
                f"Machine.add() takes an entity (Ball, Block, Domino, ...) or a group, "
                f"got {type(item).__name__}: {item!r}"
            )
        return item

    def _register(self, item: Entity | Hinge) -> None:
        self._name(item)
        if isinstance(item, Hinge):
            self.hinges.append(item)
        elif isinstance(item, Entity):
            self.entities.append(item)
        else:
            raise TypeError(f"group member must be an entity or Hinge, got {item!r}")

    def _name(self, item: Entity | Hinge | Group) -> None:
        """Assign ``<Type>_<n>`` if unnamed (per-type counter, skipping taken names, D-17)."""
        if item.name is None:
            type_name = item.type_name()
            while True:
                self._counters[type_name] += 1
                candidate = f"{type_name}_{self._counters[type_name]}"
                if candidate not in self._taken:
                    break
            item.name = candidate
        if isinstance(item.name, str):
            self._taken.add(item.name)

    def get(self, name: str) -> Entity:
        """The registered entity called ``name``.

        Raises:
            KeyError: if there is none.
        """
        for e in self.entities:
            if e.name == name:
                return e
        raise KeyError(name)

    # -- timing -------------------------------------------------------------------------

    @property
    def frame_start(self) -> int:
        """First frame (always 1)."""
        return 1

    @property
    def frame_end(self) -> int:
        """Last frame: ``1 + ceil(duration * 24)``."""
        return 1 + frame_count(self.duration)

    # -- validation ---------------------------------------------------------------------

    def validate(self) -> list[Issue]:
        """All problems of the machine (pure Layer 1; never raises for content problems).

        Order: machine settings, each entity, each hinge, each group, then cross-entity
        checks (names, body count, floor area, mass ratio).
        """
        issues = self._settings_issues()
        valid: list[Entity] = []
        for e in self.entities:
            entity_issues = e.validate()
            issues += entity_issues
            if not has_errors(entity_issues):
                valid.append(e)
        for h in self.hinges:
            issues += h.validate()
            issues += self._hinge_registration_issues(h)
        for g in self.groups:
            issues += g.validate()
        issues += self._name_issues()
        if len(self.entities) > MAX_BODIES:
            issues.append(
                error(
                    "TOO_MANY_BODIES",
                    None,
                    f"machine has {len(self.entities)} rigid bodies; the limit is {MAX_BODIES}",
                    "use fewer or larger pieces (e.g. fewer dominoes with larger spacing)",
                )
            )
        bodies = {e: e.body() for e in valid}
        issues += self._outside_floor_issues(bodies)
        issues += self._mass_ratio_issues(bodies)
        return issues

    def _settings_issues(self) -> list[Issue]:
        issues: list[Issue] = []
        if not isinstance(self.name, str) or not self.name.strip():
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    None,
                    f"machine name must be a non-empty string, got {self.name!r}",
                    "use e.g. Machine(name='ball_into_dominoes')",
                )
            )
        lo, hi = DURATION_RANGE
        if not is_number(self.duration):
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    None,
                    f"duration must be a number of seconds, got {self.duration!r}",
                    "use e.g. duration=10",
                )
            )
        elif not lo <= self.duration <= hi:
            issues.append(
                error(
                    "OUT_OF_RANGE",
                    None,
                    f"duration is {self.duration:g} s; it must be between {lo:g} and {hi:g} s",
                    f"use duration between {lo:g} and {hi:g}",
                )
            )
        if not isinstance(self.floor, bool):
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    None,
                    f"floor must be True or False, got {self.floor!r}",
                    "use floor=True (recommended) or floor=False",
                )
            )
        return issues

    def _hinge_registration_issues(self, hinge: Hinge) -> list[Issue]:
        issues: list[Issue] = []
        for field in ("body_a", "body_b"):
            body = getattr(hinge, field)
            if isinstance(body, Entity) and not any(body is e for e in self.entities):
                issues.append(
                    error(
                        "INVALID_ARGUMENT",
                        hinge.label,
                        f"{field} {body.label!r} is not part of the machine",
                        f"add {body.label!r} to the machine (or to the same group) too",
                    )
                )
        return issues

    def _name_issues(self) -> list[Issue]:
        counts = Counter(
            item.name for item in [*self.entities, *self.hinges] if isinstance(item.name, str)
        )
        return [
            error(
                "NAME_DUPLICATE",
                name,
                f"name {name!r} is used by {n} objects",
                "give each entity a unique name (and add each object only once)",
            )
            for name, n in counts.items()
            if n > 1
        ]

    def _outside_floor_issues(self, bodies: dict[Entity, BodySpec]) -> list[Issue]:
        floors = [e for e in bodies if isinstance(e, Floor)]
        if not floors:
            return []
        issues: list[Issue] = []
        reach = max(f.half_size for f in floors)
        for e, body in bodies.items():
            if isinstance(e, Floor):
                continue
            c = body.location
            if not any(abs(c.x) <= f.half_size and abs(c.y) <= f.half_size for f in floors):
                need = 2 * math.ceil(max(abs(c.x), abs(c.y)) + 1)
                issues.append(
                    error(
                        "OUTSIDE_FLOOR",
                        e.label,
                        f"center ({c.x:g}, {c.y:g}) is outside the floor, which covers "
                        f"|x|, |y| <= {reach:g} m; it would fall off",
                        f"move it within {reach:g} m of the origin or use floor_size={need}",
                    )
                )
        return issues

    def _mass_ratio_issues(self, bodies: dict[Entity, BodySpec]) -> list[Issue]:
        dynamic = [(e, b) for e, b in bodies.items() if b.dynamic]
        boxes: dict[int, tuple] = {}
        issues: list[Issue] = []
        for (ea, ba), (eb, bb) in combinations(dynamic, 2):
            heavy, light = max(ba.mass, bb.mass), min(ba.mass, bb.mass)
            # Cheap mass test first; AABBs (vertex transforms) only for suspicious pairs.
            if heavy <= MASS_RATIO_LIMIT * light:
                continue
            box_a = boxes.setdefault(id(ba), ba.aabb())
            box_b = boxes.setdefault(id(bb), bb.aabb())
            if aabb_gap(box_a, box_b) <= MASS_RATIO_GAP:
                issues.append(
                    warning(
                        "MASS_RATIO",
                        f"{ea.label},{eb.label}",
                        f"mass ratio {heavy / light:.0f}:1 ({ba.mass:g} kg vs {bb.mass:g} kg) "
                        f"between bodies within {MASS_RATIO_GAP:g} m; Bullet may jitter or "
                        "let them pass through each other",
                        f"keep touching bodies within {MASS_RATIO_LIMIT:.0f}:1, e.g. raise the "
                        "lighter mass",
                    )
                )
        return issues

    # -- build specs ---------------------------------------------------------------------

    def _require_valid(self) -> None:
        issues = self.validate()
        if has_errors(issues):
            raise RubeValidationError([i for i in issues if i.severity == "error"])

    def bodies(self) -> list[BodySpec]:
        """Every entity as a ``BodySpec``, in build order.

        Raises:
            RubeValidationError: if the machine has errors.
        """
        self._require_valid()
        return [e.body() for e in self.entities]

    def constraints(self) -> list[HingeSpec]:
        """Every hinge as a ``HingeSpec``, in build order.

        Raises:
            RubeValidationError: if the machine has errors.
        """
        self._require_valid()
        return [h.spec() for h in self.hinges]
