"""Unit tests for ``rube run`` with a fake Blender executable (FR-018, FR-025, T-010).

The fake is a small Python script (shebang = this interpreter) installed via ``RUBE_BLENDER``.
Its behaviour is chosen with the ``FAKE_BLENDER_MODE`` env var:

- ``ok`` / ``bake_failed``: write ``report.json`` with that status next to ``--spec``.
- ``hang``: start a grandchild ``sleep`` (pid written to a file), then sleep forever.
- ``noreport``: print to stderr and exit 1 without writing a report.

Every invocation records its argv as JSON in ``FAKE_BLENDER_ARGV`` so tests can check the
command line and whether Blender was launched at all.
"""

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

import rube.script
from rube import cli
from rube.report import read_report

FAKE_SOURCE = """\
#!{python}
import json, os, subprocess, sys, time
from pathlib import Path

argv = sys.argv[1:]
Path(os.environ["FAKE_BLENDER_ARGV"]).write_text(json.dumps(argv))
mode = os.environ["FAKE_BLENDER_MODE"]
args = argv[argv.index("--") + 1:]
out = Path(args[args.index("--out") + 1])
spec = json.loads(Path(args[args.index("--spec") + 1]).read_text())
print("fake blender starting", spec["name"])
if mode in ("ok", "bake_failed"):
    report = {{"status": mode, "issues": [], "timing": None, "entities": [], "events": [],
              "artifacts": {{"frames": [], "video": None, "blend": None}},
              "blender_version": "fake", "rube_version": "0.1.0", "elapsed_s": 0.0}}
    (out / "report.json").write_text(json.dumps(report))
elif mode == "hang":
    child = subprocess.Popen(["sleep", "60"])
    Path(os.environ["FAKE_BLENDER_CHILD"]).write_text(str(child.pid))
    time.sleep(60)
elif mode == "noreport":
    print("Error: fake Blender crashed", file=sys.stderr)
    sys.exit(1)
"""

VALID = """
from rube import Ball, Machine
machine = Machine(name="fake_test", duration=2)
machine.add(Ball((0, 0, 1)))
"""


@pytest.fixture
def fake_blender(tmp_path, monkeypatch):
    """Install the fake Blender; returns a function ``mode -> argv file path``."""
    exe = tmp_path / "fake_blender.py"
    exe.write_text(FAKE_SOURCE.format(python=sys.executable))
    exe.chmod(0o755)
    argv_file = tmp_path / "fake_argv.json"
    monkeypatch.setenv("RUBE_BLENDER", str(exe))
    monkeypatch.setenv("FAKE_BLENDER_ARGV", str(argv_file))
    monkeypatch.setenv("FAKE_BLENDER_CHILD", str(tmp_path / "fake_child.pid"))

    def use(mode):
        monkeypatch.setenv("FAKE_BLENDER_MODE", mode)
        return argv_file

    return use


def write_script(tmp_path, source=VALID):
    """Write an author script and return its path."""
    path = tmp_path / "machine.py"
    path.write_text(textwrap.dedent(source))
    return path


def run(tmp_path, *extra):
    """``rube run machine.py --out tmp/out`` in-process; returns (exit code, out dir)."""
    out = tmp_path / "out"
    code = cli.main(["run", str(tmp_path / "machine.py"), "--out", str(out), *extra])
    return code, out


def test_ok_run_exits_0_and_passes_spec(tmp_path, fake_blender, capsys):
    """FR-018: valid script -> spec.json written, Blender command line per design 5, exit 0."""
    argv_file = fake_blender("ok")
    write_script(tmp_path)
    code, out = run(tmp_path)
    assert code == 0
    argv = json.loads(argv_file.read_text())
    assert argv[:4] == ["-b", "--factory-startup", "--python-exit-code", "1"]
    assert argv[4] == "--python" and argv[5].endswith(
        os.path.join("rube", "blender", "bootstrap.py")
    )
    assert Path(argv[5]).is_file()
    tail = argv[argv.index("--") + 1 :]
    assert tail == ["--spec", str((out / "spec.json").resolve()), "--out", str(out.resolve())]
    spec = json.loads((out / "spec.json").read_text())
    assert spec["name"] == "fake_test" and spec["format"] == 1
    report = read_report(out / "report.json")
    assert report["status"] == "ok"
    assert report["elapsed_s"] > 0  # CLI wall time replaces Blender's (design D-20)
    assert "fake blender starting" in (out / "blender.log").read_text()
    assert "ok" in capsys.readouterr().out


def test_video_flag_is_forwarded(tmp_path, fake_blender):
    """FR-018: --video is passed through to bootstrap."""
    argv_file = fake_blender("ok")
    write_script(tmp_path)
    code, _ = run(tmp_path, "--video")
    assert code == 0
    assert json.loads(argv_file.read_text())[-1] == "--video"


