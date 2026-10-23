"""Command-line runner: ``rube check`` and ``rube run``.

Runner layer (system Python; never imports ``bpy`` -- it only spawns Blender).

``rube check machine.py`` loads the script through the import guard, validates the machine
and prints every issue, one per line. Exit code 0 when there are no errors (warnings are
fine), 2 when there are errors, 1 on a framework bug (traceback on stderr). Blender is never
started.

``rube run machine.py --out DIR [--video] [--timeout 300]`` first deletes the artifacts of an
earlier run in ``DIR`` (``STALE_ARTIFACTS``, nothing else), then validates the same way; an invalid
machine gets ``DIR/report.json`` with status ``invalid`` and exit 2 without starting Blender.
Otherwise it writes ``DIR/spec.json`` (``Machine.to_dict()``, design D-1: Blender only ever
sees data) and runs ``Blender -b --factory-startup --python-exit-code 1 --python
rube/blender/bootstrap.py -- --spec ... --out ... [--video]`` in its own process group, with
stdout/stderr captured in ``DIR/blender.log``. The exit code follows the report status (0 ok,
2 invalid, 3 bake_failed, 4 timeout, 1 internal_error), and ``report.json`` is written in
every case: on timeout, when Blender dies without a report, and on Ctrl-C (status
``internal_error``, "interrupted", before the interrupt propagates) the CLI writes it itself.

Implements: FR-017, FR-018 (and the CLI side of FR-016, FR-025, NFR-006).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

from rube.errors import Issue, error, format_issue, has_errors
from rube.report import build_report, exit_code, read_report, timing, write_report
from rube.script import check_script
from rube.vec import is_number

#: Blender binary used when ``RUBE_BLENDER`` is not set (SPEC section 1).
DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
#: Entry point executed inside Blender.
BOOTSTRAP = Path(__file__).resolve().parent / "blender" / "bootstrap.py"
#: Default ``--timeout`` in seconds.
DEFAULT_TIMEOUT = 300.0
#: Every path a run writes into ``--out`` (FR-018, FR-024); removed at the start of a run.
STALE_ARTIFACTS = (
    "report.json",
    "spec.json",
    "blender.log",
    "machine.blend",
    "video.mp4",
    "frames",
)
#: Lines of ``blender.log`` quoted in an ``internal_error`` report.
LOG_TAIL_LINES = 40


def cmd_check(path: str) -> int:
    """Validate a machine script and print the result.

    Returns:
        Exit code: 0 no errors, 2 errors.
    """
    machine, issues = check_script(path)
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = len(issues) - errors
    if has_errors(issues):
        print(f"rube check: INVALID ({errors} error(s), {warnings} warning(s)) - {path}")
    else:
        bodies = len(machine.entities) if machine is not None else 0
        print(f"rube check: OK ({bodies} bodies, {warnings} warning(s)) - {path}")
    for issue in issues:
        print(format_issue(issue))
    return 2 if has_errors(issues) else 0


def find_blender() -> str:
    """Path of the Blender binary: ``$RUBE_BLENDER`` if set, else ``DEFAULT_BLENDER``."""
    return os.environ.get("RUBE_BLENDER") or DEFAULT_BLENDER


def blender_command(blender: str, spec_path: Path, out_dir: Path, video: bool) -> list[str]:
    """Command line for one fresh Blender process running the bootstrap (design section 5).

    Args:
        blender: Blender executable.
        spec_path: Absolute path of ``spec.json``.
        out_dir: Absolute output directory.
        video: Ask for ``video.mp4`` too.
    """
    cmd = [
        blender, "-b", "--factory-startup", "--python-exit-code", "1",
        "--python", str(BOOTSTRAP), "--", "--spec", str(spec_path), "--out", str(out_dir),
    ]  # fmt: skip
    return cmd + ["--video"] if video else cmd


def _log_tail(log_path: Path) -> str:
    """Last ``LOG_TAIL_LINES`` lines of the Blender log (empty if it does not exist)."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-LOG_TAIL_LINES:])


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGKILL the process group Blender leads (it may have spawned helpers), then reap it."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:  # already gone
        pass
    proc.wait()


def remove_stale_artifacts(out_dir: Path) -> None:
    """Delete the artifacts of an earlier run in ``out_dir`` (``STALE_ARTIFACTS`` only).

    Anything else in the directory is the author's and is left alone. Symlinks are removed as
    links, never followed: ``rmtree`` runs only on a real ``frames`` directory.
    """
    for name in STALE_ARTIFACTS:
        path = out_dir / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def _finish(out_dir: Path, report: dict, start: float) -> int:
    """Stamp the CLI wall time (design D-20), write the report, print a summary, return the code."""
    report["elapsed_s"] = round(time.monotonic() - start, 3)
    write_report(out_dir / "report.json", report)
    issues = [Issue.from_dict(i) for i in report["issues"]]
    print(f"rube run: {report['status']} ({report['elapsed_s']:.1f} s) - {out_dir / 'report.json'}")
    for issue in issues:
        print(format_issue(issue))
    return exit_code(report["status"])


