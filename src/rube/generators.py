"""Generators: functions that lay out many entities at once and return them as a ``Group``.

Layer 1 (pure Python, never imports ``bpy``). All placement math happens here so it is
unit-testable (SPEC section 3.1). A generator never raises for content problems: it stores
its arguments, builds members only when the arguments are usable, and reports every problem
from the group's ``validate()`` (which ``Machine.validate()`` calls), so the author sees all
issues in one run (FR-013, design D-15).

``domino_chain`` (SPEC section 6.1): dominoes along a Catmull-Rom spline through flat
waypoints, at equal **arc length**, each facing the path tangent.

Implements: FR-011.
"""

from __future__ import annotations

import math
from typing import Any

from rube.entities import (
    COLORS,
    Domino,
    Group,
    check_number,
    check_size3,
    coerce_size,
    coerce_vec,
)
from rube.errors import Issue, RubeValidationError, error, has_errors
from rube.geometry import ArcLengthTable, catmull_rom
from rube.vec import Vec3, is_number

#: Default domino size ``(thickness, width, height)``, meters (same as ``Domino``).
DOMINO_SIZE = (0.1, 0.4, 0.8)
#: Allowed spacing as a fraction of domino height: closer touches/overlaps, farther stops.
SPACING_RANGE = (0.3, 0.75)
#: Default spacing as a fraction of domino height.
DEFAULT_SPACING = 0.5
#: Largest yaw change between neighbouring dominoes; sharper turns break the chain.
MAX_TURN_DEG = 15.0
#: Polyline samples per waypoint segment for the arc-length table (design section 6).
SAMPLES_PER_SEGMENT = 200
#: Waypoints count as flat when their z values differ by at most this (meters).
FLAT_TOLERANCE = 1e-6


