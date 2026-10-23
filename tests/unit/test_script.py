"""Unit tests for ``rube.script`` (FR-016: AST import guard, NO_MACHINE, SCRIPT_ERROR; NFR-006)."""

import os
import signal
import textwrap
import threading
import time

import pytest

import rube.script
from rube.machine import Machine
from rube.script import check_script, check_source, load_machine


def write(tmp_path, source, name="machine.py"):
    """Write a dedented script to ``tmp_path`` and return its path."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    return path


GOOD = """
    import math
    import random
    import rube
    import rube.entities
    from math import pi
    from rube import Ball, Machine

    random.seed(1)
    machine = Machine(duration=2)
    machine.add(Ball((0, 0, 1 + math.sin(pi))))
"""


def test_allowed_imports_pass():
    """FR-016: imports of rube (incl. submodules), math and random are allowed."""
    assert check_source(textwrap.dedent(GOOD), "m.py") == []


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        ("import os", "os"),
        ("import os.path", "os.path"),
        ("from os import path", "os"),
        ("import numpy as np", "numpy"),
        ("from . import helper", "relative"),
        ("import rubex", "rubex"),
        ("x = __import__('os')", "__import__"),
        ("eval('1 + 1')", "eval"),
        ("exec('x = 1')", "exec"),
        ("f = open('secrets.txt')", "open"),
        ("def f():\n    import subprocess\n", "subprocess"),
        # Review finding 3: non-public rube modules, escape-hatch names, dunder attributes.
        ("import rube.cli", "rube.cli"),
        ("from rube.cli import subprocess", "rube.cli"),
        ("from rube import cli", "cli"),
        ("from rube import script as s", "script"),
        ("import rube.report", "rube.report"),
        ("from rube.blender.build import BuildContext", "rube.blender.build"),
        ("import rube.blender", "rube.blender"),
        ("b = __builtins__", "__builtins__"),
        ("f = getattr(1, 'real')", "getattr"),
        ("setattr(x, 'y', 1)", "setattr"),
        ("delattr(x, 'y')", "delattr"),
        ("g = globals()", "globals"),
        ("g = locals()", "locals"),
        ("g = vars()", "vars"),
        ("c = compile('1', 'f', 'eval')", "compile"),
        ("breakpoint()", "breakpoint"),
        ("x = input()", "input"),
        ("f = (1).__class__", "__class__"),
        ("g = (x for x in ()).gi_frame", "gi_frame"),
    ],
)
def test_disallowed_imports_and_names(source, needle):
    """FR-016: other imports and __import__/eval/exec/open -> DISALLOWED_IMPORT with the line."""
    (issue,) = check_source(source, "m.py")
    assert issue.code == "DISALLOWED_IMPORT" and issue.severity == "error"
    assert needle in issue.message and "line" in issue.message
    assert "rube" in issue.hint and "math" in issue.hint


BYPASSES = {
    # Review finding 3: all four passed `rube check` before the fix.
    "cli_os": "import rube.cli\nrube.cli.os.environ['RUBE_PWNED'] = '1'\n",
    "cli_subprocess": "from rube.cli import subprocess\nsubprocess.run(['echo', 'pwned'])\n",
    "builtins_import": "__builtins__['__imp' + 'ort__']('os')\n",
    "init_globals": "from rube import Machine\ng = Machine.__init__.__globals__\n",
}


@pytest.mark.parametrize("source", BYPASSES.values(), ids=BYPASSES.keys())
def test_guard_bypasses_are_rejected(tmp_path, source):
    """FR-016 (T-019 review finding 3): the reviewer's bypasses are DISALLOWED_IMPORT, unrun."""
    machine, issues = load_machine(write(tmp_path, source + "raise RuntimeError('ran')\n"))
    assert machine is None and issues
    assert {i.code for i in issues} == {"DISALLOWED_IMPORT"}


