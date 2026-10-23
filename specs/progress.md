# Progress log

Append one line per completed task: `YYYY-MM-DD T-NNN <summary> — <tests> — <notes>`.

## Log

- 2026-10-23 Spec phase: clarifications, requirements, design, tasks approved (combined gate).
- 2026-10-23 T-001 Scaffolding: pyproject, .venv (3.13), ruff (Python only), smoke test, CLAUDE.md — unit 1 passed, ruff clean.
- 2026-10-23 T-003 vec.py (Vec3, as_vec3, yaw/axis rotations, Euler XYZ) + errors.py (Issue, CODES, RubeValidationError, format_issue) — unit 21 passed, ruff clean — tests/blender/ (T-002, untracked) left out of M1 commits.
- 2026-10-23 T-004 geometry.py: MeshSpec, box/uv-sphere(32x16)/cylinder/prism meshes at true size around center of volume, volume/centroid, AABB helpers — unit 27 passed, ruff clean — prism base at -h/3 so origin = centroid (D-3).
- 2026-10-23 T-005 entities.py: PhysicsProps, DEFAULTS, COLORS, Entity (auto type registry), Floor, Ball, Block, Domino (tilt about front edge, deactivation), anchors, validate(), body() -> BodySpec; Hinge/HingeSpec and Group base for later milestones — unit 69 passed, ruff clean — design D-14..D-17 added (clearance on bottom-placed bodies, arg coercion, Block default size/colors, naming).

## Physics default changes (assumption A-1)

_None yet._

## Traceability matrix

_Filled in at T-019._
