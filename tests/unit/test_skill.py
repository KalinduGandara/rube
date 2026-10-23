"""FR-028: the Claude Code ``rube`` skill and its report summarizer (T-020).

The summarizer is a standalone stdlib script, so it is exercised as a subprocess exactly the
way the skill tells Claude to run it.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / ".claude" / "skills" / "rube"
SUMMARIZER = SKILL_DIR / "scripts" / "summarize_report.py"


def _entity(name, type_, moved_frame, fell, *, left=False, rest=True):
    """One dynamic-entity record shaped like SPEC §9.2."""
    return {
        "name": name,
        "type": type_,
        "initial_position": [0.0, 0.0, 0.1],
        "final_position": [1.0, 0.0, 0.1],
        "first_motion_frame": moved_frame,
        "first_motion_time_s": None if moved_frame is None else (moved_frame - 1) / 24,
        "max_speed": 2.5,
        "final_tilt_deg": 80.0 if fell else 0.0,
        "fell_over": fell,
        "left_bounds": left,
        "at_rest_at_end": rest,
    }


def _report(entities, events, issues=(), status="ok"):
    return {
        "status": status,
        "issues": list(issues),
        "timing": {"fps": 24, "frame_start": 1, "frame_end": 193, "duration_s": 8},
        "entities": entities,
        "events": events,
        "artifacts": {"frames": ["frames/f_0001.png"], "video": None, "blend": "machine.blend"},
        "blender_version": "5.2.3",
        "rube_version": "0.1.0",
        "elapsed_s": 4.5,
    }


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SUMMARIZER), *map(str, args)], capture_output=True, text=True
    )


def test_summary_lists_status_issues_entities_events_and_artifacts(tmp_path):
    """FR-028: status, every issue + hint, one line per entity, events, absolute artifacts."""
    report = _report(
        [_entity("Ball_1", "Ball", 3, False), _entity("Domino_1", "Domino", None, False)],
        [{"frame": 3, "time_s": 0.0833, "entity": "Ball_1", "event": "started_moving"}],
        issues=[
            {
                "severity": "warning",
                "code": "MASS_RATIO",
                "entity": "Ball_1,Block_1",
                "message": "mass ratio 150:1",
                "hint": "reduce the mass difference",
            }
        ],
    )
    (tmp_path / "report.json").write_text(json.dumps(report))

    result = _run(tmp_path)  # an output directory is accepted as well as the file

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "status: ok" in out
    assert "MASS_RATIO" in out and "reduce the mass difference" in out
    assert "Ball_1" in out and "Domino_1" in out
    assert "never moved" in out  # Domino_1 has first_motion_frame None
    assert "Domino: 0/1 fell over" in out
    assert "started_moving" in out
    assert str(tmp_path / "frames" / "f_0001.png") in out


def test_long_sections_are_truncated_with_a_count(tmp_path):
    """FR-028: truncation is never silent: the omitted count is printed."""
    events = [
        {"frame": f, "time_s": f / 24, "entity": f"Domino_{f}", "event": "fell_over"}
        for f in range(1, 201)
    ]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report([], events)))

    out = _run(path, "--max-lines", 10).stdout

    assert "190 more events omitted" in out
    assert _run(path, "--all").stdout.count("fell_over") == 200


def test_missing_or_malformed_report_exits_non_zero(tmp_path):
    """FR-028: bad input gives a one-line error and a non-zero exit code."""
    missing = _run(tmp_path / "nope.json")
    assert missing.returncode != 0
    assert len(missing.stderr.strip().splitlines()) == 1

    bad = tmp_path / "report.json"
    bad.write_text("{not json")
    malformed = _run(bad)
    assert malformed.returncode != 0
    assert len(malformed.stderr.strip().splitlines()) == 1


def test_skill_points_to_the_api_doc_and_summarizer():
    """FR-028: SKILL.md has frontmatter and defers the API to docs/API_FOR_LLM.md."""
    text = (SKILL_DIR / "SKILL.md").read_text()
    assert text.startswith("---\nname: rube\n")
    assert "description:" in text.split("---")[1]
    assert "docs/API_FOR_LLM.md" in text
    assert "summarize_report.py" in text
    assert "rube check" in text and "rube run" in text
