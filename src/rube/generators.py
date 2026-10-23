"""Generators: functions that lay out many entities at once and return them as a ``Group``.

Layer 1 (pure Python, never imports ``bpy``). All placement math happens here so it is
unit-testable (SPEC section 3.1). A generator never raises for content problems: it stores
its arguments, builds members only when the arguments are usable, and reports every problem
from the group's ``validate()`` (which ``Machine.validate()`` calls), so the author sees all
issues in one run (FR-013, design D-15).

``domino_chain`` (SPEC section 6.1): dominoes along a Catmull-Rom spline through flat
waypoints, at equal **arc length**, each facing the path tangent.

``spiral_ramp`` (SPEC section 6.2): a helix U-channel (``SpiralTrack``) around a passive
``SupportColumn``, with slope and track-width checks.

Implements: FR-010, FR-011.
"""

from __future__ import annotations

import math
from typing import Any

from rube.entities import (
    CLEARANCE,
    COLORS,
    COLUMN_GAP,
    Domino,
    Group,
    SpiralTrack,
    SupportColumn,
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


# --- spiral ramp ----------------------------------------------------------------------------

#: Allowed spiral slope (height / horizontal helix length) in degrees: shallower and the ball
#: stops, steeper and it skips over the walls (SPEC 6.2).
SPIRAL_SLOPE_RANGE_DEG = (4.0, 25.0)
#: ``ball_spawn(r)`` requires ``track_width >= 2.5 r`` and ``wall_height >= 0.6 r``.
TRACK_WIDTH_PER_RADIUS = 2.5
WALL_HEIGHT_PER_RADIUS = 0.6


class SpiralRamp(Group):
    """Helix U-channel around a central support column; returned by ``spiral_ramp``.

    Members: ``SpiralTrack`` then ``SupportColumn`` (both passive), or none when the
    arguments are unusable (``validate()`` then reports them once, under the group name).

    Anchors:
        entry: Top-surface centerline point where the track starts (high end).
        exit: Top-surface centerline point where the track ends (``thickness`` above ground).
        ball_spawn(radius): Center for a ball resting in the groove just after the entry.
    """

    def __init__(
        self,
        center: Any,
        radius: Any,
        height: Any,
        turns: Any,
        track_width: Any = 0.25,
        wall_height: Any = 0.08,
        thickness: Any = 0.03,
        clockwise: Any = False,
    ):
        self.track = SpiralTrack(
            center, radius, height, turns,
            track_width=track_width, wall_height=wall_height, thickness=thickness,
            clockwise=clockwise,
        )  # fmt: skip
        #: Radii passed to ``ball_spawn``; checked against the track size by ``validate()``.
        self.spawn_radii: list[float] = []
        members = []
        if not has_errors(self.track.argument_issues(self.type_name())):
            t = self.track
            column = SupportColumn(t.center, t.radius - t.track_width / 2 - COLUMN_GAP, t.height)
            members = [t, column]
        super().__init__(members)

    @property
    def label(self) -> str:
        """Name for messages: the group name, or ``"SpiralRamp"`` before it is named."""
        return self.name if isinstance(self.name, str) and self.name else self.type_name()

    # -- anchors -------------------------------------------------------------------------

    def _require_members(self) -> None:
        if not self.members:
            raise RubeValidationError(self.track.argument_issues(self.label))

    @property
    def entry(self) -> Vec3:
        """High end of the floor's top-surface centerline (``center.z + height``)."""
        self._require_members()
        return self.track.point_at(0.0)

    @property
    def exit(self) -> Vec3:
        """Low end of the floor's top-surface centerline (``center.z + thickness``)."""
        self._require_members()
        return self.track.point_at(1.0)

    def ball_spawn(self, radius: float = 0.1) -> Vec3:
        """Center for a ball of ``radius`` m that starts rolling from the top of the spiral.

        The center is ``1.5 * radius`` along the track from the entry and ``radius +
        CLEARANCE`` above the floor along its normal (same rule as ``Ramp.ball_spawn``).
        Using it also enables the ``TRACK_TOO_NARROW`` check for this radius.

        Raises:
            RubeValidationError: unusable spiral arguments or a non-positive ``radius``.
        """
        self._require_members()
        issues: list[Issue] = []
        check_number(
            issues, self.label, "ball_spawn radius", radius, lo=0.0, lo_open=True, unit=" m",
            hint="pass the ball's radius, e.g. spiral.ball_spawn(0.08)",
        )  # fmt: skip
        if issues:
            raise RubeValidationError(issues)
        self.spawn_radii.append(float(radius))
        f = 1.5 * radius / self.track.length
        _, _, up = self.track.frame_at(f)
        return self.track.point_at(f) + up * (radius + CLEARANCE)

    # -- validation ----------------------------------------------------------------------

    def validate(self) -> list[Issue]:
        """Arguments, SLOPE_TOO_SHALLOW / SLOPE_TOO_STEEP, TRACK_TOO_NARROW (after ball_spawn)."""
        who = self.label
        if not self.members:
            return self.track.argument_issues(who)
        t = self.track
        issues: list[Issue] = []
        # SPEC 6.2 slope: height over the horizontal length of the helix.
        run = 2 * math.pi * t.radius * t.turns
        slope = t.height / run
        lo_deg, hi_deg = SPIRAL_SLOPE_RANGE_DEG
        lo, hi = math.tan(math.radians(lo_deg)), math.tan(math.radians(hi_deg))
        if not lo <= slope <= hi:
            code = "SLOPE_TOO_SHALLOW" if slope < lo else "SLOPE_TOO_STEEP"
            turns_lo, turns_hi = (
                t.height / (hi * 2 * math.pi * t.radius),
                t.height / (lo * 2 * math.pi * t.radius),
            )
            issues.append(
                error(
                    code,
                    who,
                    f"slope is {math.degrees(math.atan(slope)):.1f} deg (height {t.height:g} m "
                    f"over {run:.2f} m of helix); it must be {lo_deg:g}-{hi_deg:g} deg "
                    + ("or the ball stops" if slope < lo else "or the ball skips over the walls"),
                    f"use height between {lo * run:.2f} and {hi * run:.2f} m, or turns between "
                    f"{turns_lo:.2f} and {turns_hi:.2f} for this height and radius",
                )
            )
        if self.spawn_radii:
            r = max(self.spawn_radii)
            need_w, need_h = TRACK_WIDTH_PER_RADIUS * r, WALL_HEIGHT_PER_RADIUS * r
            if t.track_width < need_w - 1e-9 or t.wall_height < need_h - 1e-9:
                max_r = min(t.track_width / TRACK_WIDTH_PER_RADIUS,
                            t.wall_height / WALL_HEIGHT_PER_RADIUS)  # fmt: skip
                issues.append(
                    error(
                        "TRACK_TOO_NARROW",
                        who,
                        f"a ball of radius {r:g} m needs track_width >= {need_w:g} m and "
                        f"wall_height >= {need_h:g} m; the track has {t.track_width:g} m and "
                        f"{t.wall_height:g} m",
                        f"use track_width >= {need_w:g} and wall_height >= {need_h:g}, or a "
                        f"ball radius <= {max_r:.3g} m",
                    )
                )
        return issues


def spiral_ramp(
    center: Any,
    radius: float,
    height: float,
    turns: float,
    *,
    track_width: float = 0.25,
    wall_height: float = 0.08,
    thickness: float = 0.03,
    clockwise: bool = False,
) -> SpiralRamp:
    """A spiral U-channel for a ball to roll down, around a support column; add it to a machine.

    The groove's floor (top-surface centerline) is a helix of ``radius`` around the vertical
    axis through ``center``. It starts on the +X side of the axis at ``center.z + height``
    and descends evenly to ``center.z + thickness`` (the channel bottom ends on the ground),
    counter-clockwise seen from above unless ``clockwise``. Passive, collision ``MESH``.

    Args:
        center: Ground point (x, y, z) under the spiral axis, meters.
        radius: Helix radius of the groove centerline, meters (>= track_width/2 + thickness +
            0.02 so the inner wall and the column fit).
        height: Entry height above ``center.z``, meters.
        turns: Number of turns (> 0). Slope = height / (2 pi radius turns) must be 4-25 deg.
        track_width: Inner groove width, meters (>= 2.5 x ball radius).
        wall_height: Wall height above the groove floor, meters (>= 0.6 x ball radius).
        thickness: Floor and wall thickness, meters.
        clockwise: Turn clockwise seen from above.

    Returns:
        A ``SpiralRamp`` group (``.entry``, ``.exit``, ``.ball_spawn(r)``). Problems
        (``SLOPE_TOO_SHALLOW``, ``SLOPE_TOO_STEEP``, ``TRACK_TOO_NARROW``, ...) are reported by
        ``validate()``, never raised.
    """
    return SpiralRamp(center, radius, height, turns, track_width, wall_height, thickness, clockwise)
