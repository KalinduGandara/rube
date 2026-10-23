"""Command-line runner: ``rube check`` (and, from milestone M2, ``rube run``).

Runner layer (system Python; never imports ``bpy`` -- it only spawns Blender).

``rube check machine.py`` loads the script through the import guard, validates the machine
and prints every issue, one per line. Exit code 0 when there are no errors (warnings are
fine), 2 when there are errors, 1 on a framework bug (traceback on stderr). Blender is never
started.

Implements: FR-017 (and the CLI side of FR-016).
"""

from __future__ import annotations

import argparse
import sys
import traceback

from rube.errors import format_issue, has_errors
from rube.script import check_script


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


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for the ``rube`` command."""
    parser = argparse.ArgumentParser(
        prog="rube",
        description="Declarative Rube Goldberg machines simulated in Blender.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate a machine script (Blender is not started)")
    check.add_argument("script", help="path to a script defining `machine = Machine(...)`")
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
    except Exception:  # framework bug: not an author problem (SPEC section 9.1)
        traceback.print_exc()
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