def test_public_rube_modules_allowed():
    """FR-016: the public API modules stay importable (examples and tests use them)."""
    source = textwrap.dedent(
        """
        import rube.entities
        from rube.entities import Hinge
        from rube.generators import SpiralRamp
        from rube.camera import Camera
        from rube.machine import Machine
        from rube.vec import Vec3
        from rube.geometry import catmull_rom
        from rube.errors import Issue
        from rube import *
        machine._register(None)
        """
    )
    assert check_source(source, "m.py") == []


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        # `rube` is a real package whose attributes include every submodule already loaded
        # (the CLI loads rube.cli and rube.script), so `import rube` must not expose them.
        ("import rube\nx = rube.cli\n", "cli"),
        ("import rube\nx = rube.script\n", "script"),
        # `random` keeps `os` as the private attribute `_os`.
        ("import random\nx = random._os\n", "_os"),
        # Only the curated builtins exist at run time.
        ("x = type(1)\n", "type"),
        ("x = memoryview(b'')\n", "memoryview"),
    ],
)
def test_runtime_namespace_is_curated(tmp_path, source, needle):
    """FR-016: modules and builtins the guard cannot see statically are absent at run time."""
    import rube.cli  # noqa: F401 - make sure the rube package carries the attribute

    machine, (issue,) = load_machine(write(tmp_path, source))
    assert machine is None and issue.code == "SCRIPT_ERROR" and needle in issue.message


def test_curated_builtins_cover_normal_scripts(tmp_path):
    """FR-016: the builtins a normal machine script uses are all available."""
    path = write(
        tmp_path,
        """
        import math
        from rube import Ball, Machine, Vec3

        class Spacing:
            def __init__(self, step):
                self.step = step

            @property
            def double(self):
                return 2 * self.step

        xs = [round(abs(x) * Spacing(0.5).double, 3) for x in range(-2, 3)]
        pairs = list(zip(sorted(set(xs)), reversed(tuple(xs))))
        total = sum(min(a, b) + max(a, b) for a, b in pairs) + len(dict(a=1)) + pow(2, 1)
        for i, (a, b) in enumerate(pairs):
            assert isinstance(a, (int, float)) and bool(str(b)) and all([i >= 0]) and any([1])
        try:
            float("nope")
        except ValueError as exc:
            message = f"{exc!r} {int('3')} {math.pi:.2f} {divmod(7, 2)} {hasattr(Vec3, 'x')}"
        print(message, total, frozenset(), list(map(abs, filter(None, [0, -1]))), next(iter([1])))
        machine = Machine(duration=2)
        machine.add(Ball((0, 0, 1)))
        """,
    )
    machine, issues = load_machine(path)
    assert issues == [] and isinstance(machine, Machine)


def test_guard_collects_all_violations():
    """FR-013/FR-016: every violation is reported at once."""
    issues = check_source("import os\nimport sys\nopen('x')\n", "m.py")
    assert [i.code for i in issues] == ["DISALLOWED_IMPORT"] * 3
    assert "line 2" in issues[1].message


def test_disallowed_script_is_never_executed(tmp_path):
    """FR-016: a script failing the guard is not executed (its runtime error never happens)."""
    path = write(tmp_path, "import os\nraise RuntimeError('executed!')\n")
    machine, issues = load_machine(path)
    assert machine is None
    assert [i.code for i in issues] == ["DISALLOWED_IMPORT"]


def test_syntax_error_is_script_error(tmp_path):
    """FR-016: a syntax error -> SCRIPT_ERROR with its line."""
    path = write(tmp_path, "from rube import Machine\nmachine = Machine(\n")
    machine, (issue,) = load_machine(path)
    assert machine is None and issue.code == "SCRIPT_ERROR"
    assert "line" in issue.message


def test_runtime_error_reports_user_line(tmp_path):
    """FR-016: an exception -> SCRIPT_ERROR naming the failing line in the user script."""
    path = write(
        tmp_path,
        """
        from rube import Machine
        machine = Machine()
        machine.add((0, 0, 1))
        """,
    )
    machine, (issue,) = load_machine(path)
    assert machine is None and issue.code == "SCRIPT_ERROR"
    assert "line 3" in issue.message and "TypeError" in issue.message
    assert "machine.add((0, 0, 1))" in issue.message


def test_anchor_validation_error_surfaces_underlying_issue(tmp_path):
    """FR-016 / D-15: an anchor on a broken entity reports the entity issue plus SCRIPT_ERROR."""
    path = write(
        tmp_path,
        """
        from rube import Ball, Machine
        machine = Machine()
        b = Ball((0, 0), radius=0.1)
        top = b.bottom
        """,
    )
    _, issues = load_machine(path)
    assert {i.code for i in issues} == {"INVALID_ARGUMENT", "SCRIPT_ERROR"}
    assert any("line 4" in i.message for i in issues if i.code == "SCRIPT_ERROR")


