# Tasks — Rube v1

Ordered by dependency. Each task = tests first, then code, then full quality gate
(`pytest tests/unit`, `ruff check .`, `ruff format --check .`, plus the listed Blender tests),
then tick the box, append to `progress.md`, and commit `<type>(<area>): T-NNN <summary> [IDs]`.

Execution: milestones run sequentially as one workflow, one agent per milestone
(model in brackets; Sonnet for low-complexity milestones).

## Setup

- [x] T-001: Scaffolding — `pyproject.toml` (package `rube`, `src/` layout, console script, dev extras pytest+ruff, ruff config, pytest marker `blender`), `.venv` (Python 3.13), `.gitignore`, `src/rube/__init__.py` with `__version__ = "0.1.0"`, `tests/unit/test_smoke.py`, `CLAUDE.md`, `specs/*`. Commit includes `srs.md` deletion.
  - Requirements: NFR-002, NFR-008
  - Done when: `pytest tests/unit` passes (1 test), ruff clean, `rube --help` placeholder not required yet.

## M0 — Probe [sonnet]

- [ ] T-002: `tests/blender/probe_api.py` re-verifies every SPEC §1.1 fact; `tests/blender/conftest.py` (Blender discovery, `blender` marker skip); `tests/blender/test_probe.py` runs it.
  - Requirements: FR-026
  - Done when: `pytest -m blender tests/blender/test_probe.py` passes on Blender 5.2.3.

## M1 — Layer 1 core [opus]

- [x] T-003: `vec.py` (Vec3, `as_vec3`, rotation-matrix helpers) and `errors.py` (Issue, codes, RubeValidationError).
  - Requirements: FR-003, FR-013
  - Done when: `tests/unit/test_vec.py`, `test_errors.py` pass.
- [x] T-004: `geometry.py` primitives: `MeshSpec`, `box_mesh`, `uv_sphere_mesh(32,16)`, `cylinder_mesh`, `prism_mesh`, AABB helpers.
  - Requirements: FR-005, FR-006, FR-020
  - Done when: `test_geometry.py` checks vertex counts, bounds = true size, centroid at origin, closed (every edge shared by 2 faces).
- [x] T-005: `entities.py`: PhysicsProps, `DEFAULTS`, `COLORS`, Entity, Floor, Ball, Block, Domino (tilt, deactivation), anchors, `validate()`, `body()` → BodySpec.
  - Requirements: FR-004–FR-007, FR-013
  - Done when: `test_entities.py` covers defaults, density mass, anchors, tilt keeps front edge on ground, deactivation flags, OUT_OF_RANGE / INVALID_ARGUMENT / TOO_SMALL.
- [x] T-006: `machine.py`: registry, groups, auto names, auto floor, `validate()` (NAME_DUPLICATE, OUT_OF_RANGE duration, TOO_MANY_BODIES, OUTSIDE_FLOOR, MASS_RATIO), `bodies()`/`constraints()`.
  - Requirements: FR-001, FR-002, FR-013
  - Done when: `test_machine.py` covers every listed code and build order.
- [ ] T-007: `camera.py` (static, follow, auto_frame) + `to_dict`/`from_dict`.
  - Requirements: FR-014, FR-015
  - Done when: `test_camera.py` (auto frame contains bbox), `test_serialization.py` (round-trip equality, JSON-safe) pass.
- [ ] T-008: `script.py` (AST guard, exec, NO_MACHINE, SCRIPT_ERROR) + `cli.py check` + `report.py` + `test_layering.py` (NFR-001 scan; NFR-003 ops whitelist + no `active_object`).
  - Requirements: FR-016, FR-017, FR-025, NFR-001, NFR-003, NFR-006
  - Done when: `test_script.py`, `test_cli_check.py`, `test_report.py`, `test_layering.py` pass; `rube check examples/a11_disallowed_import.py` exits 2 with DISALLOWED_IMPORT.

## M2 — Pipeline [opus]

- [ ] T-009: `analysis.py` (tracks → entity records, events, UNSTABLE).
  - Requirements: FR-023
  - Done when: `test_analysis.py` covers first motion thresholds, fell_over, left_bounds, at_rest, event sorting, UNSTABLE (speed and jump).
- [ ] T-010: `blender/scene.py`, `physics.py`, `build.py`, `simulate.py` (overlap, bake, sample), `bootstrap.py`; `cli.py run` (subprocess, process group, timeout, exit codes, blender.log, missing-report fallback).
  - Requirements: FR-018–FR-023, FR-025, NFR-004
  - Done when: `test_cli_run.py` (fake Blender script: ok / timeout / no report) passes; acceptance A1, A8, A11 pass; A1 run twice gives identical final positions.

## M3 — Ramp + chains [opus]

- [ ] T-011: `Ramp` plank + anchors (`ball_spawn`, `exit`, `slope_deg`, `direction`); example + test A2.
  - Requirements: FR-008
  - Done when: unit anchor tests pass; A2 passes.
- [ ] T-012: `geometry.catmull_rom`, `ArcLengthTable`; `generators.domino_chain` + validation; examples + tests A3, A4.
  - Requirements: FR-011
  - Done when: spacing uniformity (< 1 mm), yaw follows tangent, CHAIN_* codes unit-tested; A3, A4 pass.
- [ ] T-013: Ball → ramp → chain example; A5 and A9 (A5 twice, 1e-6).
  - Requirements: FR-008, FR-011, NFR-004
  - Done when: A5, A9 pass. Physics default changes (if any) recorded per assumption A-1.

## M4 — Rendering [sonnet]

- [ ] T-014: `blender/render.py`: camera (static / follow constraints), Workbench 960×540, 6 stills, `--video` MP4, `.blend` save; report artifacts.
  - Requirements: FR-014, FR-024
  - Done when: A10 (< 60 s) and A12 (via `tests/blender/check_camera.py`) pass.

## M5 — Channels [opus]

- [ ] T-015: `geometry.channel_mesh`; `Ramp(rails=True)` (MESH, margin 0.005).
  - Requirements: FR-009
  - Done when: channel mesh closed/manifold unit test; rails ramp unit test.
- [ ] T-016: `generators.spiral_ramp` (helix channel, support column, anchors, slope + track validation); example + A6.
  - Requirements: FR-010
  - Done when: slope/entry/exit unit tests; A6 passes.

## M6 — Lever [sonnet]

- [ ] T-017: `Lever` group (plank, fulcrum prism, Hinge), `build_hinge`, overlap skip for disabled-collision pairs; example + A7.
  - Requirements: FR-012, FR-021
  - Done when: anchor/axis unit tests; A7 passes.

## M7 — Docs [sonnet]

- [ ] T-018: `docs/API_FOR_LLM.md` (< 300 lines, final defaults), `README.md`, examples tidy.
  - Requirements: FR-027
  - Done when: doc line count < 300; every example script passes `rube check`.

## Verify [opus]

- [ ] T-019: Full suite + ruff; traceability matrix in `progress.md`; fresh-eyes review against `requirements.md`; fix findings.
  - Requirements: all
  - Done when: every FR/NFR maps to ≥ 1 passing test or is flagged.