def test_bake_failed_status_exits_3(tmp_path, fake_blender):
    """FR-018: Blender report status bake_failed -> exit 3."""
    fake_blender("bake_failed")
    write_script(tmp_path)
    code, out = run(tmp_path)
    assert code == 3
    assert read_report(out / "report.json")["status"] == "bake_failed"


def test_timeout_kills_process_group_and_exits_4(tmp_path, fake_blender):
    """FR-018: on timeout the whole process group is killed; status timeout, TIMEOUT, exit 4."""
    fake_blender("hang")
    write_script(tmp_path)
    start = time.monotonic()
    code, out = run(tmp_path, "--timeout", "2")
    assert code == 4
    assert time.monotonic() - start < 20
    report = read_report(out / "report.json")
    assert report["status"] == "timeout"
    assert [i["code"] for i in report["issues"]] == ["TIMEOUT"]
    assert report["timing"]["frame_end"] == 1 + 48
    child = int((tmp_path / "fake_child.pid").read_text())
    for _ in range(50):  # the grandchild was in the same group: it must be gone (or a zombie)
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        if _is_zombie(child):
            break
        time.sleep(0.1)
    else:
        os.kill(child, signal.SIGKILL)
        pytest.fail("grandchild process survived the timeout kill")


def _is_zombie(pid):
    """True if ``pid`` is a zombie (killed but not yet reaped by its dead parent's reaper)."""
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return state.stdout.strip().startswith("Z")


def test_missing_report_is_internal_error_exit_1(tmp_path, fake_blender):
    """FR-018/FR-025: Blender exits without a report -> internal_error with the log tail."""
    fake_blender("noreport")
    write_script(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    # A stale report from an earlier run must not be mistaken for this run's (design D-20).
    (out / "report.json").write_text(json.dumps({"status": "ok"}))
    code, out = run(tmp_path)
    assert code == 1
    report = read_report(out / "report.json")
    assert report["status"] == "internal_error"
    assert "fake Blender crashed" in report["traceback"]
    assert "exit code 1" in report["traceback"]


def test_invalid_script_never_launches_blender(tmp_path, fake_blender):
    """FR-018 / A11: validation errors -> report invalid, exit 2, Blender not started."""
    argv_file = fake_blender("ok")
    write_script(tmp_path, "import os\nfrom rube import Machine\nmachine = Machine()\n")
    code, out = run(tmp_path)
    assert code == 2
    assert not argv_file.exists()
    report = read_report(out / "report.json")
    assert report["status"] == "invalid"
    assert report["issues"][0]["code"] == "DISALLOWED_IMPORT"
    assert report["blender_version"] is None
    assert not (out / "spec.json").exists()


def test_invalid_machine_report_has_timing(tmp_path, fake_blender):
    """FR-018: a loaded but invalid machine -> invalid report with timing and all issues."""
    argv_file = fake_blender("ok")
    write_script(
        tmp_path,
        "from rube import Ball, Machine\nmachine = Machine(duration=2)\n"
        "machine.add(Ball((0, 0, 1), radius=-1))\n",
    )
    code, out = run(tmp_path)
    assert code == 2 and not argv_file.exists()
    report = read_report(out / "report.json")
    assert report["timing"]["duration_s"] == 2
    assert any(i["code"] == "OUT_OF_RANGE" for i in report["issues"])


def test_blender_not_found_is_internal_error(tmp_path, monkeypatch):
    """FR-018: a missing Blender binary -> internal_error naming RUBE_BLENDER, exit 1."""
    monkeypatch.setenv("RUBE_BLENDER", str(tmp_path / "no_such_blender"))
    write_script(tmp_path)
    code, out = run(tmp_path)
    assert code == 1
    report = read_report(out / "report.json")
    assert report["status"] == "internal_error"
    assert "RUBE_BLENDER" in report["traceback"]


def test_default_blender_path(monkeypatch):
    """FR-018: RUBE_BLENDER wins; otherwise the macOS default path from SPEC 1."""
    monkeypatch.delenv("RUBE_BLENDER", raising=False)
    assert cli.find_blender() == "/Applications/Blender.app/Contents/MacOS/Blender"
    monkeypatch.setenv("RUBE_BLENDER", "/opt/blender")
    assert cli.find_blender() == "/opt/blender"


def test_framework_bug_still_writes_report(tmp_path, fake_blender, monkeypatch):
    """FR-025: a framework bug inside `rube run` -> internal_error report + exit 1."""
    fake_blender("ok")
    write_script(tmp_path)

    def broken(*args, **kwargs):
        raise RuntimeError("framework bug in run")

    monkeypatch.setattr(cli, "check_script", broken)
    code, out = run(tmp_path)
    assert code == 1
    report = read_report(out / "report.json")
    assert report["status"] == "internal_error"
    assert "framework bug in run" in report["traceback"]


def test_non_numeric_duration_is_invalid_not_internal_error(tmp_path, fake_blender):
    """FR-018: Machine(duration="long") -> invalid report (timing null), exit 2."""
    fake_blender("ok")
    write_script(tmp_path, "from rube import Machine\nmachine = Machine(duration='long')\n")
    code, out = run(tmp_path)
    assert code == 2
    report = read_report(out / "report.json")
    assert report["status"] == "invalid" and report["timing"] is None
    assert report["issues"][0]["code"] == "INVALID_ARGUMENT"


def test_script_time_limit_writes_invalid_report(tmp_path, fake_blender, monkeypatch):
    """FR-016/FR-018 (T-019 review finding 2): a hanging script -> invalid report, exit 2."""
    argv_file = fake_blender("ok")
    monkeypatch.setattr(rube.script, "SCRIPT_TIMEOUT_S", 0.2)
    write_script(tmp_path, "while True:\n    pass\n")
    code, out = run(tmp_path, "--timeout", "1")
    assert code == 2
    report = read_report(out / "report.json")
    assert report["status"] == "invalid"
    assert [i["code"] for i in report["issues"]] == ["SCRIPT_ERROR"]
    assert not argv_file.exists()  # Blender never started
    assert cli.main(["check", str(tmp_path / "machine.py")]) == 2


def test_script_raising_keyboard_interrupt_writes_report(tmp_path, fake_blender):
    """FR-016 (T-019 review finding 4): the reviewer's `raise KeyboardInterrupt` repro."""
    fake_blender("ok")
    write_script(tmp_path, "raise KeyboardInterrupt\n")
    code, out = run(tmp_path)
    assert code == 2
    assert read_report(out / "report.json")["issues"][0]["code"] == "SCRIPT_ERROR"


@pytest.mark.parametrize("target", ["check_script", "_launch"])
def test_interrupt_still_writes_report(tmp_path, fake_blender, monkeypatch, target):
    """FR-016 (T-019 review finding 4): Ctrl-C during `rube run` -> internal_error report
    ("interrupted") is written, then the interrupt propagates."""
    fake_blender("ok")
    write_script(tmp_path)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, target, interrupted)
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path)
    report = read_report(tmp_path / "out" / "report.json")
    assert report["status"] == "internal_error" and "interrupted" in report["traceback"]


