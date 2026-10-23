"""Pytest fixtures for tests that run the real Blender binary (FR-026, NFR-008).

Layer: test tooling. Provides Blender discovery (``RUBE_BLENDER`` env var, else the macOS default
path from SPEC section 1) and auto-skips every test marked ``blender`` when no binary is found.
"""

import os
from pathlib import Path

import pytest

DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


def find_blender():
    """Locate the Blender executable.

    Returns:
        Path to the binary (``RUBE_BLENDER`` wins over the default location), or None.
    """
    candidate = Path(os.environ.get("RUBE_BLENDER") or DEFAULT_BLENDER)
    return candidate if candidate.is_file() else None


def pytest_collection_modifyitems(config, items):
    """Skip ``blender``-marked tests when the Blender binary cannot be found."""
    if find_blender() is not None:
        return
    skip = pytest.mark.skip(reason="Blender binary not found (set RUBE_BLENDER)")
    for item in items:
        if "blender" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def blender_exe():
    """Path to the Blender binary (tests using this are auto-skipped if it is missing)."""
    exe = find_blender()
    assert exe is not None
    return exe
