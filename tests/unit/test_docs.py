"""Docs checks for FR-027: examples pass `rube check`; API_FOR_LLM.md is short and current."""

import re
from pathlib import Path

import pytest

from rube import cli
from rube.entities import DEFAULTS

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "API_FOR_LLM.md"
#: Intentionally invalid example (A11: disallowed import); `rube check` must reject it.
INVALID = {"a11_disallowed_import.py"}
VALID = sorted(p for p in (ROOT / "examples").glob("*.py") if p.name not in INVALID)


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_example_passes_check(path, capsys):
    """FR-027 / T-018: every valid example script passes `rube check` (exit 0)."""
    assert cli.main(["check", str(path)]) == 0


def test_api_doc_under_300_lines():
    """FR-027 / SPEC 11: docs/API_FOR_LLM.md has fewer than 300 lines."""
    assert len(DOC.read_text(encoding="utf-8").splitlines()) < 300


@pytest.mark.parametrize("name", ["a3_domino_chain", "a5_ball_ramp_chain", "a6_spiral"])
def test_api_doc_embeds_examples(name):
    """FR-027: the doc contains examples A3, A5, A6 verbatim from examples/."""
    source = (ROOT / "examples" / f"{name}.py").read_text(encoding="utf-8").rstrip()
    assert source in DOC.read_text(encoding="utf-8")


def test_api_doc_defaults_match_table():
    """FR-027: every DEFAULTS row appears in the doc's physics table with current values."""
    rows = {
        m.group(1): m.group(0)
        for m in re.finditer(r"^\| (\w+) \|.*$", DOC.read_text(encoding="utf-8"), re.M)
    }
    for key, d in DEFAULTS.items():
        assert key in rows, key
        assert f"| {d.friction:g} | {d.bounciness:g} | {d.margin:g} |" in rows[key]


def test_api_doc_documents_every_public_name():
    """FR-027 (T-019 review finding 8): every name in ``rube.__all__`` appears in the doc."""
    import rube

    text = DOC.read_text(encoding="utf-8")
    missing = [n for n in rube.__all__ if not n.startswith("__") and n not in text]
    # Deliberately undocumented: the group classes (documented through their factories), the
    # color table (names listed in prose), an internal constant, the exception type, version.
    assert set(missing) <= {
        "CLEARANCE",
        "COLORS",
        "DominoChain",
        "RubeValidationError",
        "SpiralRamp",
    }
    assert "Vec3" in text


def test_readme_has_setup_and_usage():
    """FR-027 (T-019 review finding 8): README exists with setup and usage commands."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in ("## Setup", "## Usage"):
        assert heading in text
    assert "pip install" in text
    assert "rube check" in text and "rube run" in text


def test_public_modules_state_what_they_implement():
    """NFR-007: the package docstring and the Blender package docstring have ``Implements:``."""
    import rube
    import rube.blender

    assert "Implements:" in rube.__doc__
    assert "Implements:" in (rube.blender.__doc__ or "")
    assert "bmesh" not in (rube.blender.__doc__ or "").replace("``bmesh`` is not used", "")