class DominoChain(Group):
    """Dominoes standing along a path; returned by ``domino_chain``.

    Members are the dominoes in path order (``members == dominoes``).

    Anchors:
        dominoes: The ``Domino`` list, first to last.
        first, last: The first / last ``Domino``.
        start, end: The path's first and last waypoint (``Vec3``).
    """

    def __init__(
        self,
        points: Any,
        spacing: Any = None,
        count: Any = None,
        size: Any = DOMINO_SIZE,
        tilt_first_deg: Any = 0.0,
        color: Any = None,
    ):
        self.points = (
            [coerce_vec(p) for p in points] if isinstance(points, (list, tuple)) else points
        )
        self.spacing = spacing
        self.count = count
        self.size = coerce_size(size)
        self.tilt_first_deg = tilt_first_deg
        self.color = color
        super().__init__(self._layout())

    # -- layout --------------------------------------------------------------------------

    def _layout(self) -> list[Domino]:
        """The dominoes, or ``[]`` when the arguments cannot produce a chain of >= 2.

        Why nothing on bad arguments: every domino would repeat the same problem, and the
        chain-level issue from ``validate()`` already names it once.
        """
        if has_errors(self._argument_issues("DominoChain")):
            return []
        positions, yaws = self._placement()
        if len(positions) < 2:
            return []
        return [
            Domino(
                p,
                facing_deg=yaw,
                tilt_deg=self.tilt_first_deg if k == 0 else 0.0,
                size=self.size,
                color=self.color,
            )
            for k, (p, yaw) in enumerate(zip(positions, yaws, strict=True))
        ]

    def _table(self) -> ArcLengthTable:
        return ArcLengthTable(catmull_rom(self.points, SAMPLES_PER_SEGMENT))

    def _effective_spacing(self, length: float) -> float:
        """Arc length between neighbours (meters): given, from ``count``, or 0.5 x height."""
        if self.count is not None:
            return length / (self.count - 1)
        if self.spacing is not None:
            return float(self.spacing)
        return DEFAULT_SPACING * self.size[2]

    def _placement(self) -> tuple[list[Vec3], list[float]]:
        """Domino positions at equal arc length and their yaw (degrees) along the tangent."""
        table = self._table()
        spacing = self._effective_spacing(table.length)
        # The epsilon keeps a path that is an exact multiple of the spacing from losing its
        # last domino to float rounding.
        n = math.floor(table.length / spacing + 1e-9) + 1
        positions, yaws = [], []
        for k in range(n):
            s = min(k * spacing, table.length)
            t = table.tangent_at(s)
            positions.append(table.point_at(s))
            yaws.append(math.degrees(math.atan2(t.y, t.x)))
        return positions, yaws

    # -- anchors -------------------------------------------------------------------------

    def _require_dominoes(self) -> None:
        if not self.members:
            issues = [i for i in self.validate() if i.severity == "error"]
            raise RubeValidationError(issues)

    @property
    def dominoes(self) -> list[Domino]:
        """The dominoes in path order (empty if the arguments are unusable)."""
        return list(self.members)

    @property
    def first(self) -> Domino:
        """First domino of the chain (the one to hit, or the tilted starter)."""
        self._require_dominoes()
        return self.members[0]

    @property
    def last(self) -> Domino:
        """Last domino of the chain."""
        self._require_dominoes()
        return self.members[-1]

    @property
    def start(self) -> Vec3:
        """First waypoint of the path."""
        self._require_dominoes()
        return self.points[0]

    @property
    def end(self) -> Vec3:
        """Last waypoint of the path."""
        self._require_dominoes()
        return self.points[-1]

    # -- validation ----------------------------------------------------------------------

    @property
    def label(self) -> str:
        """Name for messages: the group name, or ``"DominoChain"`` before it is named."""
        return self.name if isinstance(self.name, str) and self.name else self.type_name()

    def validate(self) -> list[Issue]:
        """Chain-level problems: arguments, CHAIN_NOT_FLAT, CHAIN_SPACING, CHAIN_TURN, count."""
        who = self.label
        issues = self._argument_issues(who)
        if has_errors(issues):
            return issues
        table = self._table()
        height = self.size[2]
        spacing = self._effective_spacing(table.length)
        lo, hi = SPACING_RANGE[0] * height, SPACING_RANGE[1] * height
        if not lo - 1e-9 <= spacing <= hi + 1e-9:
            # Counts that give a valid spacing on this path: (count - 1) * spacing = length.
            n_lo = math.ceil(table.length / hi - 1e-9) + 1
            n_hi = math.floor(table.length / lo + 1e-9) + 1
            via = f"count={self.count}" if self.count is not None else f"{spacing:g} m"
            issues.append(
                error(
                    "CHAIN_SPACING",
                    who,
                    f"spacing is {spacing:g} m ({via}) for dominoes {height:g} m tall; it must "
                    f"be {SPACING_RANGE[0]:g}-{SPACING_RANGE[1]:g} x height (closer dominoes "
                    "touch, farther ones do not reach the next)",
                    f"use spacing between {lo:g} and {hi:g} m"
                    + (
                        f", or count between {n_lo} and {n_hi} on this {table.length:.2f} m path"
                        if self.count is not None and n_lo <= n_hi
                        else ""
                    ),
                )
            )
        positions, yaws = self._placement()
        if len(positions) < 2:
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    who,
                    f"the path is {table.length:.3g} m long, which fits fewer than 2 dominoes "
                    f"at {spacing:g} m spacing",
                    f"make the path at least {spacing:g} m long or reduce spacing",
                )
            )
            return issues
        turns = [abs((b - a + 180.0) % 360.0 - 180.0) for a, b in zip(yaws, yaws[1:], strict=False)]
        worst = max(turns)
        if worst > MAX_TURN_DEG:
            k = turns.index(worst)
            # Turning MAX_TURN_DEG per spacing means a radius of spacing / angle (radians).
            radius = spacing / math.radians(MAX_TURN_DEG)
            issues.append(
                error(
                    "CHAIN_TURN",
                    who,
                    f"the path turns {worst:.1f} deg between dominoes {k + 1} and {k + 2}; at "
                    f"most {MAX_TURN_DEG:g} deg between neighbours keeps the chain going",
                    f"smooth the curve to a turn radius of at least {radius:.2f} m (move the "
                    "waypoints around the corner farther apart, or add waypoints along a wider "
                    "arc)",
                )
            )
        return issues

    def _argument_issues(self, who: str) -> list[Issue]:
        """Problems that make the chain impossible to lay out (and CHAIN_NOT_FLAT)."""
        issues: list[Issue] = []
        pts = self.points
        if not isinstance(pts, list) or len(pts) < 2:
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    who,
                    f"points must be a list of at least 2 waypoints (x, y, z), got {pts!r}",
                    "pass e.g. points=[(0, 0, 0), (4, 0, 0)]",
                )
            )
        else:
            bad = [p for p in pts if not isinstance(p, Vec3)]
            if bad:
                issues.append(
                    error(
                        "INVALID_ARGUMENT",
                        who,
                        f"every waypoint must be three numbers (x, y, z), got {bad[0]!r}",
                        "pass waypoints as tuples like (1.0, 2.0, 0.0)",
                    )
                )
            else:
                for k, (a, b) in enumerate(zip(pts, pts[1:], strict=False)):
                    if (b - a).length() < 1e-9:
                        issues.append(
                            error(
                                "INVALID_ARGUMENT",
                                who,
                                f"waypoints {k + 1} and {k + 2} are at the same position "
                                f"{a.to_list()}",
                                "remove the repeated waypoint",
                            )
                        )
                zs = [p.z for p in pts]
                if max(zs) - min(zs) > FLAT_TOLERANCE:
                    issues.append(
                        error(
                            "CHAIN_NOT_FLAT",
                            who,
                            f"waypoint z values range from {min(zs):g} to {max(zs):g} m; "
                            "domino paths must be flat",
                            f"give every waypoint the same z, e.g. z={zs[0]:g}",
                        )
                    )
        if self.spacing is not None and self.count is not None:
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    who,
                    f"both spacing ({self.spacing!r}) and count ({self.count!r}) are given",
                    "pass only one of spacing or count",
                )
            )
        if self.spacing is not None:
            check_number(
                issues, who, "spacing", self.spacing, lo=0.0, lo_open=True, unit=" m",
                hint="use a spacing of about half the domino height, e.g. spacing=0.4",
            )  # fmt: skip
        if self.count is not None and (
            not is_number(self.count) or self.count != int(self.count) or self.count < 2
        ):
            issues.append(
                error(
                    "INVALID_ARGUMENT",
                    who,
                    f"count must be a whole number >= 2, got {self.count!r}",
                    "use e.g. count=20, or omit count to use spacing",
                )
            )
        check_size3(issues, who, "size", self.size, ("thickness", "width", "height"), DOMINO_SIZE)
        check_number(
            issues, who, "tilt_first_deg", self.tilt_first_deg, lo=0.0, hi=90.0, hi_open=True,
            unit=" deg", hint="use tilt_first_deg=10 to start the chain by itself, or 0",
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


def domino_chain(
    points: Any,
    *,
    spacing: float | None = None,
    count: int | None = None,
    size: tuple[float, float, float] = DOMINO_SIZE,
    tilt_first_deg: float = 0.0,
    color: str | None = None,
) -> DominoChain:
    """Dominoes standing along a smooth path through ``points``; add the result to a machine.

    The path is a Catmull-Rom spline **through** the waypoints (two points = straight line).
    Dominoes are placed at equal arc length from the first waypoint, each facing (falling
    toward) the path direction, so the chain runs from ``points[0]`` toward ``points[-1]``.

    Args:
        points: Two or more flat waypoints (x, y, z) in meters, all with the same z (the
            surface the dominoes stand on).
        spacing: Arc length between neighbouring dominoes, meters; must be 0.3-0.75 x height.
        count: Number of dominoes, spread so the first and last stand on the path ends. Give
            ``spacing`` or ``count``, not both; neither = spacing of 0.5 x height.
        size: Domino ``(thickness, width, height)`` in meters.
        tilt_first_deg: Pre-tilt of the first domino in degrees [0, 90); 10 starts the chain
            by itself, 0 waits for something to hit it.
        color: Preview color name for every domino (default: the Domino default).

    Returns:
        A ``DominoChain`` group (``.first``, ``.last``, ``.dominoes``, ``.start``, ``.end``).
        Problems (``CHAIN_SPACING``, ``CHAIN_TURN``, ``CHAIN_NOT_FLAT``, ...) are reported by
        ``validate()``, never raised.
    """
    return DominoChain(points, spacing, count, size, tilt_first_deg, color)
