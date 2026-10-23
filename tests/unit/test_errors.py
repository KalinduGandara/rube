"""Unit tests for ``rube.errors`` (FR-013: Issue shape, codes, RubeValidationError)."""

import dataclasses

import pytest

from rube.errors import CODES, Issue, RubeValidationError, error, format_issue, warning

SPEC_CODES = {
    "NAME_DUPLICATE", "OUT_OF_RANGE", "INVALID_ARGUMENT", "TOO_MANY_BODIES", "CHAIN_SPACING",
    "CHAIN_TURN", "CHAIN_NOT_FLAT", "SLOPE_TOO_SHALLOW", "SLOPE_TOO_STEEP", "TRACK_TOO_NARROW",
    "OUTSIDE_FLOOR", "TOO_SMALL", "MASS_RATIO", "OVERLAP", "UNSTABLE", "DISALLOWED_IMPORT",
    "SCRIPT_ERROR", "NO_MACHINE", "BAKE_FAILED", "TIMEOUT",
}  # fmt: skip


def test_codes_match_spec():
    """FR-013: exactly the SPEC section 9.1 v1 codes exist."""
    assert set(CODES) == SPEC_CODES


def test_issue_fields_and_dict():
    """FR-013: Issue(severity, code, entity, message, hint) is frozen and JSON-serializable."""
    issue = error("OUT_OF_RANGE", "Ball_1", "radius is -1", "use a radius > 0")
    assert issue == Issue("error", "OUT_OF_RANGE", "Ball_1", "radius is -1", "use a radius > 0")
    with pytest.raises(dataclasses.FrozenInstanceError):
        issue.code = "X"  # type: ignore[misc]
    d = issue.to_dict()
    assert d == {
        "severity": "error",
        "code": "OUT_OF_RANGE",
        "entity": "Ball_1",
        "message": "radius is -1",
        "hint": "use a radius > 0",
    }
    assert Issue.from_dict(d) == issue
    assert warning("MASS_RATIO", None, "m", "h").severity == "warning"


def test_issue_rejects_unknown_code_or_severity():
    """FR-013: a typo in a code/severity is a framework bug and raises immediately."""
    with pytest.raises(ValueError):
        Issue("error", "NOT_A_CODE", None, "m", "h")
    with pytest.raises(ValueError):
        Issue("fatal", "OVERLAP", None, "m", "h")


def test_format_issue_is_one_readable_line():
    """FR-017: CLI output names severity, code, entity, message and hint."""
    line = format_issue(error("OVERLAP", "Ball_1,Block_1", "they intersect", "move apart"))
    assert "error" in line and "OVERLAP" in line and "Ball_1,Block_1" in line
    assert "they intersect" in line and "move apart" in line
    assert "\n" not in line


def test_rube_validation_error_carries_issues():
    """FR-013: RubeValidationError holds the issues and shows them in its message."""
    issues = [error("TOO_SMALL", "Ball_1", "radius 0.001 m", "use >= 0.01")]
    exc = RubeValidationError(issues)
    assert exc.issues == issues
    assert "TOO_SMALL" in str(exc)
