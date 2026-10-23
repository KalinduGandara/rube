"""NFR-002: the runtime is stdlib only.

``pyproject.toml`` declares no runtime dependencies, and no Layer 1 module (everything
outside ``src/rube/blender``) imports a third-party top-level package. Inside Blender the
bundled ``bpy`` / ``mathutils`` / ``numpy`` are allowed, so ``rube/blender`` is not scanned.
"""

import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "rube"
BLENDER_DIR = SRC / "blender"


def third_party_imports(source):
    """Top-level imported package names that are neither stdlib nor ``rube`` itself."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top != "rube" and top not in sys.stdlib_module_names:
                found.add(top)
    return found


def test_pyproject_has_no_runtime_dependencies():
    """NFR-002: ``[project] dependencies`` is empty (dev tools live in the ``dev`` extra)."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["dependencies"] == []


def test_layer1_imports_only_stdlib():
    """NFR-002: no Layer 1 module imports a non-stdlib top-level package."""
    files = [p for p in SRC.rglob("*.py") if BLENDER_DIR not in p.parents]
    assert len(files) >= 8
    bad = {
        str(p.relative_to(SRC)): sorted(i)
        for p in files
        if (i := third_party_imports(p.read_text()))
    }
    assert bad == {}


def test_third_party_scanner_detects_imports():
    """NFR-002 self-test: third-party imports are flagged, stdlib and rube are not."""
    assert third_party_imports("import numpy as np\nfrom yaml import load") == {"numpy", "yaml"}
    assert third_party_imports("import os.path\nfrom rube.vec import Vec3\nimport json") == set()
