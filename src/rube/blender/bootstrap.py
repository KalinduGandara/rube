"""Entry point executed inside Blender by ``rube run``: spec.json -> simulation -> report.json.

Layers 2/3 (runs inside Blender's bundled Python). Invoked as::

    Blender -b --factory-startup --python-exit-code 1 --python .../rube/blender/bootstrap.py \
        -- --spec DIR/spec.json --out DIR [--video]

It never executes the author's script: it rebuilds the machine from JSON data with
``Machine.from_dict`` (design D-1, NFR-006). Pipeline (SPEC section 8): reset -> scene
settings -> rigid body world -> build -> overlap check -> bake -> sample & analyze -> save
``machine.blend`` -> ``report.json``. A report is written in every case; a framework
exception becomes status ``internal_error`` with the traceback (SPEC section 9.1), and the
process still exits 0 so the CLI reads the status from the report.

Implements: FR-018 (Blender side), FR-019 - FR-025 orchestration.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

# Blender's Python does not have rube installed: put our src/ directory on sys.path
# (this file is src/rube/blender/bootstrap.py, design section 5).
_SRC = Path(__file__).resolve().parents[2]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bpy  # noqa: E402

from rube.analysis import analyze  # noqa: E402
from rube.blender import build, render, scene, simulate  # noqa: E402
from rube.entities import Floor  # noqa: E402
from rube.errors import error  # noqa: E402
from rube.machine import FPS, Machine  # noqa: E402
from rube.report import build_report, timing, write_report  # noqa: E402

BLEND_NAME = "machine.blend"


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the arguments after Blender's ``--`` separator (``--spec``, ``--out``, ``--video``)."""
    args = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser(prog="rube.blender.bootstrap")
    parser.add_argument("--spec", required=True, help="absolute path of spec.json")
    parser.add_argument("--out", required=True, help="absolute output directory")
    parser.add_argument("--video", action="store_true", help="render video.mp4 (milestone M4)")
    return parser.parse_args(args)


def blender_version() -> str:
    """Blender version as ``"major.minor.patch"`` (e.g. ``"5.2.3"``)."""
    return ".".join(str(part) for part in bpy.app.version)


def floor_half_size(machine: Machine) -> float | None:
    """Half edge of the largest floor (``left_bounds`` area), or ``None`` without a floor."""
    return max((e.half_size for e in machine.entities if isinstance(e, Floor)), default=None)


def run_pipeline(spec: dict, out_dir: Path, video: bool) -> dict:
    """Simulate one machine and return its report dict (SPEC section 8).

    Args:
        spec: ``Machine.to_dict()`` output (already validated by the CLI).
        out_dir: Absolute output directory.
        video: Requested video output (ignored until milestone M4, design D-21).

    Returns:
        Report with status ``ok``, ``invalid`` (overlap, nothing baked) or ``bake_failed``.
    """
    del video  # rendering arrives in M4
    machine = Machine.from_dict(spec)
    # The CLI rejected errors already; keep its warnings (e.g. MASS_RATIO) in this report.
    issues = machine.validate()
    run_timing = timing(machine.duration)
    sc = bpy.context.scene

    scene.reset()
    scene.configure(sc, machine.frame_end)
    scene.add_rigid_body_world(sc)
    ctx = build.build_machine(machine, sc)
    blend = out_dir / BLEND_NAME
    artifacts = {"frames": [], "video": None, "blend": BLEND_NAME}

    overlaps = simulate.check_overlaps(ctx)
    if overlaps:
        # Do not bake: overlapping bodies explode, and the author needs the fix, not a movie.
        render.save_blend(sc, blend)
        return build_report(
            "invalid", issues=issues + overlaps, timing=run_timing, artifacts=artifacts
        )

    bake_error = simulate.bake(sc)
    if bake_error is not None:
        failure = error(
            "BAKE_FAILED",
            None,
            f"Blender could not bake the simulation: {bake_error}",
            "simplify the machine (fewer bodies, no overlaps) and run again",
        )
        render.save_blend(sc, blend)
        return build_report(
            "bake_failed", issues=[*issues, failure], timing=run_timing, artifacts=artifacts
        )

    result = analyze(
        simulate.sample(ctx),
        fps=FPS,
        frame_start=sc.frame_start,
        floor_half_size=floor_half_size(machine),
    )
    render.save_blend(sc, blend)
    return build_report(
        "ok",
        issues=issues + result.issues,
        timing=run_timing,
        entities=result.entities,
        events=result.events,
        artifacts=artifacts,
    )


def main(argv: list[str]) -> None:
    """Run the pipeline and always write ``report.json`` (internal_error on any exception)."""
    start = time.monotonic()
    args = parse_args(argv)
    out_dir = Path(args.out).resolve()
    report_timing = None
    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        report_timing = timing(spec["duration"])
        report = run_pipeline(spec, out_dir, args.video)
    except Exception:  # framework bug: surface it as internal_error (SPEC 9.1)
        traceback.print_exc()
        report = build_report(
            "internal_error", timing=report_timing, traceback=traceback.format_exc()
        )
    report["blender_version"] = blender_version()
    report["elapsed_s"] = round(time.monotonic() - start, 3)
    write_report(out_dir / "report.json", report)
    print(f"rube bootstrap: status {report['status']} -> {out_dir / 'report.json'}")


if __name__ == "__main__":
    main(sys.argv)
