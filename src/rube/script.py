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

Execution is limited to ``SCRIPT_TIMEOUT_S`` (30 s, fixed) of wall time; a script that runs
longer is stopped and reported as ``SCRIPT_ERROR``. Any exception the script raises, including
``BaseException`` subclasses (``SystemExit``, a ``KeyboardInterrupt`` it raises itself), is
``SCRIPT_ERROR``; only a real Ctrl-C propagates (design D-29).

This is still a **guard rail, not a sandbox**: it catches an LLM reaching for the filesystem
or Blender by mistake and closes the obvious escape hatches, but determined code can get
around it (``str.format`` can still *read* attributes, for one). Run untrusted scripts in a
container.

Implements: FR-016, NFR-006.
"""

from __future__ import annotations

import ast
import builtins
import pkgutil
import signal
import sys
import threading
import traceback
import types
from pathlib import Path

from rube.errors import Issue, RubeValidationError, error
from rube.machine import Machine

#: Wall-clock limit (s) on executing an author script (FR-016). Fixed, not configurable: a
#: machine description runs in milliseconds, so 30 s only ever means an endless loop.
SCRIPT_TIMEOUT_S = 30.0
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

#: The real ``__import__``, which the guard wraps (the guard only ever sees allowed names).
_REAL_IMPORT = builtins.__import__


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    """``__import__`` for author scripts: allowed modules only, ``rube``/``random`` as views.

    Mirrors the builtin's contract: ``import a.b`` gets the top package ``a``, ``from a.b
    import x`` gets ``a.b`` itself.
    """
    if level or name not in ALLOWED_MODULES:
        raise ImportError(f"import of {name!r} is not allowed in a machine script")
    # A non-empty fromlist makes the builtin return the leaf module (as import_module does).
    # Layer 1 must not import importlib at all (NFR-001 scan, review finding 6).
    module = _REAL_IMPORT(name, fromlist=("_",))
    if not fromlist:
        module = sys.modules[name.split(".")[0]]
    return _public_view(module) if module.__name__ in _VIEWED_MODULES else module


def safe_builtins() -> dict:
    """Fresh ``__builtins__`` mapping for one script run (``SAFE_BUILTIN_NAMES`` + import)."""
    return {
        **{name: getattr(builtins, name) for name in SAFE_BUILTIN_NAMES},
        "__import__": _guarded_import,
    }


def _script_error(exc: BaseException, path: Path, hint: str | None = None) -> Issue:
    """``SCRIPT_ERROR`` naming the last traceback frame inside the user script."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == str(path)]
    where = f" at line {frames[-1].lineno}: {frames[-1].line}" if frames else ""
    line_hint = f"line {frames[-1].lineno}" if frames else "the script"
    message = f"{type(exc).__name__}: {exc}"
    return error(
        "SCRIPT_ERROR",
        None,
        f"{path.name}{where} -> {message}",
        hint or f"fix {line_hint} (see the error above)",
    )


class ScriptTimeout(BaseException):
    """Raised inside an author script that ran longer than ``SCRIPT_TIMEOUT_S``.

    A ``BaseException`` so that the author's ``except Exception`` cannot swallow it.
    """


class _ExecutionLimits:
    """Context manager arming the script time limit and marking real Ctrl-C (design D-29).

    Time limit: ``SIGALRM`` via ``setitimer`` in the main thread -- the simplest mechanism that
    stops a pure-Python loop without moving the script (and the ``Machine`` it builds) into
    another process. On expiry the handler raises ``ScriptTimeout`` *and* installs a trace
    function that raises it again on every line executed in the script, so a script that
    swallows the first one with ``except BaseException: pass`` is stopped at the ``pass``;
    the timer keeps re-firing every ``_REFIRE_S`` because CPython drops a trace function
    that raises. A
    single long C call (``10 ** 10 ** 9``) only sees the signal when it returns: accepted
    (guard rail, NFR-006). Off the main thread (no signals there) the script runs unlimited.

    Interrupts: ``SIGINT`` gets a handler that records the interrupt before raising
    ``KeyboardInterrupt``, so ``load_machine`` can tell a real Ctrl-C (re-raised) from a
    script raising ``KeyboardInterrupt`` itself (feedback). Handlers, timer and trace function
    are restored on exit.
    """

    #: Interval (s) at which the timer re-fires (re-raising, re-tracing) after expiry.
    _REFIRE_S = 0.05

    def __init__(self, script: Path) -> None:
        self.interrupted = False
        self._script = str(script)
        self._active = False
        self._saved: tuple | None = None

    def _timeout(self) -> ScriptTimeout:
        return ScriptTimeout(f"the script did not finish within {SCRIPT_TIMEOUT_S:g} s")

    def _trace(self, frame, event, _arg):
        """Global and local trace function after expiry: fail every line of the script."""
        if frame.f_code.co_filename != self._script:
            return None  # library frames run untraced; control returns to a traced frame
        # Only "line": raising on the "exception" event of the timeout itself would happen
        # inside the script's try body (and be caught), and CPython unsets a trace function
        # that raises -- the re-firing timer re-installs it.
        if self._active and event == "line":
            raise self._timeout()
        return self._trace

    def _on_alarm(self, _signum, frame) -> None:
        if not self._active:
            return
        sys.settrace(self._trace)  # frames entered from now on
        while frame is not None:  # frames already running in the script
            if frame.f_code.co_filename == self._script:
                frame.f_trace_lines = True
                frame.f_trace = self._trace
            frame = frame.f_back
        raise self._timeout()

    def _on_interrupt(self, _signum, _frame) -> None:
        self.interrupted = True
        raise KeyboardInterrupt

    def __enter__(self) -> _ExecutionLimits:
        if threading.current_thread() is threading.main_thread():
            self._saved = (
                signal.signal(signal.SIGALRM, self._on_alarm),
                signal.signal(signal.SIGINT, self._on_interrupt),
                sys.gettrace(),
            )
            self._active = True
            signal.setitimer(signal.ITIMER_REAL, SCRIPT_TIMEOUT_S, self._REFIRE_S)
        return self

    def __exit__(self, *exc_info) -> None:
        # Deactivate first: an alarm landing between here and the disarm must not raise.
        self._active = False
        if self._saved is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._saved[0])
            signal.signal(signal.SIGINT, self._saved[1])
            sys.settrace(self._saved[2])


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
    limits = _ExecutionLimits(path)
    try:
        with limits:
            # compile with the real path so traceback frames can be matched to the script.
            exec(compile(source, str(path), "exec"), namespace)  # noqa: S102 - guarded above
    except RubeValidationError as exc:
        return None, [*exc.issues, _script_error(exc, path)]
    except ScriptTimeout as exc:
        line = _script_error(exc, path).hint.removeprefix("fix ").split(" (")[0]
        hint = f"the script must finish within {SCRIPT_TIMEOUT_S:g} s; look for an endless loop"
        return None, [_script_error(exc, path, f"{hint} around {line}")]
    except KeyboardInterrupt as exc:
        if limits.interrupted:  # a real Ctrl-C: the user wants out, not feedback
            raise
        return None, [_script_error(exc, path)]
    except BaseException as exc:  # author mistakes of any kind (SystemExit too) are feedback
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