#: Artifacts a run produces (FR-018/FR-024); stale copies must not survive a re-run.
KNOWN_ARTIFACTS = ("spec.json", "blender.log", "report.json", "video.mp4", "machine.blend")


def test_rerun_removes_stale_artifacts_only(tmp_path, fake_blender):
    """FR-018 (T-019 review finding 7): a re-run deletes the known artifacts of an earlier
    run (frames/ included) and nothing else in the output directory."""
    argv_file = fake_blender("ok")
    out = tmp_path / "out"
    (out / "frames").mkdir(parents=True)
    (out / "frames" / "f_0001.png").write_bytes(b"old")
    for name in KNOWN_ARTIFACTS:
        (out / name).write_text("old")
    (out / "notes.txt").write_text("mine")
    (out / "mine").mkdir()
    (out / "mine" / "frames").mkdir()
    write_script(tmp_path, "from rube import Machine\nmachine = Machine(duration=99)\n")
    code, _ = run(tmp_path)
    assert code == 2 and not argv_file.exists()
    left = sorted(p.relative_to(out).as_posix() for p in out.rglob("*"))
    assert left == ["mine", "mine/frames", "notes.txt", "report.json"]
    assert read_report(out / "report.json")["status"] == "invalid"


def test_rerun_unlinks_frames_symlink_without_following_it(tmp_path, fake_blender):
    """FR-018: a `frames` symlink is removed as a link; the directory it points to is kept."""
    fake_blender("ok")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.png").write_bytes(b"keep")
    out = tmp_path / "out"
    out.mkdir()
    (out / "frames").symlink_to(elsewhere, target_is_directory=True)
    write_script(tmp_path, "from rube import Machine\nmachine = Machine(duration=99)\n")
    run(tmp_path)
    assert not (out / "frames").exists() and not (out / "frames").is_symlink()
    assert (elsewhere / "keep.png").read_bytes() == b"keep"


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "abc", ""])
def test_timeout_must_be_finite_and_positive(tmp_path, fake_blender, value, capsys):
    """FR-018 (T-019 review finding 9): --timeout must be a finite number > 0 (usage error)."""
    argv_file = fake_blender("ok")
    write_script(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run(tmp_path, "--timeout", value)
    assert exc.value.code == 2 and "--timeout" in capsys.readouterr().err
    assert not argv_file.exists() and not (tmp_path / "out").exists()


def test_timeout_accepts_fractional_seconds():
    """FR-018: a positive fraction is a valid --timeout."""
    args = cli.build_parser().parse_args(["run", "m.py", "--out", "o", "--timeout", "0.5"])
    assert args.timeout == 0.5
