"""Loading an author script: static import guard, execution, and the ``machine`` contract.

Layer 1 (pure Python, never imports ``bpy``; runs only in system Python, never in Blender --
Blender receives JSON data only, design D-1 / NFR-006).

Script contract (SPEC section 10.1): the script defines a top-level variable ``machine`` of
type ``Machine`` and never calls ``bpy`` or any run method.

Before executing, the source is parsed with ``ast`` and rejected (``DISALLOWED_IMPORT``) if it
imports anything but ``math``, ``random``, ``rube`` or a public ``rube`` API module (never
``rube.cli``, ``rube.script``, ``rube.report``, ``rube.blender*``, which hold ``os``,
``subprocess`` and file access); mentions a name in ``FORBIDDEN_NAMES`` (``__import__``,
``eval``, ``exec``, ``open``, ``__builtins__``, ``getattr``, ``globals``, ...); or reads a dunder
attribute (``x.__globals__``) or a frame/generator internal (``gi_frame``, ``f_globals``, ...).
A script that passes runs with a curated ``__builtins__`` (``SAFE_BUILTINS``: the arithmetic,
container, iteration and exception builtins a machine script needs), whose ``__import__``
re-checks every import at run time and hands out *public views* of ``rube`` and ``random``
(their ``__all__`` only): the real ``rube`` package also carries every submodule already
loaded (``rube.cli`` in the CLI) and ``random`` keeps ``os`` as ``random._os`` (design D-28).

This is still a **guard rail, not a sandbox**: it catches an LLM reaching for the filesystem
or Blender by mistake and closes the obvious escape hatches, but determined code can get
around it (``str.format`` can still *read* attributes, for one). Run untrusted scripts in a
container.

Implements: FR-016, NFR-006.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import pkgutil
import sys
import traceback
import types
from pathlib import Path

from rube.errors import Issue, RubeValidationError, error
from rube.machine import Machine

#: Public API modules of the ``rube`` package an author script may import (design D-28).
PUBLIC_RUBE_MODULES = (
    "rube",
    "rube.camera",
    "rube.entities",
    "rube.errors",
    "rube.generators",
    "rube.geometry",
    "rube.machine",
    "rube.vec",
)
#: Every module a script may import (exact names; no other submodules).
ALLOWED_MODULES = ("math", "random", *PUBLIC_RUBE_MODULES)
#: Names a script may not mention at all: dynamic code, files, interactive input, and the
#: introspection builtins that reach any attribute or namespace by string.
FORBIDDEN_NAMES = (
    "__import__", "eval", "exec", "open", "__builtins__", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "compile", "breakpoint", "input",
)  # fmt: skip
#: Non-dunder attributes that lead from a generator, coroutine, frame or traceback to
#: another module's globals or the real builtins (dunder attributes are rejected wholesale).
FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame", "ag_code",
        "f_back", "f_builtins", "f_code", "f_globals", "f_locals", "tb_frame", "tb_next",
    }
)  # fmt: skip
#: Builtins available to a script (plus ``__import__`` = ``_guarded_import``): enough for
#: arithmetic, containers, loops, classes, printing and catching the usual exceptions.
SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "chr", "classmethod", "dict", "divmod", "enumerate",
    "filter", "float", "format", "frozenset", "hasattr", "hash", "int", "isinstance",
    "issubclass", "iter", "len", "list", "map", "max", "min", "next", "object", "ord", "pow",
    "print", "property", "range", "repr", "reversed", "round", "set", "slice", "sorted",
    "staticmethod", "str", "sum", "super", "tuple", "zip", "__build_class__",
    "None", "True", "False", "Ellipsis", "NotImplemented",
    "ArithmeticError", "AssertionError", "AttributeError", "Exception", "IndexError",
    "KeyError", "LookupError", "NotImplementedError", "OverflowError", "RuntimeError",
    "StopIteration", "TypeError", "ValueError", "ZeroDivisionError",
)  # fmt: skip

_IMPORT_HINT = (
    "only import math, random and the public rube API (from rube import ...); describe the "
    "machine with the rube API (no files, no bpy, no other libraries, no introspection)"
)


def _private_rube_submodules() -> frozenset[str]:
    """Short names of ``rube`` submodules that are not public (``cli``, ``blender``, ...)."""
    import rube  # local: the package imports this module's dependencies first

    public = {name.split(".")[1] for name in PUBLIC_RUBE_MODULES if "." in name}
    return frozenset(m.name for m in pkgutil.iter_modules(rube.__path__)) - public


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

    private = _private_rube_submodules()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_MODULES:
                    disallow(node, f"import of {alias.name!r} is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                disallow(node, "relative import (from . import ...) is not allowed")
            elif node.module not in ALLOWED_MODULES:
                disallow(node, f"import from {node.module!r} is not allowed")
            elif node.module == "rube":
                # `from rube import cli` reaches a private submodule as a package attribute.
                for alias in node.names:
                    if alias.name in private:
                        disallow(node, f"import of 'rube.{alias.name}' is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            disallow(node, f"use of {node.id!r} is not allowed")
        elif isinstance(node, ast.Attribute) and (
            node.attr.startswith("__") or node.attr in FORBIDDEN_ATTRIBUTES
        ):
            # Dunder attributes (__globals__, __class__, __subclasses__, ...) and frame
            # internals are the standard ways from any object back to real modules.
            disallow(node, f"access to attribute {node.attr!r} is not allowed")
    # ast.walk is breadth-first; report in source order (stable sort keeps same-line order).
    return [issue for _, issue in sorted(found, key=lambda pair: pair[0])]


def _public_view(module: types.ModuleType) -> types.ModuleType:
    """A stand-in module exposing only ``module.__all__`` (plus public ``rube`` submodules).

    Why: the real ``rube`` package also has every *loaded* submodule as an attribute (the CLI
    has loaded ``rube.cli``, which holds ``os`` and ``subprocess``), and ``random`` keeps
    ``os`` as ``random._os``; neither is visible to the static guard.
    """
    view = types.ModuleType(module.__name__, module.__doc__)
    names = list(module.__all__)
    if module.__name__ == "rube":
        names += [name.split(".")[1] for name in PUBLIC_RUBE_MODULES if "." in name]
    for name in names:
        setattr(view, name, getattr(module, name))
    view.__all__ = list(module.__all__)
    return view


#: Modules a script receives as a public view (``_public_view``) instead of the real one.
_VIEWED_MODULES = ("rube", "random")


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    """``__import__`` for author scripts: allowed modules only, ``rube``/``random`` as views.

    Mirrors the builtin's contract: ``import a.b`` gets the top package ``a``, ``from a.b
    import x`` gets ``a.b`` itself.
    """
    if level or name not in ALLOWED_MODULES:
        raise ImportError(f"import of {name!r} is not allowed in a machine script")
    module = importlib.import_module(name)
    if not fromlist:
        module = sys.modules[name.split(".")[0]]
    return _public_view(module) if module.__name__ in _VIEWED_MODULES else module


def safe_builtins() -> dict:
    """Fresh ``__builtins__`` mapping for one script run (``SAFE_BUILTIN_NAMES`` + import)."""
    return {
        **{name: getattr(builtins, name) for name in SAFE_BUILTIN_NAMES},
        "__import__": _guarded_import,
    }


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
    namespace = {
        "__name__": "__rube_script__",
        "__file__": str(path),
        "__builtins__": safe_builtins(),
    }
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
