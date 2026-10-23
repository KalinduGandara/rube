"""Acceptance scenarios run end to end through ``rube run`` and the real Blender (SPEC 10.3).

Each test runs ``python -m rube.cli run <script> --out <tmp>`` (Blender found via
``RUBE_BLENDER`` or the default path, see ``conftest.py``) and asserts on ``report.json``.
Milestone M2 covers A1, A8, A11 and determinism (A1 twice, NFR-004); later milestones add
the other scenarios here.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"

pytestmark = pytest.mark.blender


def rube_run(script, out, blender_exe, timeout=300):
    """Run ``rube run script --out out``; returns (exit code, report dict, combined output)."""
    env = {**os.environ, "RUBE_BLENDER": str(blender_exe)}
    proc = subprocess.run(
        [sys.executable, "-m", "rube.cli", "run", str(script), "--out", str(out),
         "--timeout", str(timeout)],
        capture_output=True, text=True, timeout=timeout + 60, env=env,
    )  # fmt: skip
    report = json.loads((Path(out) / "report.json").read_text())
    return proc.returncode, report, proc.stdout + proc.stderr


def entity(report, name):
    """The report's entity record called ``name``."""
    return next(e for e in report["entities"] if e["name"] == name)


def write_script(tmp_path, name, source):
    """Write a throwaway author script into ``tmp_path``."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(source))
    return path


def test_a1_ball_drop(tmp_path, blender_exe):
    """A1: ball dropped from 1 m -> ok; final z = radius +- 0.01; at rest; no warnings."""
    code, report, output = rube_run(EXAMPLES / "a1_ball_drop.py", tmp_path, blender_exe)
    assert code == 0, output
    assert report["status"] == "ok", report
    assert report["issues"] == []
    ball = entity(report, "Ball_1")
    assert ball["final_position"][2] == pytest.approx(0.1, abs=0.01)
    assert ball["at_rest_at_end"] is True
    assert ball["left_bounds"] is False
    assert [e["event"] for e in report["events"]] == ["started_moving"]
    # Passive bodies (the floor) are omitted from the entity records (FR-025).
    assert [e["name"] for e in report["entities"]] == ["Ball_1"]
    assert report["blender_version"].startswith("5.2")
    assert report["artifacts"]["blend"] == "machine.blend"
    assert (tmp_path / "machine.blend").is_file()


def test_a1_determinism(tmp_path, blender_exe):
    """A9 precursor / NFR-004: A1 run twice -> final positions identical to 1e-6."""
    finals = []
    for run in ("first", "second"):
        code, report, output = rube_run(EXAMPLES / "a1_ball_drop.py", tmp_path / run, blender_exe)
        assert code == 0, output
        finals.append({e["name"]: e["final_position"] for e in report["entities"]})
    assert finals[0].keys() == finals[1].keys()
    for name, first in finals[0].items():
        assert finals[1][name] == pytest.approx(first, abs=1e-6), name


def test_a8_ball_intersecting_block(tmp_path, blender_exe):
    """A8 / FR-021: ball inside a block -> invalid, OVERLAP naming both, nothing baked."""
    code, report, output = rube_run(EXAMPLES / "a8_ball_in_block.py", tmp_path, blender_exe)
    assert code == 2, output
    assert report["status"] == "invalid"
    overlaps = [i for i in report["issues"] if i["code"] == "OVERLAP"]
    assert len(overlaps) == 1
    assert set(overlaps[0]["entity"].split(",")) == {"Ball_1", "Block_1"}
    assert overlaps[0]["severity"] == "error" and overlaps[0]["hint"]
    # No bake -> no sampling: no entity records and no events.
    assert report["entities"] == [] and report["events"] == []


def test_a11_disallowed_import_never_starts_blender(tmp_path, blender_exe):
    """A11 / FR-016: `import os` -> DISALLOWED_IMPORT, exit 2, Blender not launched."""
    script = EXAMPLES / "a11_disallowed_import.py"
    code, report, output = rube_run(script, tmp_path, blender_exe)
    assert code == 2, output
    assert report["status"] == "invalid"
    assert [i["code"] for i in report["issues"]] == ["DISALLOWED_IMPORT"]
    assert report["blender_version"] is None
    assert not (tmp_path / "blender.log").exists()
    assert not (tmp_path / "spec.json").exists()


def test_overlap_containment_and_near_misses(tmp_path, blender_exe):
    """FR-021: a body fully inside another is OVERLAP; bodies whose boxes overlap but whose
    shapes do not, and bodies resting with clearance on the floor, are not."""
    script = write_script(
        tmp_path,
        "machine.py",
        """
        from rube import Ball, Block, Domino, Machine
        machine = Machine(duration=1)
        big = machine.add(Block(position=(0, 0, 0), size=(0.6, 0.6, 0.6), name="big"))
        machine.add(Ball(center=(0, 0, 0.3), radius=0.05, name="inside"))
        # Near the block's top corner: AABBs overlap, the sphere does not touch the box.
        machine.add(Ball(center=(0.37, 0.37, 0.67), radius=0.1, name="corner"))
        machine.add(Domino(position=(2, 0, 0), name="standing"))
        machine.add(Ball(center=(-2, 0, 0.102), radius=0.1, name="resting"))
        """,
    )
    code, report, output = rube_run(script, tmp_path / "out", blender_exe)
    assert code == 2, output
    assert [i["entity"] for i in report["issues"] if i["code"] == "OVERLAP"] == ["big,inside"]