@pytest.mark.parametrize("body", ["x = 1\n", "from rube import Ball\nmachine = Ball((0, 0, 1))\n"])
def test_no_machine(tmp_path, body):
    """FR-016: no top-level `machine` of type Machine -> NO_MACHINE."""
    machine, (issue,) = load_machine(write(tmp_path, body))
    assert machine is None and issue.code == "NO_MACHINE" and "machine" in issue.hint


def test_check_script_loads_and_validates(tmp_path):
    """FR-016/FR-017: check_script returns the machine plus its validation issues."""
    machine, issues = check_script(write(tmp_path, GOOD))
    assert isinstance(machine, Machine) and issues == []
    bad = write(tmp_path, "from rube import Machine\nmachine = Machine(duration=99)\n", "b.py")
    machine, issues = check_script(bad)
    assert isinstance(machine, Machine) and [i.code for i in issues] == ["OUT_OF_RANGE"]


def test_missing_file_is_script_error(tmp_path):
    """FR-016: an unreadable script path -> SCRIPT_ERROR (not a crash)."""
    machine, (issue,) = load_machine(tmp_path / "nope.py")
    assert machine is None and issue.code == "SCRIPT_ERROR" and "nope.py" in issue.message


def test_guard_documented_as_guard_rail_not_sandbox():
    """NFR-006: the module states the guard is a guard rail, not a sandbox."""
    doc = rube.script.__doc__.lower()
    assert "guard rail" in doc and "not a sandbox" in doc


HANG = "while True:\n    pass\n"
#: Swallows the first timeout signal; the limit must keep firing until the script stops.
STUBBORN_HANG = """
while True:
    try:
        while True:
            pass
    except BaseException:
        pass
"""


@pytest.mark.parametrize("source", [HANG, STUBBORN_HANG], ids=["loop", "swallowing"])
def test_script_time_limit(tmp_path, monkeypatch, source):
    """FR-016 (T-019 review finding 2): a script running past the limit -> SCRIPT_ERROR."""
    monkeypatch.setattr(rube.script, "SAFE_BUILTIN_NAMES", (*SAFE_NAMES, "BaseException"))
    monkeypatch.setattr(rube.script, "SCRIPT_TIMEOUT_S", 0.2)
    start = time.monotonic()
    machine, (issue,) = load_machine(write(tmp_path, source))
    assert time.monotonic() - start < 5
    assert machine is None and issue.code == "SCRIPT_ERROR"
    assert "0.2 s" in issue.message and "line" in issue.message


def test_script_time_limit_is_a_fixed_30_s_and_disarmed_after(tmp_path):
    """FR-016: the limit is the module constant 30 s; no timer is left running afterwards."""
    assert rube.script.SCRIPT_TIMEOUT_S == 30
    load_machine(write(tmp_path, GOOD))
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGALRM) in (signal.SIG_DFL, signal.SIG_IGN, None)


SAFE_NAMES = rube.script.SAFE_BUILTIN_NAMES


@pytest.mark.parametrize(
    "raised", ["KeyboardInterrupt", "SystemExit(3)", "GeneratorExit", "Custom"]
)
def test_base_exceptions_are_script_errors(tmp_path, monkeypatch, raised):
    """FR-016 (T-019 review finding 4): any BaseException from the script -> SCRIPT_ERROR.

    The curated builtins do not even offer these names, so they are added here to prove the
    catch itself does not depend on that curation.
    """
    extra = ("KeyboardInterrupt", "SystemExit", "GeneratorExit", "BaseException")
    monkeypatch.setattr(rube.script, "SAFE_BUILTIN_NAMES", (*SAFE_NAMES, *extra))
    source = f"class Custom(BaseException):\n    pass\n\nraise {raised}\n"
    machine, (issue,) = load_machine(write(tmp_path, source))
    assert machine is None and issue.code == "SCRIPT_ERROR" and "line 4" in issue.message


def test_real_interrupt_propagates(tmp_path, monkeypatch):
    """FR-016: a real Ctrl-C while the script runs is not swallowed as SCRIPT_ERROR."""
    monkeypatch.setattr(rube.script, "SCRIPT_TIMEOUT_S", 10)
    timer = threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGINT))
    timer.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            load_machine(write(tmp_path, HANG))
    finally:
        timer.cancel()
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
