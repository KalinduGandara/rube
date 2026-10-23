# Fresh-eyes review — v1 (T-019)

Reviewer: independent read-only agent, 2026-10-24, against `requirements.md` and `SPEC.md`.
Resolution of each finding is logged in `progress.md`.

**rube v1 review (`feat/v1`): the gates pass, but I found two high-severity bugs, both reproduced**

The worst is that the overlap check misses boxes that overlap with coplanar faces. Two blocks overlapping by 75% bake as `ok` and get thrown apart at 4 m/s. Second, an author script with an infinite loop hangs `rube check` and `rube run` forever and no `report.json` is written. No repo files were modified; probe scripts and outputs are in `/private/tmp/claude-502/-Users-kalindu-MyWork-rube/e9105d94-d190-48d4-84ce-91b71b724704/scratchpad/`.

## 1. Test and lint results
- `.venv/bin/pytest tests/unit -q`: 297 passed (4.5 s)
- `.venv/bin/pytest -m blender tests/blender -q`: 16 passed (30 s)
- `.venv/bin/ruff check .`: all checks passed
- `.venv/bin/ruff format --check .`: 56 files already formatted

## 2. Traceability matrix

| Req | Test(s) | Gap |
|---|---|---|
| FR-001 | test_machine.py::test_auto_floor_first_and_optional, test_add_returns_same_object_and_keeps_order, test_add_group_registers_members_in_order, test_duration_out_of_range, test_too_many_bodies; test_entities.py::test_floor_body_top_at_zero | – |
| FR-002 | test_machine.py::test_auto_names_per_type_and_explicit_names, test_name_duplicate; test_generators.py::test_chain_in_machine_names_and_order | Nothing asserts that the Blender object name equals the entity name; it is only implied by `bpy.data.objects["Ball_1"]` in check_camera.py |
| FR-003 | test_vec.py (9 tests); test_machine.py::test_frame_range, test_frame_range_ignores_float_noise | – |
| FR-004 | test_entities.py::test_defaults_table_matches_spec, test_resolved_physics_uses_defaults_and_overrides, test_density_mass_for_block_and_domino, test_physics_fields_are_keyword_only, test_entity_validation_codes, test_invalid_color_lists_valid_names | – |
| FR-005 | test_entities.py::test_ball_body_and_anchor; test_geometry.py::test_uv_sphere_mesh; A1 | – |
| FR-006 | test_entities.py::test_block_anchors_and_body; test_geometry.py::test_box_mesh | – |
| FR-007 | test_entities.py::test_upright_domino_anchors_and_deactivation, test_tilted_domino_keeps_front_edge_on_ground, test_domino_top_center_follows_tilt; A3 | Deactivation flags are checked on the spec only, never on the Blender `rigid_body` |
| FR-008 | test_ramp.py (9 tests); A2 | – |
| FR-009 | test_channel.py (9 tests); A6 | – |
| FR-010 | test_spiral.py (14 tests); A6 | – |
| FR-011 | test_generators.py (15 tests); test_paths.py (5 tests); A3, A4 | – |
| FR-012 | test_lever.py (8 tests); test_entities.py::test_hinge_spec_and_validation; A7; test_overlap_skips_hinged_pairs_with_collisions_disabled | Blender constraint type and axis are not asserted (behaviour only) |
| FR-013 | test_machine.py::test_outside_floor, test_mass_ratio_warning_for_near_dynamic_bodies, test_entity_and_group_issues_are_collected, test_bad_machine_arguments_are_issues_not_exceptions; test_entities.py::test_validation_collects_all_issues; test_errors.py::test_codes_match_spec | – |
| FR-014 | test_camera.py (6 tests); A12 (check_camera.py) | Nothing asserts COPY_LOCATION/TRACK_TO with use_offset or "not parented" (behaviour only) |
| FR-015 | test_serialization.py (5 tests); test_entities.py::test_entity_dict_roundtrip | – |
| FR-016 | test_script.py (11 tests); test_cli_check.py::test_a11_disallowed_import_exits_2_without_blender; A11 | Bypass forms are untested (finding 3) |
| FR-017 | test_cli_check.py (7 tests) | – |
| FR-018 | test_cli_run.py (11 tests); test_report.py::test_exit_codes | "report.json in every case" fails for a hanging or interrupting script (findings 2 and 4) |
| FR-019 | none | **No test**: units, fps, frame range, substeps 20, iterations 20, split impulse, cache range and reset via `bpy.data` are never asserted |
| FR-020 | test_entities.py::test_entity_is_base_of_all; test_channel.py::test_recenter_moves_origin_to_center_of_volume | **No Blender-side test**: rb type, shape, margin, damping and the `rube_name`/`rube_type` custom properties are never read back |
| FR-021 | A8; test_overlap_containment_and_near_misses; test_overlap_skips_hinged_pairs_with_collisions_disabled | Coplanar box overlaps are missed (finding 1) |
| FR-022 | test_cli_run.py::test_bake_failed_status_exits_3 (fake Blender) | The real `RuntimeError` → `BAKE_FAILED` path is never exercised |
| FR-023 | test_analysis.py (19 tests) | – |
| FR-024 | test_report.py::test_still_frames_*; A10; A12 | H.264 not verified (A12 checks only `ftyp`); the cache inside `machine.blend` is not checked |
| FR-025 | test_report.py (5 tests); test_analysis.py::test_record_has_report_keys_and_values; test_cli_run.py::test_framework_bug_still_writes_report; A1 (passive bodies omitted) | – |
| FR-026 | test_probe.py::test_probe_api_facts_hold | – |
| FR-027 | test_docs.py (4 tests) | README not tested; `Vec3` missing from the doc (finding 8) |
| NFR-001 | test_layering.py::test_layer1_never_imports_blender_modules (+ self-tests) | Scanner weaknesses (finding 6) |
| NFR-002 | none | Holds today (`dependencies = []`, stdlib-only imports) but no test |
| NFR-003 | test_layering.py::test_blender_layer_uses_only_whitelisted_ops_under_temp_override (+ self-tests) | Scanner weaknesses (finding 6) |
| NFR-004 | A9 test_a9_ball_ramp_chain_determinism; test_a1_determinism | – |
| NFR-005 | A10 test_a10_ramp_chain_with_stills_under_60s | – |
| NFR-006 | test_script.py::test_guard_documented_as_guard_rail_not_sandbox; A11 | – |
| NFR-007 | none | No test; small gaps (finding 8) |
| NFR-008 | CI gates (run above) | – |