def _launch(cmd: list[str], log_path: Path, timeout: float) -> int | None:
    """Run Blender with output captured in ``log_path``.

    Returns:
        Blender's exit code, or ``None`` if it was killed after ``timeout`` seconds.
    """
    with log_path.open("w", encoding="utf-8") as log:
        # Own session = own process group, so a timeout kill also reaches anything Blender
        # spawned (a hung bake would otherwise keep running after we gave up).
        proc = subprocess.Popen(
            cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )  # fmt: skip
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            return None
        except BaseException:  # e.g. Ctrl-C: never leave Blender running behind us
            _kill_group(proc)
            raise


def cmd_run(path: str, out: str, video: bool = False, timeout: float = DEFAULT_TIMEOUT) -> int:
    """Validate a machine script, simulate it in Blender and write ``out/report.json``.

    Args:
        path: Author script defining ``machine``.
        out: Output directory (created; relative paths are resolved against the cwd, because
            Blender needs absolute paths, SPEC section 1.1).
        video: Also render ``video.mp4`` (rendering arrives in milestone M4).
        timeout: Seconds before the Blender process group is killed (status ``timeout``).

    Returns:
        Exit code: 0 ok, 2 invalid, 3 bake_failed, 4 timeout, 1 internal_error.
    """
    start = time.monotonic()
    out_dir = Path(out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.json"
    # Artifacts left by an earlier run must never pass for this run's (design D-20, D-30).
    remove_stale_artifacts(out_dir)
    try:
        machine, issues = check_script(path)
        # No timing block when there is no machine or its duration is not even a number.
        has_duration = machine is not None and is_number(machine.duration)
        run_timing = timing(machine.duration) if has_duration else None
        if machine is None or has_errors(issues):
            return _finish(
                out_dir, build_report("invalid", issues=issues, timing=run_timing), start
            )

        spec_path = out_dir / "spec.json"
        spec_path.write_text(json.dumps(machine.to_dict(), indent=2) + "\n", encoding="utf-8")
        blender = find_blender()
        if not Path(blender).is_file():
            message = (
                f"Blender not found at {blender!r}; install Blender 5.2 or set RUBE_BLENDER "
                "to the Blender executable"
            )
            report = build_report("internal_error", timing=run_timing, traceback=message)
            return _finish(out_dir, report, start)

        log_path = out_dir / "blender.log"
        returncode = _launch(blender_command(blender, spec_path, out_dir, video), log_path, timeout)
        if returncode is None:
            timeout_issue = error(
                "TIMEOUT",
                None,
                f"Blender did not finish within {timeout:g} s and was stopped",
                "shorten duration or use fewer bodies; a hang often means bodies start "
                "overlapping or explode - or raise --timeout",
            )
            report = build_report("timeout", issues=[timeout_issue], timing=run_timing)
            return _finish(out_dir, report, start)
        try:
            report = read_report(report_path)
            exit_code(report["status"])  # an unknown status is a framework bug too
        except (OSError, ValueError, KeyError, TypeError) as exc:
            message = (
                f"Blender exited with exit code {returncode} without a usable report.json "
                f"({type(exc).__name__}: {exc}). Last lines of {log_path}:\n{_log_tail(log_path)}"
            )
            report = build_report("internal_error", timing=run_timing, traceback=message)
        return _finish(out_dir, report, start)
    except Exception:  # framework bug: report it, never crash without a report (SPEC 9.1)
        report = build_report("internal_error", traceback=traceback.format_exc())
        return _finish(out_dir, report, start)
    except BaseException as exc:
        # Ctrl-C (or a SystemExit from deep inside): still leave a report behind (FR-016),
        # then let the interrupt end the process as the user asked. `_launch` has already
        # killed Blender; a report Blender wrote before dying is superseded by this one.
        why = "interrupted" if isinstance(exc, KeyboardInterrupt) else traceback.format_exc()
        _finish(out_dir, build_report("internal_error", traceback=why), start)
        raise


def positive_seconds(text: str) -> float:
    """``argparse`` type for ``--timeout``: a finite number of seconds > 0.

    Why: ``0`` or a negative value would time out Blender at once and ``nan`` crashes the wait,
    both reported as if the machine were at fault.
    """
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of seconds") from None
    if not (math.isfinite(value) and value > 0):
        raise argparse.ArgumentTypeError(f"{text!r} must be a finite number of seconds > 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for the ``rube`` command."""
    parser = argparse.ArgumentParser(
        prog="rube",
        description="Declarative Rube Goldberg machines simulated in Blender.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate a machine script (Blender is not started)")
    check.add_argument("script", help="path to a script defining `machine = Machine(...)`")
    run = sub.add_parser("run", help="simulate a machine script in Blender and write a report")
    run.add_argument("script", help="path to a script defining `machine = Machine(...)`")
    run.add_argument("--out", required=True, help="output directory (report.json, spec.json, ...)")
    run.add_argument("--video", action="store_true", help="also render video.mp4")
    run.add_argument(
        "--timeout",
        type=positive_seconds,
        default=DEFAULT_TIMEOUT,
        help=f"seconds before Blender is killed (default {DEFAULT_TIMEOUT:g})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point of the ``rube`` console script.

    Args:
        argv: Arguments without the program name (default: ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            return cmd_check(args.script)
        if args.command == "run":
            return cmd_run(args.script, args.out, video=args.video, timeout=args.timeout)
    except Exception:  # framework bug: not an author problem (SPEC section 9.1)
        traceback.print_exc()
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
