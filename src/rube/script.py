"""Loading an author script: static import guard, execution, and the ``machine`` contract.

Layer 1 (pure Python, never imports ``bpy``; runs only in system Python, never in Blender --
Blender receives JSON data only, design D-1 / NFR-006).

Script contract (SPEC section 10.1): the script defines a top-level variable ``machine`` of
type ``Machine`` and never calls ``bpy`` or any run method.

Before executing, the source is parsed with ``ast`` and rejected (``DISALLOWED_IMPORT``) if it
imports anything but ``rube`` (and submodules), ``math`` or ``random``, or mentions the names
``__import__``, ``eval``, ``exec`` or ``open``. This is a **guard rail, not a sandbox**: it
catches an LLM reaching for the filesystem or Blender by mistake, but determined code can get
around it. Run untrusted scripts in a container.

Implements: FR-016, NFR-006.
"""

from __future__ import annotations

import ast
import traceback
from pathlib import Path

from rube.errors import Issue, RubeValidationError, error
from rube.machine import Machine

#: Top-level modules a script may import.
ALLOWED_MODULES = ("rube", "math", "random")
#: Builtin names a script may not mention at all.
FORBIDDEN_NAMES = ("__import__", "eval", "exec", "open")

_IMPORT_HINT = (
    f"only import {', '.join(ALLOWED_MODULES)}; describe the machine with the rube API "
    "(no files, no bpy, no other libraries)"
)


def check_source(source: str, filename: str) -> list[Issue]:
    """Statically check a script's source without running it.

    Args:
        source: Python source text.
        filename: Shown in messages.

    Returns:
        ``DISALLOWED_IMPORT`` issues (one per violation, with line numbers), or a single
        ``SCRIPT_ERROR`` if the source does not parse. Empty list = safe to execute.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [
            error(
                "SCRIPT_ERROR",
                None,
                f"{filename} line {exc.lineno}: SyntaxError: {exc.msg}",
                f"fix the Python syntax at line {exc.lineno}",
            )
        ]
    found: list[tuple[int, Issue]] = []

    def disallow(node: ast.AST, what: str) -> None:
        issue = error("DISALLOWED_IMPORT", None, f"line {node.lineno}: {what}", _IMPORT_HINT)
        found.append((node.lineno, issue))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_MODULES:
                    disallow(node, f"import of {alias.name!r} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                disallow(node, "relative import (from . import ...) is not allowed")
            elif (node.module or "").split(".")[0] not in ALLOWED_MODULES:
                disallow(node, f"import from {node.module!r} is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            disallow(node, f"use of {node.id!r} is not allowed")
    # ast.walk is breadth-first; report in source order (stable sort keeps same-line order).
    return [issue for _, issue in sorted(found, key=lambda pair: pair[0])]


def _script_error(exc: BaseException, path: Path) -> Issue:
    """``SCRIPT_ERROR`` naming the last traceback frame inside the user script."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == str(path)]
    where = f" at line {frames[-1].lineno}: {frames[-1].line}" if frames else ""
    line_hint = f"line {frames[-1].lineno}" if frames else "the script"
    message = f"{type(exc).__name__}: {exc}"
    return error(
        "SCRIPT_ERROR",
        None,
        f"{path.name}{where} -> {message}",
        f"fix {line_hint} (see the error above)",
    )


def load_machine(path: str | Path) -> tuple[Machine | None, list[Issue]]:
    """Guard-check and execute a script, returning its ``machine``.

    Args:
        path: Script file.

    Returns:
        ``(machine, [])`` on success, else ``(None, issues)`` with ``DISALLOWED_IMPORT``,
        ``SCRIPT_ERROR`` or ``NO_MACHINE``. A ``RubeValidationError`` raised by the script
        (e.g. an anchor of a broken entity) contributes its own issues too.
    """
    path = Path(path).resolve()
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [
            error(
                "SCRIPT_ERROR",
                None,
                f"cannot read script {str(path)!r}: {exc.strerror or exc}",
                "check the path to the machine script",
            )
        ]
    issues = check_source(source, path.name)
    if issues:
        return None, issues
    namespace = {"__name__": "__rube_script__", "__file__": str(path)}
    try:
        # compile with the real path so traceback frames can be matched to the script.
        exec(compile(source, str(path), "exec"), namespace)  # noqa: S102 - guarded above
    except RubeValidationError as exc:
        return None, [*exc.issues, _script_error(exc, path)]
    except (Exception, SystemExit) as exc:  # author mistakes of any kind are feedback
        return None, [_script_error(exc, path)]
    machine = namespace.get("machine")
    if not isinstance(machine, Machine):
        found = "is missing" if machine is None else f"is a {type(machine).__name__}"
        return None, [
            error(
                "NO_MACHINE",
                None,
                f"top-level variable 'machine' {found}",
                "define machine = Machine(...) at the top level of the script and add "
                "entities to it",
            )
        ]
    return machine, []


def check_script(path: str | Path) -> tuple[Machine | None, list[Issue]]:
    """Load a script and validate its machine (pure system Python; Blender never starts).

    Returns:
        ``(machine, issues)``: loading issues if the script failed (machine ``None``),
        otherwise ``machine.validate()``.
    """
    machine, issues = load_machine(path)
    if machine is None:
        return None, issues
    return machine, machine.validate()
