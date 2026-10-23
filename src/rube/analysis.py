"""Post-bake analysis: sampled rigid body transforms -> report entity records, events, issues.

Layer 1 (pure Python, never imports ``bpy``). ``rube.blender.simulate`` samples every dynamic
body's world transform once per frame after the bake and hands the plain numbers to
``analyze``; all the judgement ("did it move, fall over, leave the floor, settle?") lives
here so it is unit-testable without Blender (assumption A-3, design D-6).

Conventions: positions in meters (world, Z up), rotations as row-major 3x3 world matrices,
angles reported in degrees, speeds in m/s. Sample ``i`` belongs to frame ``frame_start + i``;
times are ``(frame - frame_start) / fps`` seconds.

Implements: FR-023.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from rube.errors import Issue, warning
from rube.machine import FPS
from rube.vec import Mat3, Vec3, mat_mul, mat_transpose

#: First motion: displacement from frame 1 strictly greater than this (m) ...
MOTION_DISPLACEMENT = 0.005
#: ... or rotation from frame 1 strictly greater than this (degrees).
MOTION_ROTATION_DEG = 2.0
#: Final tilt (angle of local +Z vs world +Z, degrees) above which a body has fallen over.
FELL_OVER_TILT_DEG = 60.0
#: Types for which ``fell_over`` is meaningful (a rolling ball "tilts" all the time).
FALLS_OVER_TYPES = ("Domino", "Block")
#: Below this z (m) a body has left the scene, floor or not.
MIN_Z = -1.0
#: ``at_rest_at_end``: every step in the last REST_WINDOW_S seconds is slower than REST_SPEED.
REST_SPEED = 0.01
REST_WINDOW_S = 0.5
#: UNSTABLE warning thresholds: max speed (m/s) and displacement in a single frame (m).
UNSTABLE_SPEED = 30.0
UNSTABLE_JUMP = 2.0

#: Tie-break order for events on the same frame and entity.
_EVENT_ORDER = ("started_moving", "fell_over", "left_bounds")


@dataclass(frozen=True)
class Track:
    """World transforms of one dynamic body, one sample per frame starting at ``frame_start``.

    Attributes:
        name: Entity name.
        type: Public type name (e.g. ``"Domino"``).
        positions: Object origin (= center of volume) per frame, meters.
        rotations: Row-major 3x3 world rotation matrix per frame.
    """

    name: str
    type: str
    positions: list[Vec3]
    rotations: list[Mat3]

    def __post_init__(self) -> None:
        if len(self.positions) != len(self.rotations) or not self.positions:
            raise ValueError(
                f"track {self.name!r}: need the same non-zero number of positions "
                f"({len(self.positions)}) and rotations ({len(self.rotations)})"
            )


@dataclass(frozen=True)
class Analysis:
    """Result of ``analyze``.

    Attributes:
        entities: One SPEC 9.2 record per track, in track (build) order.
        events: ``{"frame", "time_s", "entity", "event"}`` dicts sorted by frame.
        issues: ``UNSTABLE`` warnings (one per offending entity).
    """

    entities: list[dict]
    events: list[dict]
    issues: list[Issue]


def rotation_angle_deg(a: Mat3, b: Mat3) -> float:
    """Angle (degrees, 0..180) of the relative rotation ``a^T b`` between two orientations."""
    rel = mat_mul(mat_transpose(a), b)
    trace = rel[0][0] + rel[1][1] + rel[2][2]
    return math.degrees(math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0))))


def tilt_deg(rotation: Mat3) -> float:
    """Angle (degrees) between the body's local +Z axis and world +Z.

    The local +Z axis in world space is the third column of the rotation matrix, so its
    z component is ``rotation[2][2]``.
    """
    return math.degrees(math.acos(max(-1.0, min(1.0, rotation[2][2]))))


def _first(flags: list[bool]) -> int | None:
    """Index of the first ``True``, or ``None``."""
    return next((i for i, flag in enumerate(flags) if flag), None)


def _round_vec(v: Vec3) -> list[float]:
    # 1e-6 m resolution: far below anything physical, keeps report.json readable.
    return [round(c, 6) for c in v]


def _out_of_bounds(p: Vec3, floor_half_size: float | None) -> bool:
    if p.z < MIN_Z:
        return True
    return floor_half_size is not None and (
        abs(p.x) > floor_half_size or abs(p.y) > floor_half_size
    )


def _analyze_track(
    track: Track, fps: float, frame_start: int, floor_half_size: float | None
) -> tuple[dict, list[tuple[int, str]], Issue | None]:
    """Record, ``(sample index, event)`` pairs and optional UNSTABLE issue for one track."""
    p0, r0 = track.positions[0], track.rotations[0]
    steps = [(b - a).length() for a, b in itertools.pairwise(track.positions)]
    speeds = [d * fps for d in steps]
    max_speed = max(speeds, default=0.0)

    moved = _first(
        [
            (p - p0).length() > MOTION_DISPLACEMENT
            or rotation_angle_deg(r0, r) > MOTION_ROTATION_DEG
            for p, r in zip(track.positions, track.rotations, strict=True)
        ]
    )
    tilts = [tilt_deg(r) for r in track.rotations]
    fell_over = track.type in FALLS_OVER_TYPES and tilts[-1] > FELL_OVER_TILT_DEG
    # Event at the first frame past the threshold, reported only if it stayed fallen.
    fell_at = _first([t > FELL_OVER_TILT_DEG for t in tilts]) if fell_over else None
    left_at = _first([_out_of_bounds(p, floor_half_size) for p in track.positions])

    window = max(1, round(REST_WINDOW_S * fps))
    at_rest = all(v < REST_SPEED for v in speeds[-window:])

    def time_s(index: int | None) -> float | None:
        return None if index is None else round(index / fps, 4)

    record = {
        "name": track.name,
        "type": track.type,
        "initial_position": _round_vec(p0),
        "final_position": _round_vec(track.positions[-1]),
        "first_motion_frame": None if moved is None else frame_start + moved,
        "first_motion_time_s": time_s(moved),
        "max_speed": round(max_speed, 4),
        "final_tilt_deg": round(tilts[-1], 2),
        "fell_over": fell_over,
        "left_bounds": left_at is not None,
        "at_rest_at_end": at_rest,
    }
    events = [
        (index, kind)
        for index, kind in (
            (moved, "started_moving"),
            (fell_at, "fell_over"),
            (left_at, "left_bounds"),
        )
        if index is not None
    ]

    issue = None
    max_step = max(steps, default=0.0)
    if max_speed > UNSTABLE_SPEED or max_step > UNSTABLE_JUMP:
        jump_frame = frame_start + steps.index(max_step) + 1
        issue = warning(
            "UNSTABLE",
            track.name,
            f"max speed {max_speed:.1f} m/s (limit {UNSTABLE_SPEED:g}); largest move "
            f"{max_step:.2f} m in one frame at frame {jump_frame} (limit {UNSTABLE_JUMP:g} m)",
            "the simulation exploded: look for bodies that start touching or overlapping, very "
            "small or very light bodies next to heavy ones, or a high bounciness; add a few "
            "mm of clearance and keep sizes >= 0.02 m",
        )
    return record, events, issue


def analyze(
    tracks: list[Track],
    *,
    fps: float = FPS,
    frame_start: int = 1,
    floor_half_size: float | None = None,
) -> Analysis:
    """Turn sampled tracks into report records (SPEC section 8 step 7).

    Args:
        tracks: One ``Track`` per dynamic body, in build order (passive bodies omitted).
        fps: Frames per second of the samples.
        frame_start: Frame number of sample 0.
        floor_half_size: The floor covers ``|x|, |y| <= floor_half_size``; ``None`` = no
            floor (then only ``z < -1`` counts as leaving bounds).

    Returns:
        ``Analysis`` with per-entity records, events sorted by frame (ties: track order,
        then started_moving / fell_over / left_bounds), and ``UNSTABLE`` warnings.
    """
    records: list[dict] = []
    keyed_events: list[tuple[tuple[int, int, int], dict]] = []
    issues: list[Issue] = []
    for order, track in enumerate(tracks):
        record, events, issue = _analyze_track(track, fps, frame_start, floor_half_size)
        records.append(record)
        if issue is not None:
            issues.append(issue)
        for index, kind in events:
            event = {
                "frame": frame_start + index,
                "time_s": round(index / fps, 4),
                "entity": track.name,
                "event": kind,
            }
            keyed_events.append(((index, order, _EVENT_ORDER.index(kind)), event))
    events_sorted = [event for _, event in sorted(keyed_events, key=lambda pair: pair[0])]
    return Analysis(records, events_sorted, issues)
