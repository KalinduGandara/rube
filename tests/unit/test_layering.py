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


def import_aliases(tree):
    """Local name -> dotted module path for every import in ``tree`` (``import bpy as b``).

    Why: the scanners match on dotted names such as ``bpy.ops.x``; without resolving aliases
    ``b.ops.x()`` or ``from bpy import context as c`` would sail past them. Scopes are
    ignored (an alias anywhere counts everywhere), which can only over-report.
    """
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    aliases[a.asname] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def resolved(node, aliases):
    """``dotted(node)`` with an aliased first segment replaced by the module it stands for."""
    name = dotted(node)
    if name is None:
        return None
    head, _, rest = name.partition(".")
    if head in aliases:
        return f"{aliases[head]}.{rest}" if rest else aliases[head]
    return name


def forbidden_in_layer1(module):
    """True for bpy/bmesh/mathutils, ``importlib`` and ``rube.blender`` (and submodules)."""
    top = module.split(".")[0]
    return (
        top in FORBIDDEN_IN_LAYER1
        or module == "rube.blender"
        or module.startswith(("rube.blender.", "importlib"))
    )


def layer1_violations(source):
    """Layer-1 isolation breaches in a source string.

    Flags imports of bpy/bmesh/mathutils, of ``importlib`` (a dynamic-import back door) and of
    ``rube.blender`` (Layer 1 must never depend on Layers 2/3), in every import form.
    """
    found = []
    tree = ast.parse(source)
    aliases = import_aliases(tree)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
            if node.module == "rube":  # ``from rube import blender``
                names += [f"rube.{a.name}" for a in node.names]
        elif isinstance(node, ast.Call) and resolved(node.func, aliases) in (
            "__import__",
            "importlib.import_module",
        ):
            names = [a.value for a in node.args[:1] if isinstance(a, ast.Constant)]
        found += [f"line {node.lineno}: {n}" for n in names if forbidden_in_layer1(n)]
    return found


def is_temp_override_with(node):
    """True for ``with <something>.temp_override(...)``."""
    return isinstance(node, ast.With) and any(
        isinstance(item.context_expr, ast.Call)
        and (dotted(item.context_expr.func) or "").endswith("temp_override")
        for item in node.items
    )


FORBIDDEN_CONTEXT_ATTRS = ("context.active_object", "context.object")
SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def ops_violations(source):
    """Non-whitelisted ops, ops outside temp_override, active-object reads, ``bpy.ops`` aliasing.

    Import aliases are resolved first; ``getattr`` on ``bpy`` / ``bpy.context`` is flagged
    because it can reach ``object`` / ``active_object`` / ``ops`` by string; a nested
    ``def`` / ``lambda`` does not inherit an enclosing ``temp_override`` because it may run
    after the ``with`` block has exited.
    """
    found = []
    tree = ast.parse(source)
    aliases = import_aliases(tree)

    def visit(node, in_override):
        if isinstance(node, ast.Call):
            name = resolved(node.func, aliases) or ""
            if name.startswith("bpy.ops."):
                op = name[len("bpy.ops.") :]
                if op not in ALLOWED_OPS:
                    found.append(f"line {node.lineno}: bpy.ops.{op} is not whitelisted")
                elif not in_override:
                    found.append(f"line {node.lineno}: bpy.ops.{op} outside temp_override")
            if name == "getattr" and node.args:
                target = resolved(node.args[0], aliases) or ""
                if target == "bpy" or target.startswith(("bpy.ops", "bpy.context")):
                    found.append(f"line {node.lineno}: getattr on {target}")
        if isinstance(node, ast.Attribute):
            name = resolved(node, aliases) or ""
            if name.endswith(FORBIDDEN_CONTEXT_ATTRS):
                found.append(f"line {node.lineno}: reads {name}")
            if name == "bpy.ops" and not isinstance(getattr(node, "_parent", None), ast.Attribute):
                found.append(f"line {node.lineno}: bpy.ops used without a direct op call")
        if isinstance(node, ast.Name) and aliases.get(node.id) == "bpy.ops":
            if not isinstance(getattr(node, "_parent", None), ast.Attribute):
                found.append(f"line {node.lineno}: bpy.ops used without a direct op call")
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("bpy.ops"):
                    found.append(f"line {node.lineno}: imports {a.name}")
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("bpy.ops"):
            found.append(f"line {node.lineno}: imports from {node.module}")
        if isinstance(node, ast.ImportFrom) and node.module == "bpy":
            if any(a.name == "ops" for a in node.names):
                found.append(f"line {node.lineno}: from bpy import ops")
        inner = (
            False if isinstance(node, SCOPE_NODES) else in_override or is_temp_override_with(node)
        )
        for child in ast.iter_child_nodes(node):
            child._parent = node
            visit(child, inner)

    visit(tree, False)
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
    [
        "import bpy",
        "import mathutils.bvhtree",
        "from bmesh import ops",
        "x = __import__('bpy')",
        "import importlib",  # review finding 6: dynamic imports hide bpy
        "from importlib import import_module",
        "import rube.blender",  # Layer 1 must not reach into Layers 2/3
        "from rube.blender import scene",
        "from rube import blender",
        "import importlib.util",
    ],
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
        # Review finding 6: aliases are resolved to their dotted names.
        "import bpy as b\nb.ops.rigidbody.object_add()\n",
        "import bpy as b\nwith b.context.temp_override():\n    b.ops.mesh.primitive_cube_add()\n",
        "import bpy as b\nobj = b.context.active_object\n",
        "from bpy import context as c\nobj = c.object\n",
        "import bpy as b\nops = b.ops\n",
        "import bpy.ops as o\no.rigidbody.object_add()\n",
        # getattr on the context reads the same forbidden attributes.
        'import bpy\nobj = getattr(bpy.context, "object")\n',
        'import bpy as b\nobj = getattr(b.context, "active_object", None)\n',
        "import bpy\nname = 'x'\nobj = getattr(bpy.context, name)\n",
        'import bpy\nops = getattr(bpy, "ops")\n',
        # A nested def or lambda is not lexically "inside" the enclosing temp_override: it can
        # run after the with block has exited.
        (
            "import bpy\nwith bpy.context.temp_override():\n"
            "    def later():\n        bpy.ops.rigidbody.object_add()\n"
        ),
        (
            "import bpy\nwith bpy.context.temp_override():\n"
            "    f = lambda: bpy.ops.rigidbody.object_add()\n"
        ),
    ],
)
def test_ops_scanner_detects_violations(snippet):
    """NFR-003 self-test: each forbidden pattern is flagged."""
    assert ops_violations(snippet)


def test_ops_scanner_accepts_good_code():
    """NFR-003 self-test: whitelisted ops under temp_override (keyword active_object=) pass."""
    assert ops_violations(GOOD_BLENDER) == []


def test_ops_scanner_accepts_override_inside_nested_def():
    """NFR-003 self-test: a nested def that opens its own temp_override is fine."""
    source = (
        "import bpy\ndef outer():\n    def inner(obj):\n"
        "        with bpy.context.temp_override(object=obj):\n"
        "            bpy.ops.rigidbody.object_add()\n"
    )
    assert ops_violations(source) == []


def test_ops_scanner_accepts_aliased_override():
    """NFR-003 self-test: an aliased whitelisted op under an aliased temp_override passes."""
    source = (
        "import bpy as b\nwith b.context.temp_override(scene=1):\n"
        "    b.ops.ptcache.bake(bake=True)\n"
    )
    assert ops_violations(source) == []
