"""Unit tests for ``rube.report`` (FR-025 report shape, FR-018 status -> exit code)."""

import json

import pytest

from rube.errors import error
from rube.report import STATUS_EXIT, build_report, exit_code, read_report, timing, write_report

KEYS = [
    "status", "issues", "timing", "entities", "events", "artifacts",
    "blender_version", "rube_version", "elapsed_s",
]  # fmt: skip


def test_exit_codes():
    """FR-018: ok 0, invalid 2, bake_failed 3, timeout 4, internal_error 1."""
    assert STATUS_EXIT == {
        "ok": 0,
        "invalid": 2,
        "bake_failed": 3,
        "timeout": 4,
        "internal_error": 1,
    }
    assert exit_code("timeout") == 4
    with pytest.raises(ValueError):
        exit_code("exploded")


def test_timing():
    """FR-003/FR-025: timing block for a duration."""
    assert timing(10.0) == {"fps": 24, "frame_start": 1, "frame_end": 241, "duration_s": 10.0}


def test_report_has_exact_keys_and_serializes_issues():
    """FR-025: SPEC 9.2 keys in order; issues as dicts; defaults for missing parts."""
    issue = error("OVERLAP", "Ball_1,Block_1", "overlap 0.05 m", "move apart")
    rep = build_report("invalid", issues=[issue], timing=timing(2.0), elapsed_s=0.123)
    assert list(rep) == KEYS
    assert rep["issues"] == [issue.to_dict()]
    assert rep["entities"] == [] and rep["events"] == []
    assert rep["artifacts"] == {"frames": [], "video": None, "blend": None}
    assert rep["rube_version"] == "0.1.0" and rep["blender_version"] is None
    assert "traceback" not in rep
    assert json.loads(json.dumps(rep)) == rep


def test_internal_error_has_traceback():
    """FR-025: internal_error adds a traceback."""
    rep = build_report("internal_error", traceback="Traceback ...")
    assert rep["traceback"] == "Traceback ..."
    with pytest.raises(ValueError):
        build_report("nonsense")


def test_write_and_read(tmp_path):
    """FR-025: report.json round-trips through disk (creating the directory)."""
    path = tmp_path / "out" / "report.json"
    rep = build_report("ok", timing=timing(1.0), blender_version="5.2.3")
    write_report(path, rep)
    assert read_report(path) == rep
