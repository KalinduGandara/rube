"""Smoke test: the package imports and reports its version (T-001)."""

import rube


def test_version():
    assert rube.__version__ == "0.1.0"