## 3. Findings (most severe first)

**1. HIGH: OVERLAP misses box overlaps with coplanar faces (FR-021).** `src/rube/blender/simulate.py:55-59`
- **Cause:** `_intersect` relies on `BVHTree.overlap` plus a check that `vertices[0]` is strictly inside the other body. Coplanar triangles are not reported by the BVH, and a vertex lying on the other body's surface fails the `< 0` test.
- **Repro 1:** two `Block(size=(0.4,0.4,0.4))` at x=0 and x=0.1. Result: status `ok`, exit 0, no issues, blocks thrown apart at 3.97 m/s (`scratchpad/o_ov/report.json`).
- **Repro 2:** two `Domino` at x=0 and x=0.05. Result: `ok`, and they stay interpenetrated because they start deactivated.
- **Fix:** in `_intersect`, also test whether the centre of the AABB-intersection box, and each body's location, lies strictly inside both shapes (`contains` with an `-eps` tolerance). Alternatively, use a separating-axis test for BOX/BOX pairs. Add both repro cases to `test_overlap_containment_and_near_misses`.

**2. HIGH: an author script that never finishes hangs the CLI with no report.json (FR-018 "every case").** `src/rube/script.py:122`, `src/rube/cli.py:149`
- **Cause:** `exec` has no time limit; `--timeout` only covers Blender.
- **Repro:** `while True: pass` under `rube run --timeout 1` hung until it was killed externally after 5 s; the output directory was empty.
- **Fix:** run `check_script` in a child process (`multiprocessing`/subprocess) with a script timeout, or use `signal.alarm` on POSIX. On expiry, report `SCRIPT_ERROR` (or status `timeout`) and write the report.

**3. MEDIUM: the import guard is trivially bypassed (FR-016).** `src/rube/script.py:65-77`, `src/rube/script.py:120`. All four forms below passed `rube check` with exit 0 (`scratchpad/b1.py`–`b4.py`):
- `import rube.cli; rube.cli.os.environ[...]`
- `from rube.cli import subprocess` (ran `echo`)
- `__builtins__["__imp"+"ort__"]("os")`
- `Machine.__init__.__globals__`

These go beyond the documented "guard rail" caveat because they need no deliberate trickery: `rube.cli`, `rube.report` and `rube.script` legitimately expose `os`, `subprocess` and `Path`.
- **Fix, part 1:** allow only `rube` and its public-API modules (deny `rube.cli`, `rube.script`, `rube.report`, `rube.blender*`, and `from X import *` from them).
- **Fix, part 2:** forbid the names `__builtins__`, `getattr`, `globals`, `vars`, `compile`, `breakpoint` and `input`, and any `ast.Attribute` whose `attr` starts with `__`.
- **Fix, part 3:** exec with a curated `{"__builtins__": SAFE_BUILTINS}`.
- **Fix, part 4:** add these cases to `test_disallowed_imports_and_names`.

