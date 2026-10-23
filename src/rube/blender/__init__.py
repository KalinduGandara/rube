"""Blender side of rube: builder (Layer 2) and simulation / output (Layer 3).

Layers 2/3. Modules here run **only inside Blender** (they import ``bpy``, ``bmesh``,
``mathutils``) and are entered through ``bootstrap.py``, which ``rube run`` executes in a
fresh Blender process. They may import Layer 1 (``rube.*``); Layer 1 never imports them
(NFR-001). Only the whitelisted ``bpy.ops`` are used, each under ``temp_override`` (NFR-003).

Modules: ``scene`` (reset, settings, rigid body world), ``physics`` (rigid body settings),
``build`` (``BUILDERS`` dispatch), ``simulate`` (overlap check, bake, sampling), ``render``
(``.blend`` save; stills / video from milestone M4), ``bootstrap`` (pipeline entry point).

Implements: FR-018 - FR-025 (Blender side).
"""
