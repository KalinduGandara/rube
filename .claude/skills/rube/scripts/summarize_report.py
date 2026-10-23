"""Print a compact, readable summary of a rube ``report.json`` (FR-028).

Runner-side helper for the Claude Code ``rube`` skill; stdlib only, no ``rube`` import, so it
works with any Python 3 and never depends on the package being installed.

Why it exists: a report lists every dynamic body and every event, which for a 300-domino
machine is thousands of JSON lines. The skill needs the facts that decide the next edit:
status, issues with hints, which bodies moved/fell and when, and where the stills are.

Usage::

    python3 summarize_report.py out/my_machine            # directory containing report.json
    python3 summarize_report.py out/my_machine/report.json --max-lines 40
    python3 summarize_report.py out/my_machine --all      # no truncation
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_MAX_LINES = 80  # per section (entities, events); keeps the summary skimmable


def load_report(target: Path) -> tuple[dict, Path]:
    """Return ``(report, out_dir)`` for a report file or the directory that holds one.

    Raises ``ValueError`` with a one-line message for a missing or malformed report.
    """
    path = target / "report.json" if target.is_dir() else target
    try:
        report = json.loads(path.read_text())
    except FileNotFoundError:
        raise ValueError(f"no report found at {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON ({exc.msg} at line {exc.lineno})") from None
    if not isinstance(report, dict) or "status" not in report:
        raise ValueError(f"{path} is not a rube report (no 'status' key)")
    return report, path.parent.resolve()


def _section(title: str, lines: list[str], limit: int | None, noun: str) -> list[str]:
    """Title + lines, cut to ``limit`` with an explicit count of what was left out."""
    out = [f"{title} ({len(lines)}):" if lines else f"{title}: none"]
    shown = lines if limit is None else lines[:limit]
    out += [f"  {line}" for line in shown]
    if len(shown) < len(lines):
        out.append(f"  ... {len(lines) - len(shown)} more {noun} omitted (use --all)")
    return out


def _fmt_pos(p) -> str:
    return "(" + ", ".join(f"{v:.2f}" for v in p) + ")" if p else "-"


def summarize(report: dict, out_dir: Path, limit: int | None) -> str:
    """Render the summary text. ``limit`` caps entity and event lines (``None`` = all)."""
    timing = report.get("timing") or {}
    lines = [
        f"status: {report['status']}   "
        f"({timing.get('duration_s', '?')} s simulated, frames "
        f"{timing.get('frame_start', '?')}-{timing.get('frame_end', '?')} at "
        f"{timing.get('fps', '?')} fps; wall {report.get('elapsed_s', '?')} s)"
    ]
    if report.get("traceback"):
        lines.append("traceback (framework bug, not your script):")
        lines += [f"  {t}" for t in report["traceback"].strip().splitlines()[-6:]]

    # Issues are never truncated: every error must be fixed before the next run.
    issues = [
        f"{i.get('severity', '?')} {i.get('code', '?')} [{i.get('entity') or '-'}]: "
        f"{i.get('message', '')} -> {i.get('hint', '')}"
        for i in report.get("issues", [])
    ]
    lines += _section("issues", issues, None, "issues")

    entities = report.get("entities", [])
    rows = []
    fell_by_type: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for e in entities:
        moved = (
            f"moved@{e['first_motion_time_s']:.2f}s"
            if e.get("first_motion_frame") is not None
            else "never moved"
        )
        flags = [
            name
            for name, on in (
                ("FELL", e.get("fell_over")),
                ("LEFT_BOUNDS", e.get("left_bounds")),
                ("at_rest", e.get("at_rest_at_end")),
            )
            if on
        ]
        rows.append(
            f"{e['name']} [{e['type']}] {moved} max {e.get('max_speed', 0):.2f} m/s "
            f"tilt {e.get('final_tilt_deg', 0):.0f}deg final {_fmt_pos(e.get('final_position'))}"
            + (f" {' '.join(flags)}" if flags else "")
        )
        if e["type"] in ("Domino", "Block"):  # only these can "fall over" (SPEC §8.7)
            fell_by_type[e["type"]][1] += 1
            fell_by_type[e["type"]][0] += bool(e.get("fell_over"))
    lines += _section("dynamic entities", rows, limit, "entities")
    for type_, (fell, total) in sorted(fell_by_type.items()):
        lines.append(f"  {type_}: {fell}/{total} fell over")

    events = [
        f"{ev['time_s']:.2f}s f{ev['frame']} {ev['entity']} {ev['event']}"
        for ev in report.get("events", [])
    ]
    lines += _section("events", events, limit, "events")

    # Absolute paths so the stills can be opened directly (e.g. with an image-reading tool).
    art = report.get("artifacts") or {}
    lines.append("artifacts:")
    lines += [f"  still: {out_dir / f}" for f in art.get("frames") or []]
    for key in ("video", "blend"):
        if art.get(key):
            lines.append(f"  {key}: {out_dir / art[key]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code (0 ok, 1 unreadable report)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", type=Path, help="report.json or the rube --out directory")
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    parser.add_argument("--all", action="store_true", help="print every entity and event")
    args = parser.parse_args(argv)
    try:
        report, out_dir = load_report(args.target)
    except ValueError as exc:
        print(f"summarize_report: {exc}", file=sys.stderr)
        return 1
    print(summarize(report, out_dir, None if args.all else args.max_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
