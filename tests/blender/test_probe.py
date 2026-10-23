"""Runs the Blender API probe in a fresh Blender process (FR-026, T-002)."""

import subprocess
from pathlib import Path

import pytest

PROBE = Path(__file__).with_name("probe_api.py").resolve()

pytestmark = pytest.mark.blender


def test_probe_api_facts_hold(blender_exe):
    """FR-026: every SPEC 1.1 Blender 5.2.3 fact still holds (probe exits 0, names changes)."""
    cmd = [
        str(blender_exe), "-b", "--factory-startup", "--python-exit-code", "1",
        "--python", str(PROBE),
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    report = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"probe reported changed facts:\n{report}"
    assert "PROBE OK" in proc.stdout, report
