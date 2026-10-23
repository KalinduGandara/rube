# Progress log

Append one line per completed task: `YYYY-MM-DD T-NNN <summary> — <tests> — <notes>`.

## Log

- 2026-10-23 Spec phase: clarifications, requirements, design, tasks approved (combined gate).
- 2026-10-23 T-001 Scaffolding: pyproject, .venv (3.13), ruff (Python only), smoke test, CLAUDE.md — unit 1 passed, ruff clean.
- 2026-10-23 T-003 vec.py (Vec3, as_vec3, yaw/axis rotations, Euler XYZ) + errors.py (Issue, CODES, RubeValidationError, format_issue) — unit 21 passed, ruff clean — tests/blender/ (T-002, untracked) left out of M1 commits.
- 2026-10-23 T-004 geometry.py: MeshSpec, box/uv-sphere(32x16)/cylinder/prism meshes at true size around center of volume, volume/centroid, AABB helpers — unit 27 passed, ruff clean — prism base at -h/3 so origin = centroid (D-3).
- 2026-10-23 T-005 entities.py: PhysicsProps, DEFAULTS, COLORS, Entity (auto type registry), Floor, Ball, Block, Domino (tilt about front edge, deactivation), anchors, validate(), body() -> BodySpec; Hinge/HingeSpec and Group base for later milestones — unit 69 passed, ruff clean — design D-14..D-17 added (clearance on bottom-placed bodies, arg coercion, Block default size/colors, naming).
- 2026-10-23 T-006 machine.py: registry (entities/hinges/groups in order), auto floor, auto names (D-17), FPS/frame range, validate() (NAME_DUPLICATE, OUT_OF_RANGE/INVALID_ARGUMENT settings, TOO_MANY_BODIES, OUTSIDE_FLOOR error, MASS_RATIO warning, hinge registration), bodies()/constraints() — unit 90 passed, ruff clean — frame_count uses a 1e-9 epsilon against float noise.
- 2026-10-23 T-007 camera.py (Camera.static/follow, validate, look_rotation, auto_frame using the vertical FOV of the 960x540 / 36 mm sensor) + Machine.set_camera, to_dict/from_dict (format 1, flat entities, hinges, resolved default camera) — unit 108 passed, ruff clean — shared validation helpers in entities.py made public (check_*, coerce_*, jsonable) for reuse by camera/generators.
- 2026-10-23 T-008 script.py (AST guard: rube/math/random only, no __import__/eval/exec/open; exec with real path; SCRIPT_ERROR names the user line; NO_MACHINE), cli.py `rube check` (exit 0/2, 1 on framework bug), report.py (SPEC 9.2 keys, status->exit, timing), test_layering.py (NFR-001 scan + NFR-003 ops/temp_override/active_object scan with self-tests), examples/a11_disallowed_import.py, public API re-exported from rube/__init__ — unit 156 passed, ruff clean, `rube check examples/a11_disallowed_import.py` exits 2 with DISALLOWED_IMPORT — `rube run` is added in T-010.
- 2026-10-23 T-009 analysis.py (Track, analyze -> Analysis(entities, events, issues); first motion > 5 mm / > 2 deg vs frame 1, max_speed, final tilt, fell_over Domino/Block > 60 deg, left_bounds floor area or z < -1, at_rest last 0.5 s < 0.01 m/s, events sorted by frame, UNSTABLE > 30 m/s or > 2 m/frame) — unit 175 passed, ruff clean — times rounded to 1e-4 s, positions to 1e-6 m in records.
- 2026-10-23 T-010 Blender pipeline: blender/scene.py (reset via bpy.data, units/fps/range, rigid body world 20 substeps/20 iterations/split impulse/cache range), physics.py (object_add under temp_override + all BodySpec values), build.py (BUILDERS {BodySpec}, from_pydata, matrix_world, color, rube_name/rube_type), simulate.py (OVERLAP: AABB prefilter + world-space BVHTree.FromPolygons overlap + containment test; free_bake_all + bake; per-frame sampling -> analysis), render.py (machine.blend save only), bootstrap.py (spec.json -> report.json, internal_error with traceback); cli.py `rube run` (validate, spec.json, own process group, timeout kill -> TIMEOUT exit 4, blender.log, stale report removed, missing-report -> internal_error with log tail, exit codes 0/2/3/4/1); examples a1_ball_drop.py, a8_ball_in_block.py — unit 186 passed (test_cli_run with a fake Blender: ok/bake_failed/timeout/no report/invalid/missing binary), blender 6 passed (A1, A1 determinism 1e-6, A8, A11, overlap containment/near-miss, probe), ruff clean — design D-18..D-21 added (passive-passive pairs skipped in overlap check; world-space BVH + containment instead of BVHTree.FromObject; stale report deleted, CLI wall time in elapsed_s, validation warnings carried into the Blender report; M2 saves machine.blend, renders nothing, --video accepted but ignored until M4); tests/blender/conftest.py (T-002, needed by test_acceptance.py) committed, probe files still left to T-002.

## Physics default changes (assumption A-1)

_None yet._

## Traceability matrix

_Filled in at T-019._