**4. MEDIUM: a BaseException from the script leaves no report.json.** `src/rube/script.py:125`, `src/rube/cli.py:205`
- **Cause:** `load_machine` catches only `(Exception, SystemExit)`, and `cmd_run` only `Exception`.
- **Repro:** a script with `raise KeyboardInterrupt` exits 130 and leaves the output directory empty (`scratchpad/b6.py`). The same happens on Ctrl-C during the Blender run (`_launch` re-raises at cli.py:115-117).
- **Fix:** in `cmd_run`, add `except BaseException` that writes an `internal_error` report (traceback "interrupted") and then re-raises. In `load_machine`, catch `BaseException` other than a real interrupt as `SCRIPT_ERROR`.

**5. MEDIUM: Blender-side settings have no verifying test (FR-019, FR-020, FR-007 flags, FR-014 constraints and no-parent, FR-024 H.264, FR-022 real bake failure).**
- **Cause:** the acceptance tests check behaviour only. Each requirement says "verified by a test", and a regression in, say, `substeps_per_frame` or `use_margin` would go unnoticed.
- **Fix:** add `tests/blender/check_scene.py`, run against `machine.blend` after A1/A5/A12, asserting:
  - `scene.unit_settings`, fps and frame range
  - `rigidbody_world` substeps, iterations, `use_split_impulse` and `point_cache` range
  - each object's `rigid_body` fields and `["rube_name"]`/`["rube_type"]`
  - domino `use_start_deactivated`
  - camera `parent is None` with constraint types `COPY_LOCATION` (`use_offset`) and `TRACK_TO`
  - `ffmpeg.codec == "H264"`

**6. LOW: the layering scanners are easy to fool (NFR-001, NFR-003 test strength).** `tests/unit/test_layering.py:29-100`
- **Missed patterns:**
  - `import bpy as b; b.ops.x()` (aliasing)
  - `getattr(bpy.context, "object")`
  - `from importlib import import_module`
  - `bpy.ops` calls inside a nested `def`, which count as "inside" a `with temp_override`
  - Layer-1 imports of `rube.blender`
- **Fix:** resolve import aliases into the dotted names, flag `getattr` on `context`, reset `in_override` on `FunctionDef`/`Lambda`, and add `rube.blender` to the Layer-1 forbidden set.

**7. LOW: stale artifacts survive a re-run.** `src/rube/cli.py:144`
- **Cause:** only `report.json` is unlinked. Old `frames/`, `video.mp4`, `machine.blend`, `spec.json` and `blender.log` remain next to a new `invalid`/`timeout` report.
- **Fix:** also remove the known artifact paths, or the `frames/` directory, at the start of `cmd_run`.

**8. LOW: documentation coverage (FR-027, NFR-007).**
- `Vec3` is exported in `src/rube/__init__.py:28` but appears 0 times in `docs/API_FOR_LLM.md`, though FR-027 requires every public signature.
- No test checks that the README exists or has setup content.
- The `src/rube/__init__.py` docstring has no `Implements:` line.
- `src/rube/blender/__init__.py:3` says the modules import `bmesh`; none do.
- **Fix:** add a `Vec3` line to the doc, a README test, an `Implements:` line, and fix the docstring.

**9. LOW: `--timeout` is not validated.** `src/rube/cli.py:226-231`
- **Cause:** a value of 0 or below makes `proc.wait` time out immediately and report `timeout` (inferred from reading the code, not run); `nan` falls through to `internal_error`.
- **Fix:** use an argparse `type` that requires a finite value > 0.

**10. LOW: overlap check skips passive–passive pairs.** `src/rube/blender/simulate.py:82`
- **Cause:** FR-021 says "any two rigid bodies", but pairs of two passive bodies are skipped. This is deliberate (design D-18) and harmless physically.
- **Fix:** either amend FR-021 to say "pairs with at least one dynamic body", or report those overlaps as warnings.

**Checked and found correct:**
- Every `bpy.ops` call is whitelisted and under `temp_override`, and nothing reads `context.object` or `context.active_object`.
- Layer 1 has no `bpy`, `bmesh` or `mathutils` imports.
- The framework uses no randomness, time or hash-dependent ordering.
- The process group is created with `start_new_session` and killed with `killpg(SIGKILL)` on timeout and on a `BaseException`.
- Exit-code mapping and the `internal_error` fallbacks for a missing or invalid Blender report are correct.
