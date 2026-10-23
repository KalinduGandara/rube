"""Smoke test: the package imports and reports its version (T-001)."""

import rube


def test_version():
    assert rube.__version__ == "0.1.0"


def test_public_api_reexported():
    """FR-001/FR-003/FR-014: the M1 public API is importable from the package root."""
    from rube import Ball, Block, Camera, Domino, Floor, Issue, Machine, RubeValidationError, Vec3

    for obj in (Ball, Block, Camera, Domino, Floor, Issue, Machine, RubeValidationError, Vec3):
        assert obj.__name__ in rube.__all__
