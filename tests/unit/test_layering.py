"""Source scans enforcing the layer rules (NFR-001 layer isolation, NFR-003 Blender API discipline).

NFR-001: no module outside ``rube/blender/`` imports ``bpy``, ``bmesh`` or ``mathutils``.
NFR-003: inside ``rube/blender/`` only the whitelisted ``bpy.ops`` are called, each lexically
inside a ``with ... temp_override(...)`` block, and ``context.active_object`` /
``context.object`` are never read. The scanners are also tested on synthetic snippets so the
checks stay meaningful while ``rube/blender/`` is still small.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "rube"
BLENDER_DIR = SRC / "blender"
FORBIDDEN_IN_LAYER1 = {"bpy", "bmesh", "mathutils"}
ALLOWED_OPS = {
    "rigidbody.world_add",
    "rigidbody.object_add",
    "rigidbody.constraint_add",
    "ptcache.bake",
    "ptcache.free_bake_all",
    "render.render",
    "wm.save_as_mainfile",
}


def dotted(node):
    """``a.b.c`` for a Name/Attribute chain, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def layer1_violations(source):
    """Imports of bpy/bmesh/mathutils (any submodule) in a source string."""
    found = []
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Call) and dotted(node.func) in (
            "__import__",
            "importlib.import_module",
        ):
            names = [a.value for a in node.args[:1] if isinstance(a, ast.Constant)]
        found += [
            f"line {node.lineno}: {n}" for n in names if n.split(".")[0] in FORBIDDEN_IN_LAYER1
        ]
    return found


def is_temp_override_with(node):
    """True for ``with <something>.temp_override(...)``."""
    return isinstance(node, ast.With) and any(
        isinstance(item.context_expr, ast.Call)
        and (dotted(item.context_expr.func) or "").endswith("temp_override")
        for item in node.items
    )


def ops_violations(source):
    """Non-whitelisted ops, ops outside temp_override, active-object reads, ``bpy.ops`` aliasing."""
    found = []

    def visit(node, in_override):
        if isinstance(node, ast.Call):
            name = dotted(node.func) or ""
            if name.startswith("bpy.ops."):
                op = name[len("bpy.ops.") :]
                if op not in ALLOWED_OPS:
                    found.append(f"line {node.lineno}: bpy.ops.{op} is not whitelisted")
                elif not in_override:
                    found.append(f"line {node.lineno}: bpy.ops.{op} outside temp_override")
        if isinstance(node, ast.Attribute):
            name = dotted(node) or ""
            if name.endswith(("context.active_object", "context.object")):
                found.append(f"line {node.lineno}: reads {name}")
            if name == "bpy.ops" and not isinstance(getattr(node, "_parent", None), ast.Attribute):
                found.append(f"line {node.lineno}: bpy.ops used without a direct op call")
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("bpy.ops"):
            found.append(f"line {node.lineno}: imports from {node.module}")
        if isinstance(node, ast.ImportFrom) and node.module == "bpy":
            if any(a.name == "ops" for a in node.names):
                found.append(f"line {node.lineno}: from bpy import ops")
        inner = in_override or is_temp_override_with(node)
        for child in ast.iter_child_nodes(node):
            child._parent = node
            visit(child, inner)

    visit(ast.parse(source), False)
    return found


def py_files(root):
    """All ``.py`` files under ``root``."""
    return sorted(root.rglob("*.py"))


def test_layer1_never_imports_blender_modules():
    """NFR-001: no module outside rube/blender imports bpy, bmesh or mathutils."""
    files = [p for p in py_files(SRC) if BLENDER_DIR not in p.parents]
    assert len(files) >= 8  # the scan really covers the Layer 1 modules
    bad = {str(p.relative_to(SRC)): v for p in files if (v := layer1_violations(p.read_text()))}
    assert bad == {}


def test_blender_layer_uses_only_whitelisted_ops_under_temp_override():
    """NFR-003: rube/blender uses only whitelisted bpy.ops under temp_override; no active_object."""
    bad = {
        str(p.relative_to(SRC)): v
        for p in py_files(BLENDER_DIR)
        if (v := ops_violations(p.read_text()))
    }
    assert bad == {}


@pytest.mark.parametrize(
    "snippet",
    ["import bpy", "import mathutils.bvhtree", "from bmesh import ops", "x = __import__('bpy')"],
)
def test_layer1_scanner_detects_violations(snippet):
    """NFR-001 self-test: the scanner flags each forbidden import form."""
    assert layer1_violations(snippet)


GOOD_BLENDER = """
import bpy
def add(obj, sc, rw):
    with bpy.context.temp_override(object=obj, active_object=obj):
        bpy.ops.rigidbody.object_add(type="ACTIVE")
    with bpy.context.temp_override(scene=sc, point_cache=rw.point_cache):
        bpy.ops.ptcache.bake(bake=True)
"""


@pytest.mark.parametrize(
    "snippet",
    [
        "import bpy\nbpy.ops.rigidbody.object_add()\n",  # not under temp_override
        "import bpy\nwith bpy.context.temp_override():\n    bpy.ops.mesh.primitive_cube_add()\n",
        "import bpy\nobj = bpy.context.active_object\n",
        "import bpy\nobj = bpy.context.object\n",
        "import bpy\nops = bpy.ops\n",
        "from bpy import ops\n",
    ],
)
def test_ops_scanner_detects_violations(snippet):
    """NFR-003 self-test: each forbidden pattern is flagged."""
    assert ops_violations(snippet)


def test_ops_scanner_accepts_good_code():
    """NFR-003 self-test: whitelisted ops under temp_override (keyword active_object=) pass."""
    assert ops_violations(GOOD_BLENDER) == []
