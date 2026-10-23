"""Acceptance scenario A11: a script importing ``os`` is rejected before anything runs.

Expected: ``rube check`` / ``rube run`` report ``DISALLOWED_IMPORT`` and exit 2; Blender is
never launched (FR-016). Only ``rube``, ``math`` and ``random`` may be imported.
"""

import os  # noqa: F401 - deliberately disallowed import under test

from rube import Ball, Machine

machine = Machine(name="a11_disallowed_import", duration=2)
machine.add(Ball((0, 0, 1)))
