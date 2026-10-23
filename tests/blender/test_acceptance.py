"""Acceptance scenarios run end to end through ``rube run`` and the real Blender (SPEC 10.3).

Each test runs ``python -m rube.cli run <script> --out <tmp>`` (Blender found via
``RUBE_BLENDER`` or the default path, see ``conftest.py``) and asserts on ``report.json``.
Milestone M2 covers A1, A8, A11 and determinism (A1 twice, NFR-004); M3 adds A2-A5 and A9
(A5 twice); M4 adds A10, A12; M5 adds A6; M6 adds A7; later milestones add the other scenarios here.
"""

import json
import math
import os
import struct
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from rube.entities import DEFAULTS
from rube.generators import SpiralRamp
from rube.report import still_frames
from rube.script import load_machine

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"

pytestmark = pytest.mark.blender


def rube_run(script, out, blender_exe, timeout=300, extra=()):
    """Run ``rube run script --out out``; returns (exit code, report dict, combined output)."""
    env = {**os.environ, "RUBE_BLENDER": str(blender_exe)}
    proc = subprocess.run(
        [sys.executable, "-m", "rube.cli", "run", str(script), "--out", str(out),
         "--timeout", str(timeout), *extra],
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


#: Collision shape per entity type (SPEC section 5; FR-020).
SHAPES = {
    "Floor": "BOX", "Ball": "SPHERE", "Block": "BOX", "Domino": "BOX", "Ramp": "BOX",
    "LeverPlank": "BOX", "Fulcrum": "CONVEX_HULL", "SupportColumn": "CONVEX_HULL",
    "SpiralTrack": "MESH",
}  # fmt: skip


def expected_scene(out_dir, video=False):
    """Expected Blender settings of the machine in ``out_dir/spec.json``, from the spec text.

    Entity names and types come from the author's script (``spec.json``); every physics
    value comes from the ``DEFAULTS`` table, the shapes from SPEC section 5, the scene
    values from FR-019 / FR-007 / FR-014 - never from reading the built scene back.
    """
    spec = json.loads((out_dir / "spec.json").read_text())
    bodies = {}
    for ent in spec["entities"]:
        row = DEFAULTS[ent["type"]]
        mass = row.mass
        if mass is None:  # density-derived: Block and Domino are plain boxes
            mass = row.density * math.prod(ent["size"])
        # FR-007: dominoes deactivate when idle and start asleep unless pre-tilted.
        domino = ent["type"] == "Domino"
        bodies[ent["name"]] = {
            "type": ent["type"], "shape": SHAPES[ent["type"]], "dynamic": row.dynamic,
            "friction": row.friction, "restitution": row.bounciness,
            "linear_damping": row.linear_damping, "angular_damping": row.angular_damping,
            "margin": row.margin, "mass": mass,
            "use_deactivation": domino,
            "use_start_deactivated": domino and ent["tilt_deg"] == 0,
        }  # fmt: skip
    return {
        "fps": 24,
        "frame_end": 1 + math.ceil(spec["duration"] * 24),
        "bodies": bodies,
        "hinges": {c["name"]: {"disable_collisions": True} for c in spec["constraints"]},
        "camera": spec["camera"]["mode"],
        "video": video,
    }


def check_scene(out_dir, blender_exe, video=False):
    """Run ``check_scene.py`` inside Blender on ``out_dir/machine.blend`` (FR-019/020/...)."""
    expect = out_dir / "expected_scene.json"
    expect.write_text(json.dumps(expected_scene(out_dir, video)))
    proc = subprocess.run(
        [str(blender_exe), "-b", str(out_dir / "machine.blend"), "--python",
         str(ROOT / "tests" / "blender" / "check_scene.py"), "--", "--expect", str(expect)],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "checked: 0 failure(s)" in proc.stdout


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
    check_scene(tmp_path, blender_exe)  # FR-019, FR-020, FR-002


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


@pytest.mark.parametrize(
    "bodies",
    [
        # Review finding 1, repro 1: same size, same z -> four faces coplanar (BVH misses it).
        """
        machine.add(Block(position=(0, 0, 0), size=(0.4, 0.4, 0.4), name="a"))
        machine.add(Block(position=(0.1, 0, 0), size=(0.4, 0.4, 0.4), name="b"))
        """,
        # Repro 2: two dominoes 5 cm apart -> half inside each other, faces coplanar.
        """
        machine.add(Domino(position=(0, 0, 0), name="a"))
        machine.add(Domino(position=(0.05, 0, 0), name="b"))
        """,
    ],
    ids=["blocks", "dominoes"],
)
def test_overlap_coplanar_boxes(tmp_path, blender_exe, bodies):
    """FR-021 (T-019 review finding 1): box pairs whose faces are coplanar still overlap."""
    header = """
        from rube import Block, Domino, Machine
        machine = Machine(duration=1)
        """
    script = write_script(tmp_path, "machine.py", header + bodies)
    code, report, output = rube_run(script, tmp_path / "out", blender_exe)
    assert code == 2, output
    assert [i["entity"] for i in report["issues"] if i["code"] == "OVERLAP"] == ["a,b"]


def test_a2_ball_rolls_down_ramp(tmp_path, blender_exe):
    """A2 / FR-008: ball on a 20 deg ramp ends beyond ramp.bottom.x; no UNSTABLE warning."""
    code, report, output = rube_run(EXAMPLES / "a2_ball_down_ramp.py", tmp_path, blender_exe)
    assert code == 0, output
    assert report["status"] == "ok", report
    assert "UNSTABLE" not in {i["code"] for i in report["issues"]}
    # ramp.bottom = the ramp's `end` as handed to Blender in spec.json.
    spec = json.loads((tmp_path / "spec.json").read_text())
    ramp = next(e for e in spec["entities"] if e["type"] == "Ramp")
    ball = entity(report, "Ball_1")
    assert ball["final_position"][0] > ramp["end"][0]
    assert ball["left_bounds"] is False
    # Passive ramp is not in the entity records.
    assert [e["name"] for e in report["entities"]] == ["Ball_1"]


def fall_frames(report):
    """Domino name -> frame of its ``fell_over`` event."""
    return {e["entity"]: e["frame"] for e in report["events"] if e["event"] == "fell_over"}


def dominoes(report):
    """Domino entity records in chain (build) order."""
    return [e for e in report["entities"] if e["type"] == "Domino"]


def test_a3_straight_chain(tmp_path, blender_exe):
    """A3 / FR-011, FR-007: 20-domino chain, tilt_first_deg=10 -> all 20 fell over, and the
    fall frames strictly increase along the chain."""
    code, report, output = rube_run(EXAMPLES / "a3_domino_chain.py", tmp_path, blender_exe)
    assert code == 0, output
    assert report["status"] == "ok", report
    chain = dominoes(report)
    assert len(chain) == 20
    assert [d["name"] for d in chain if not d["fell_over"]] == []
    frames = fall_frames(report)
    ordered = [frames[d["name"]] for d in chain]
    assert all(a < b for a, b in zip(ordered, ordered[1:], strict=False)), ordered
    assert "UNSTABLE" not in {i["code"] for i in report["issues"]}
    check_scene(tmp_path, blender_exe)  # FR-007: Domino_1 tilted -> active, the rest asleep


def test_a4_curved_chain(tmp_path, blender_exe):
    """A4 / FR-011: chain along a 90 deg curve through 3 waypoints -> all dominoes fell over."""
    code, report, output = rube_run(EXAMPLES / "a4_curved_chain.py", tmp_path, blender_exe)
    assert code == 0, output
    assert report["status"] == "ok", report
    chain = dominoes(report)
    assert len(chain) >= 10
    assert [d["name"] for d in chain if not d["fell_over"]] == []
    assert "UNSTABLE" not in {i["code"] for i in report["issues"]}


def started_frames(report):
    """Entity name -> frame of its ``started_moving`` event."""
    return {e["entity"]: e["frame"] for e in report["events"] if e["event"] == "started_moving"}


def test_a5_ball_ramp_chain(tmp_path, blender_exe):
    """A5 / FR-008, FR-011: ball -> ramp -> untilted chain: the first domino starts moving
    after the ball does, and the last domino fell over."""
    code, report, output = rube_run(EXAMPLES / "a5_ball_ramp_chain.py", tmp_path, blender_exe)
    assert code == 0, output
    assert report["status"] == "ok", report
    assert "UNSTABLE" not in {i["code"] for i in report["issues"]}
    chain = dominoes(report)
    assert len(chain) >= 10
    started = started_frames(report)
    assert started["Ball_1"] < started[chain[0]["name"]]
    assert chain[-1]["fell_over"] is True


def test_a9_ball_ramp_chain_determinism(tmp_path, blender_exe):
    """A9 / NFR-004: A5 run twice -> every final position identical to 1e-6."""
    finals = []
    for run in ("first", "second"):
        script = EXAMPLES / "a5_ball_ramp_chain.py"
        code, report, output = rube_run(script, tmp_path / run, blender_exe)
        assert code == 0, output
        finals.append({e["name"]: e["final_position"] for e in report["entities"]})
    assert finals[0].keys() == finals[1].keys()
    assert len(finals[0]) >= 11  # the ball and every domino
    for name, first in finals[0].items():
        assert finals[1][name] == pytest.approx(first, abs=1e-6), name


def test_a10_ramp_chain_with_stills_under_60s(tmp_path, blender_exe):
    """A10 / NFR-005, FR-024: A5 with 6 stills takes < 60 s wall time; the 6 PNGs exist at
    absolute-resolvable paths named f_XXXX.png, are 960x540, and machine.blend is saved."""
    start = time.monotonic()
    code, report, output = rube_run(EXAMPLES / "a5_ball_ramp_chain.py", tmp_path, blender_exe)
    wall = time.monotonic() - start
    assert code == 0, output
    assert wall < 60, f"A5 with stills took {wall:.1f} s"
    frames = report["artifacts"]["frames"]
    assert len(frames) == 6
    timing = report["timing"]
    expected = [
        f"frames/f_{n:04d}.png" for n in still_frames(timing["frame_start"], timing["frame_end"])
    ]
    assert frames == expected
    assert expected[0].endswith("f_0001.png") and expected[-1].endswith(
        f"f_{timing['frame_end']:04d}.png"
    )
    for rel in frames:
        png = tmp_path / rel
        assert png.is_file() and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", png.read_bytes()[16:24])
        assert (width, height) == (960, 540)
    assert report["artifacts"]["video"] is None
    assert (tmp_path / "machine.blend").is_file()


def test_a12_follow_camera_video(tmp_path, blender_exe):
    """A12 / FR-014, FR-024: Camera.follow(ball) in A2 with --video -> video.mp4 (H.264) is
    rendered, and the ball projects inside the middle 50 % of the frame in every still."""
    code, report, output = rube_run(
        EXAMPLES / "a12_follow_camera.py", tmp_path, blender_exe, extra=["--video"]
    )
    assert code == 0, output
    assert report["status"] == "ok", report
    assert report["artifacts"]["video"] == "video.mp4"
    video = tmp_path / "video.mp4"
    assert video.is_file() and video.stat().st_size > 1000
    assert b"ftyp" in video.read_bytes()[:16]  # MP4 container
    timing = report["timing"]
    frames = still_frames(timing["frame_start"], timing["frame_end"])
    proc = subprocess.run(
        [str(blender_exe), "-b", str(tmp_path / "machine.blend"), "--python",
         str(ROOT / "tests" / "blender" / "check_camera.py"), "--",
         "--ball", "Ball_1", "--frames", *map(str, frames)],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.count(": x=") == len(frames)
    check_scene(tmp_path, blender_exe, video=True)  # FR-014 constraints, FR-024 H264


def test_a6_ball_through_spiral(tmp_path, blender_exe):
    """A6 / FR-009, FR-010: a ball spawned with spiral.ball_spawn(r) runs down a 2-turn
    spiral_ramp: it passes within 0.3 m of spiral.exit and never leaves the bounds."""
    script = EXAMPLES / "a6_spiral.py"
    code, report, output = rube_run(script, tmp_path, blender_exe)
    assert code == 0, output
    assert report["status"] == "ok", report
    assert "UNSTABLE" not in {i["code"] for i in report["issues"]}
    ball = entity(report, "Ball_1")
    assert ball["left_bounds"] is False
    assert not any(e["event"] == "left_bounds" for e in report["events"])
    # spiral.exit from the same script, evaluated in system Python (pure Layer 1).
    machine, issues = load_machine(script)
    assert issues == []
    (spiral,) = [g for g in machine.groups if isinstance(g, SpiralRamp)]
    exit_point = spiral.exit
    proc = subprocess.run(
        [str(blender_exe), "-b", str(tmp_path / "machine.blend"), "--python",
         str(ROOT / "tests" / "blender" / "check_trajectory.py"), "--",
         "--object", "Ball_1", "--point", *map(str, exit_point)],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("min_distance="))
    min_distance = float(line.split()[0].split("=")[1])
    assert min_distance < 0.3, line


def test_a7_lever(tmp_path, blender_exe):
    """A7 / FR-012: a ball dropped on one end of a Lever -> the other end rises >= 0.1 m.

    The report has no plank end height (schema stays SPEC section 9.2), so it is derived:
    the plank only rotates about the hinge, and its final tilt theta lifts the far end by
    (length / 2) * sin(theta) above its start (length 2.0 m, level at the start).
    """
    code, report, output = rube_run(EXAMPLES / "a7_lever.py", tmp_path, blender_exe)
    assert code == 0, output
    assert report["status"] == "ok", report
    assert "OVERLAP" not in {i["code"] for i in report["issues"]}
    plank = entity(report, "LeverPlank_1")
    rise = 1.0 * math.sin(math.radians(plank["final_tilt_deg"]))
    assert rise >= 0.1, plank
    # The hinge keeps the plank on its pivot: its center stays within a plank thickness.
    assert plank["final_position"][2] == pytest.approx(0.525, abs=0.3)
    assert abs(plank["final_position"][0]) < 0.05 and abs(plank["final_position"][1]) < 0.05
    assert entity(report, "Ball_1")["left_bounds"] is False
    check_scene(tmp_path, blender_exe)  # FR-012: HINGE with disable_collisions


def test_overlap_skips_hinged_pairs_with_collisions_disabled(tmp_path, blender_exe):
    """FR-012 / FR-021 (T-017): two overlapping blocks joined by a Hinge are an OVERLAP
    only when the hinge keeps their collisions enabled."""
    template = """
        from rube import Block, Machine
        from rube.entities import Hinge
        machine = Machine(duration=1)
        a = machine.add(Block(position=(0, 0, 1), size=(0.4, 0.4, 0.4), name="a"))
        # Offset in y/z and narrower so no faces are coplanar (BVH ignores coplanar contact).
        b = machine.add(Block(position=(0.2, 0.05, 1.1), size=(0.4, 0.3, 0.4), name="b"))
        machine._register(Hinge(a, b, (0.1, 0, 1.2), (0, 1, 0), disable_collisions={flag}))
        """
    code, report, output = rube_run(
        write_script(tmp_path, "off.py", template.format(flag=True)), tmp_path / "off", blender_exe
    )
    assert code == 0 and "OVERLAP" not in {i["code"] for i in report["issues"]}, output
    code, report, output = rube_run(
        write_script(tmp_path, "on.py", template.format(flag=False)), tmp_path / "on", blender_exe
    )
    assert code == 2, output
    assert [i["entity"] for i in report["issues"] if i["code"] == "OVERLAP"] == ["a,b"]
