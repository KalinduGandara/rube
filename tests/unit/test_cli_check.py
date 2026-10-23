"""Unit tests for ``rube check`` (FR-017; A11 via the check path; FR-016)."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from rube import cli

ROOT = Path(__file__).resolve().parents[2]
A11 = ROOT / "examples" / "a11_disallowed_import.py"


def write(tmp_path, source):
    """Write a dedented script and return its path."""
    path = tmp_path / "machine.py"
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    return path


@pytest.fixture
def no_subprocess(monkeypatch):
    """Fail the test if anything tries to start a process (Blender must not launch)."""

    def boom(*args, **kwargs):
        raise AssertionError(f"subprocess started: {args}")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)


def test_check_valid_script_exits_0(tmp_path, capsys, no_subprocess):
    """FR-017: no errors -> exit 0 and an OK line."""
    path = write(
        tmp_path,
        "from rube import Ball, Machine\nmachine = Machine()\nmachine.add(Ball((0, 0, 1)))\n",
    )
    assert cli.main(["check", str(path)]) == 0
    assert "OK" in capsys.readouterr().out


def test_check_warnings_only_exits_0(tmp_path, capsys, no_subprocess):
    """FR-017: warnings are printed but do not fail the check."""
    path = write(
        tmp_path,
        """
        from rube import Ball, Block, Machine
        machine = Machine()
        machine.add(Ball((0, 0, 0.2), mass=0.05))
        machine.add(Block((0.13, 0, 0), size=(0.04, 0.4, 0.4), mass=10))
        """,
    )
    assert cli.main(["check", str(path)]) == 0
    assert "warning MASS_RATIO" in capsys.readouterr().out


def test_check_invalid_machine_prints_all_issues_exits_2(tmp_path, capsys, no_subprocess):
    """FR-017: errors -> every issue printed, exit 2."""
    path = write(
        tmp_path,
        """
        from rube import Ball, Machine
        machine = Machine(duration=100)
        machine.add(Ball((0, 0, 1), radius=-1, color="mauve"))
        """,
    )
    assert cli.main(["check", str(path)]) == 2
    out = capsys.readouterr().out
    assert "INVALID" in out
    assert out.count("error OUT_OF_RANGE") == 2 and "error INVALID_ARGUMENT" in out


def test_a11_disallowed_import_exits_2_without_blender(capsys, no_subprocess):
    """A11 / FR-016: `rube check examples/a11_disallowed_import.py` -> DISALLOWED_IMPORT, exit 2."""
    assert cli.main(["check", str(A11)]) == 2
    assert "DISALLOWED_IMPORT" in capsys.readouterr().out


def test_check_script_error_and_no_machine(tmp_path, capsys, no_subprocess):
    """FR-016/FR-017: SCRIPT_ERROR and NO_MACHINE exit 2."""
    assert cli.main(["check", str(write(tmp_path, "x = 1 / 0\n"))]) == 2
    assert "SCRIPT_ERROR" in capsys.readouterr().out
    assert cli.main(["check", str(write(tmp_path, "x = 1\n"))]) == 2
    assert "NO_MACHINE" in capsys.readouterr().out


def test_internal_error_exits_1(tmp_path, capsys, monkeypatch):
    """FR-018: a framework bug during check -> traceback on stderr, exit 1."""

    def broken(path):
        raise RuntimeError("framework bug")

    monkeypatch.setattr(cli, "check_script", broken)
    assert cli.main(["check", str(write(tmp_path, "x = 1\n"))]) == 1
    assert "framework bug" in capsys.readouterr().err


def test_console_entry_point_runs_check():
    """FR-017 / A11: the real command line (`python -m rube.cli check`) exits 2 on A11."""
    proc = subprocess.run(
        [sys.executable, "-m", "rube.cli", "check", str(A11)],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "DISALLOWED_IMPORT" in proc.stdout
