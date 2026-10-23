"""``report.json``: the single report builder used by the CLI and by Blender.

Layer 1 (pure Python, never imports ``bpy``). ``report.json`` is written in every case:
by the CLI for ``invalid`` / ``timeout`` / ``internal_error`` without a Blender report, and by
``rube.blender.bootstrap`` for ``ok`` / ``bake_failed`` / ``invalid`` (overlap). One builder
keeps the shape identical whoever writes it (design D-7). Shape: SPEC section 9.2.

Implements: FR-025 (report shape), FR-018 (status -> exit code).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rube import __version__
from rube.errors import Issue
from rube.machine import FPS, frame_count

#: Report status -> process exit code of ``rube run`` (SPEC section 10.1).
STATUS_EXIT: dict[str, int] = {
    "ok": 0,
    "invalid": 2,
    "bake_failed": 3,
    "timeout": 4,
    "internal_error": 1,
}


def exit_code(status: str) -> int:
    """Exit code for a report status.

    Raises:
        ValueError: unknown status.
    """
    if status not in STATUS_EXIT:
        raise ValueError(f"unknown report status {status!r}")
    return STATUS_EXIT[status]


def timing(duration: float) -> dict:
    """The ``timing`` block: fps, frame range (1 .. 1 + ceil(duration*24)), duration in s."""
    return {
        "fps": FPS,
        "frame_start": 1,
        "frame_end": 1 + frame_count(duration),
        "duration_s": duration,
    }


#: Number of still frames rendered per run (SPEC section 8 step 8).
STILL_COUNT = 6


def still_frames(frame_start: int, frame_end: int, count: int = STILL_COUNT) -> list[int]:
    """Frame numbers of the preview stills: ``count`` evenly spaced, first and last included.

    Args:
        frame_start: First frame of the scene range.
        frame_end: Last frame (inclusive).
        count: Number of stills wanted.

    Returns:
        Strictly increasing frames; fewer than ``count`` when the range has fewer frames.
    """
    if count < 2 or frame_end <= frame_start:
        return [frame_start]
    span = frame_end - frame_start
    # Rounding can repeat a frame only when span < count - 1; the set removes those repeats.
    return sorted({frame_start + round(i * span / (count - 1)) for i in range(count)})


def build_report(
    status: str,
    *,
    issues: list[Issue | dict] = (),
    timing: dict | None = None,
    entities: list[dict] = (),
    events: list[dict] = (),
    artifacts: dict | None = None,
    blender_version: str | None = None,
    elapsed_s: float = 0.0,
    traceback: str | None = None,
) -> dict[str, Any]:
    """Assemble a report dict with exactly the SPEC section 9.2 keys, in order.

    Args:
        status: ``ok | invalid | bake_failed | timeout | internal_error``.
        issues: ``Issue`` objects (or their dicts).
        timing: Output of ``timing(duration)``, or ``None`` if no machine was loaded.
        entities: Per dynamic entity records (passive bodies omitted).
        events: Event records sorted by frame.
        artifacts: ``{"frames": [...], "video": str|None, "blend": str|None}`` relative paths.
        blender_version: e.g. ``"5.2.3"``; ``None`` when Blender never ran.
        elapsed_s: Wall time in seconds.
        traceback: Only for ``internal_error``: the framework traceback.

    Returns:
        JSON-safe dict; ``traceback`` key added only when given.
    """
    exit_code(status)  # validates the status
    report: dict[str, Any] = {
        "status": status,
        "issues": [i.to_dict() if isinstance(i, Issue) else dict(i) for i in issues],
        "timing": timing,
        "entities": list(entities),
        "events": list(events),
        "artifacts": artifacts or {"frames": [], "video": None, "blend": None},
        "blender_version": blender_version,
        "rube_version": __version__,
        "elapsed_s": round(float(elapsed_s), 3),
    }
    if traceback is not None:
        report["traceback"] = traceback
    return report


def write_report(path: str | Path, report: dict) -> None:
    """Write ``report`` as indented JSON to ``path`` (absolute; parent dirs created)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def read_report(path: str | Path) -> dict:
    """Load a ``report.json``."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
