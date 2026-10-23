"""Unit tests for ``rube.script`` (FR-016: AST import guard, NO_MACHINE, SCRIPT_ERROR; NFR-006)."""

import textwrap

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
    ],
)
def test_disallowed_imports_and_names(source, needle):
    """FR-016: other imports and __import__/eval/exec/open -> DISALLOWED_IMPORT with the line."""
    (issue,) = check_source(source, "m.py")
    assert issue.code == "DISALLOWED_IMPORT" and issue.severity == "error"
    assert needle in issue.message and "line" in issue.message
    assert "rube" in issue.hint and "math" in issue.hint


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
