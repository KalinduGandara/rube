# Requirements — Rube v1

Every requirement traces to a section of [`SPEC.md`](../SPEC.md) (`§n`). Acceptance criteria
use EARS phrasing and name the test that verifies them (filled in as tasks complete; see the
traceability matrix in `progress.md`). "Author" = the machine-author LLM using the package.

## Functional requirements

### FR-001 Machine container (§4)
As an author, I want one `Machine` object that holds everything, so that my script is just "create, add, done".
- THE SYSTEM SHALL provide `Machine(name="machine", duration=10.0, floor=True, floor_size=20.0)`.
- WHEN `floor=True`, THE SYSTEM SHALL add a passive `Floor` of `floor_size × floor_size × 0.2` m whose top is at z = 0.
- WHEN `add(item)` is called, THE SYSTEM SHALL register it, return the same object, and, for a `Group`, register all of its members in order.
- THE SYSTEM SHALL build entities in registration order.
- WHEN `duration` is outside [1, 60] s, THE SYSTEM SHALL report `OUT_OF_RANGE`.
- WHEN there are more than 500 rigid bodies, THE SYSTEM SHALL report `TOO_MANY_BODIES`.

### FR-002 Naming (§2)
- WHEN an entity has no name, THE SYSTEM SHALL name it `<Type>_<n>` (per type, 1-based, in registration order).
- WHEN two entities share a name, THE SYSTEM SHALL report `NAME_DUPLICATE` naming it.
- THE SYSTEM SHALL give the Blender object exactly the entity's name.

### FR-003 Vectors and conventions (§2)
- THE SYSTEM SHALL provide an immutable `Vec3` with `+ - * /`, `dot`, `cross`, `length`, `normalized`.
- THE SYSTEM SHALL accept a 3-tuple or a `Vec3` everywhere a position is expected.
- THE SYSTEM SHALL use meters / kg / s, Z up, ground top at z = 0, angles in **degrees** in the public API, `facing_deg` = yaw about +Z with 0° = +X.
- THE SYSTEM SHALL use 24 fps and `frames = ceil(duration · 24)`, `frame_end = 1 + frames`.

### FR-004 Physics properties and defaults (§5)
- THE SYSTEM SHALL give every entity keyword-only `dynamic`, `mass`, `friction`, `bounciness`, `color`.
- WHEN a field is not given, THE SYSTEM SHALL use the per-class default from a single defaults table (SPEC §5 table).
- WHEN `mass` is not given for `Block`/`Domino`, THE SYSTEM SHALL derive it from density 600 kg/m³ and the box volume.
- WHEN `friction` or `bounciness` is outside [0, 1] or `mass` ≤ 0, THE SYSTEM SHALL report `OUT_OF_RANGE`.
- WHEN `color` is not a known named color, THE SYSTEM SHALL report `INVALID_ARGUMENT` listing valid names.

### FR-005 Ball (§5)
- THE SYSTEM SHALL provide `Ball(center, radius=0.1)`: UV sphere 32×16, collision `SPHERE`, dynamic by default, `center` = sphere center.
- THE SYSTEM SHALL expose `ball.bottom`.

### FR-006 Block (§5)
- THE SYSTEM SHALL provide `Block(position, size=(x,y,z), facing_deg=0)`, collision `BOX`, `position` = bottom-center.
- THE SYSTEM SHALL expose `.top_center` and `.front` (bottom point on the +facing side).

### FR-007 Domino (§5, §5.1)
- THE SYSTEM SHALL provide `Domino(position, facing_deg=0, tilt_deg=0, size=(0.1,0.4,0.8))`, `size = (thickness, width, height)`, falling toward `facing_deg`.
- WHEN `tilt_deg > 0`, THE SYSTEM SHALL rotate the domino toward `facing_deg` about its bottom front edge (computed in Layer 1) so that edge stays on `position`'s ground plane.
- THE SYSTEM SHALL set `use_deactivation` and `use_start_deactivated` on dominoes, EXCEPT WHEN `tilt_deg > 0`, in which case the domino SHALL start active.
- THE SYSTEM SHALL expose `.top_center` and `.front`.

### FR-008 Ramp — plank (§5, §5.2)
- THE SYSTEM SHALL provide `Ramp(start, end, width=0.4, thickness=0.05, rails=False)`, passive, collision `BOX`; `start`/`end` are the top-surface centerline endpoints and `start` is the high end.
- WHEN `start.z <= end.z`, THE SYSTEM SHALL report `INVALID_ARGUMENT` with a hint to swap them.
- THE SYSTEM SHALL expose `.top`, `.bottom`, `.direction` (unit downhill), `.slope_deg`, `.ball_spawn(radius)` (sphere center 1.5·radius in from the top edge, resting just above the surface incl. clearance, correct for slope), `.exit(distance=0.0)` (ground-level point beyond the bottom end along the horizontal direction).

### FR-009 Ramp — rails (§5, §6.2)
- WHEN `rails=True`, THE SYSTEM SHALL build the ramp as a U-channel from `geometry.channel_mesh` with a straight path, collision `MESH`, margin 0.005.

### FR-010 Spiral ramp (§6.2)
- THE SYSTEM SHALL provide `spiral_ramp(center, radius, height, turns, *, track_width=0.25, wall_height=0.08, thickness=0.03, clockwise=False) -> SpiralRamp`, a passive U-channel along a helix descending from `center.z + height` to `center.z + thickness`, ≥ 48 segments per turn, collision `MESH`, plus a passive central support column of radius `radius − track_width/2 − 0.01`.
- THE SYSTEM SHALL expose `.entry`, `.exit`, `.ball_spawn(radius)`.
- WHEN slope = `height / (2π·radius·turns)` < tan 4°, THE SYSTEM SHALL report `SLOPE_TOO_SHALLOW`; WHEN > tan 25°, `SLOPE_TOO_STEEP`.
- WHEN `ball_spawn(r)` was used and `track_width < 2.5 r` or `wall_height < 0.6 r`, THE SYSTEM SHALL report `TRACK_TOO_NARROW`.

### FR-011 Domino chain (§6.1)
- THE SYSTEM SHALL provide `domino_chain(points, *, spacing=None, count=None, size=(0.1,0.4,0.8), tilt_first_deg=0, color=None) -> DominoChain`.
- THE SYSTEM SHALL route the chain along a Catmull-Rom spline through the waypoints (2 points = straight line) and place dominoes at equal **arc length** (SPEC "gap variance < 1 mm", interpreted as: max − min straight-line gap between consecutive domino positions < 1 mm).
- THE SYSTEM SHALL set each domino's `facing_deg = atan2(ty, tx)` of the path tangent.
- WHEN neither `spacing` nor `count` is given, spacing SHALL be `0.5 × height`; WHEN both are given, `INVALID_ARGUMENT`.
- WHEN spacing ∉ [0.3, 0.75] × height → `CHAIN_SPACING`; yaw change between neighbours > 15° → `CHAIN_TURN`; waypoint z values differ → `CHAIN_NOT_FLAT`; fewer than 2 dominoes → `INVALID_ARGUMENT`. Each hint SHALL contain a concrete fix (e.g. the valid spacing range in meters).
- THE SYSTEM SHALL expose `.first`, `.last`, `.dominoes`, `.start`, `.end`.

### FR-012 Lever (§5.3)
- THE SYSTEM SHALL provide `Lever(pivot, length=2.0, width=0.3, thickness=0.05, facing_deg=0, tilt_deg=0, fulcrum_height=None)`: dynamic plank, passive triangular-prism fulcrum (height defaults to `pivot.z`), and a `HINGE` constraint at `pivot` with horizontal axis perpendicular to `facing_deg` and `disable_collisions=True`.
- THE SYSTEM SHALL expose `.left_end`, `.right_end`.

### FR-013 Static validation (§9.1, §2, §4)
- WHEN `validate()` is called, THE SYSTEM SHALL return **all** issues (never raise for content problems), each an `Issue(severity, code, entity, message, hint)` whose message contains the actual numbers.
- THE SYSTEM SHALL check: `NAME_DUPLICATE`, `OUT_OF_RANGE`, `INVALID_ARGUMENT`, `TOO_MANY_BODIES`, chain/spiral codes (FR-010/011), `OUTSIDE_FLOOR` (entity center outside floor area when a floor exists), `TOO_SMALL` (any dimension < 0.02 m), `MASS_RATIO` (warning, > 100:1 between dynamic bodies whose bounding boxes are within 0.05 m).

### FR-014 Camera (§7)
- THE SYSTEM SHALL provide `Camera.static(position, look_at, lens_mm=35)` and `Camera.follow(target, offset=(-3,-3,2), lens_mm=35)`.
- WHEN no camera is set, THE SYSTEM SHALL auto-frame the bounding box of all non-floor entities from a 3/4 elevated view with the whole box in frame.
- WHEN following, THE SYSTEM SHALL use `COPY_LOCATION` (use_offset) + `TRACK_TO` (`TRACK_NEGATIVE_Z`, `UP_Y`) and SHALL NOT parent the camera to the target.

### FR-015 Serialization (§3.3, §4)
- THE SYSTEM SHALL provide `Machine.to_dict()` producing JSON-safe data (entities flattened in build order, constraints, camera, settings) and `Machine.from_dict(d)` such that `Machine.from_dict(d).to_dict() == d`.

### FR-016 Script loading and import guard (§10.1)
- THE SYSTEM SHALL parse the script with `ast` before executing it; WHEN it imports anything other than `rube`, `math`, `random` (incl. submodules of `rube`), or references `__import__`, `eval`, `exec`, `open`, THE SYSTEM SHALL report `DISALLOWED_IMPORT` and not execute it.
- WHEN the script raises, THE SYSTEM SHALL report `SCRIPT_ERROR` with the line in the user script.
- WHEN the script defines no top-level `machine` of type `Machine`, THE SYSTEM SHALL report `NO_MACHINE`.
- THE SYSTEM SHALL allow only the public `rube` API modules (not `rube.cli`, `rube.script`, `rube.report`, `rube.blender*`), SHALL reject dunder attribute access and the names `__builtins__`, `getattr`, `setattr`, `delattr`, `globals`, `locals`, `vars`, `compile`, `breakpoint`, `input`, and SHALL execute the script with a curated set of builtins. (Review finding 3; still a guard rail, not a sandbox.)
- WHEN the script runs longer than 30 s, THE SYSTEM SHALL stop it and report `SCRIPT_ERROR` (status `invalid`, report written). (Review finding 2.)
- WHEN the script raises any exception including `BaseException` subclasses other than a real user interrupt, THE SYSTEM SHALL report `SCRIPT_ERROR`; WHEN the user interrupts `rube run`, THE SYSTEM SHALL still write `report.json` (status `internal_error`, "interrupted") before exiting. (Review finding 4.)

### FR-017 `rube check` (§10.1)
- WHEN `rube check machine.py` runs, THE SYSTEM SHALL print all issues and exit 0 if there are no errors, else 2, without starting Blender.

### FR-018 `rube run` (§10.1, §3.3)
- WHEN `rube run machine.py --out DIR [--video] [--timeout 300]` runs, THE SYSTEM SHALL validate first; WHEN invalid, write `report.json` with status `invalid` and exit 2 without starting Blender.
- OTHERWISE THE SYSTEM SHALL write `DIR/spec.json` and run `Blender -b --factory-startup --python-exit-code 1 --python bootstrap.py -- …` in a new process group; WHEN it exceeds the timeout, kill the group and write status `timeout`.
- THE SYSTEM SHALL use the Blender path from `RUBE_BLENDER` if set, else `/Applications/Blender.app/Contents/MacOS/Blender`.
- THE SYSTEM SHALL exit 0 ok, 2 invalid, 3 bake_failed, 4 timeout, 1 internal_error, and write `report.json` in every case.

### FR-019 Scene setup (§8.1–8.3)
- THE SYSTEM SHALL delete all objects, meshes, materials, cameras, lights and collections via `bpy.data` (not `read_factory_settings`).
- THE SYSTEM SHALL set metric units, scale 1.0, fps 24, `frame_start=1`, `frame_end=1+ceil(duration·24)`.
- THE SYSTEM SHALL create the rigid body world with `substeps_per_frame=20`, `solver_iterations=20`, `use_split_impulse=True`, and the point cache range equal to the scene range.

### FR-020 Build (§3.1, §8.4)
- THE SYSTEM SHALL build each spec via one `BUILDERS` dispatch table, creating meshes from Layer-1 vertex data at true size (scale (1,1,1), origin = center of volume).
- THE SYSTEM SHALL set rigid body type, shape, mass, friction, restitution, damping, `use_margin=True`, `collision_margin`, deactivation flags, and custom props `rube_name`, `rube_type`.

### FR-021 Overlap check (§8.5)
- WHEN any two rigid bodies, at least one of them dynamic (passive–passive pairs are skipped, design D-18), overlap at frame 1 — including touching-coplanar and fully-contained configurations — excluding pairs joined by a constraint with `disable_collisions`, THE SYSTEM SHALL report `OVERLAP` naming both, set status `invalid`, and SHALL NOT bake.

### FR-022 Bake (§8.6)
- THE SYSTEM SHALL free existing bakes, set frame 1, and bake under `temp_override(scene, point_cache)`.
- WHEN baking raises `RuntimeError`, THE SYSTEM SHALL set status `bake_failed` with `BAKE_FAILED` and the message.

### FR-023 Analysis (§8.7)
- THE SYSTEM SHALL sample every dynamic body's world transform at every frame and compute `first_motion_frame` (displacement > 5 mm or rotation > 2° vs frame 1), `max_speed`, `final_position`, `final_tilt_deg`, `fell_over` (Domino/Block with tilt > 60°), `left_bounds` (center outside floor area or z < −1), `at_rest_at_end` (speed < 0.01 m/s over the last 0.5 s).
- THE SYSTEM SHALL emit events `started_moving`, `fell_over`, `left_bounds`, sorted by frame.
- WHEN any `max_speed > 30 m/s` or a body moves > 2 m in one frame, THE SYSTEM SHALL add warning `UNSTABLE`.

### FR-024 Rendering (§8.8, §8.9)
- THE SYSTEM SHALL render with `BLENDER_WORKBENCH`, solid shading, object colors, 960×540 PNG, 6 stills evenly spaced incl. first and last frame to `out/frames/f_XXXX.png`.
- WHEN `--video` is given, THE SYSTEM SHALL render an H.264 MP4 of the full range to `out/video.mp4`.
- THE SYSTEM SHALL save `out/machine.blend` with the baked cache, using absolute paths only.

### FR-025 Report (§9.2)
- THE SYSTEM SHALL write `report.json` with keys `status, issues, timing, entities, events, artifacts, blender_version, rube_version, elapsed_s`, omitting passive bodies from `entities`.
- WHEN the framework itself fails, THE SYSTEM SHALL set status `internal_error` and include the traceback.

### FR-026 API probe (§1.1, M0)
- THE SYSTEM SHALL provide `tests/blender/probe_api.py` that re-verifies every fact in SPEC §1.1 on the installed Blender and exits non-zero naming any fact that changed.

### FR-027 LLM-facing documentation (§11)
- THE SYSTEM SHALL ship `docs/API_FOR_LLM.md` (< 300 lines): conventions, every public signature with defaults, anchors, report format, all issue codes with typical fixes, examples A3/A5/A6, rules of thumb, and the final default physics values.
- THE SYSTEM SHALL ship a README with setup and usage.

### FR-028 Claude Code skill for machine authors (post-v1 request, 2026-10-24)
As a Claude Code user, I want a `rube` skill, so that Claude can design, simulate and iterate on a machine without re-learning the workflow each time.
- THE SYSTEM SHALL ship a project skill at `.claude/skills/rube/SKILL.md` that points to `docs/API_FOR_LLM.md` as the single API reference (no duplicated API listing) and prescribes the loop: plan stages with success criteria → write script → `rube check` until clean → `rube run` → summarize report → inspect stills → fix → repeat.
- THE SYSTEM SHALL ship `.claude/skills/rube/scripts/summarize_report.py` (stdlib only) that prints status, all issues, one line per dynamic entity and the event timeline from a `report.json` or output directory, and states how many lines it omitted when truncating.
- WHEN the summarizer is given a missing or malformed report, IT SHALL exit non-zero with a one-line error.

## Non-functional requirements

- **NFR-001 Layer isolation (§3.1).** No module outside `rube/blender/` imports `bpy`, `bmesh` or `mathutils`. Verified by a unit test that scans the source.
- **NFR-002 Dependencies (§1).** Runtime: stdlib only (system Python ≥ 3.11); inside Blender: stdlib, `bpy`, `bmesh`, `mathutils`, `numpy`. Dev-only: `pytest`, `ruff`.
- **NFR-003 Blender API discipline (§3.1).** Only the allowed `bpy.ops` (`rigidbody.world_add`, `rigidbody.object_add`, `rigidbody.constraint_add`, `ptcache.bake`, `ptcache.free_bake_all`, `render.render`, `wm.save_as_mainfile`), each under `temp_override`; never read `context.active_object`/`context.object`. Verified by a source-scan unit test.
- **NFR-004 Determinism (§10.1, A9).** No randomness in the framework; the same spec yields final positions identical to 1e-6 on the same machine/build.
- **NFR-005 Performance (A10).** Ball → ramp → chain with 6 stills completes in < 60 s wall time on the target Mac.
- **NFR-006 Untrusted scripts (§3.3, §10.1).** The author script runs only in system Python; Blender receives only JSON data. The import guard is documented as a guard rail, not a sandbox.
- **NFR-007 Code documentation (user request).** Every module has a docstring with layer, responsibility and implemented requirement IDs; every public class/function has a docstring; non-obvious logic carries "why" comments. Decisions are recorded in `specs/design.md`.
- **NFR-008 Quality gate.** `pytest` (unit) and `ruff check` + `ruff format --check` pass on every commit.

## Acceptance scenarios (§10.3)

Each is an `examples/*.py` script plus a `tests/blender` test asserting on `report.json`.

| ID | Scenario | Pass condition | Requirements |
|---|---|---|---|
| A1 | Ball dropped from 1 m | status ok; final z = radius ± 0.01; at rest; no warnings | FR-005, FR-019–025 |
| A2 | Ball rolls down a 20° Ramp | ball final x > `ramp.bottom.x`; no `UNSTABLE` | FR-008 |
| A3 | 20-domino straight chain, `tilt_first_deg=10` | all fell over; fall frames strictly increase | FR-007, FR-011 |
| A4 | Chain along a 90° curve (3 waypoints) | all fell over | FR-011 |
| A5 | Ball → ramp → chain (no tilt) | first domino starts after ball; last domino fell over | FR-008, FR-011 |
| A6 | Ball through 2-turn spiral | ball within 0.3 m of `spiral.exit`; never left_bounds | FR-009, FR-010 |
| A7 | Ball on one end of a Lever | other end rises ≥ 0.1 m | FR-012 |
| A8 | Ball intersecting a block | status invalid, `OVERLAP` naming both, no bake | FR-021 |
| A9 | A5 twice | final positions identical to 1e-6 | NFR-004 |
| A10 | A5 with 6 stills | wall time < 60 s | NFR-005 |
| A11 | Script with `import os` | `DISALLOWED_IMPORT`, Blender not launched | FR-016 |
| A12 | `Camera.follow(ball)` in A2 | video renders; ball within middle 50 % of every still | FR-014, FR-024 |

## Out of scope (§0)

GUI add-on; beauty renders (EEVEE/Cycles, materials, lighting); multiple cameras/cuts;
kinematic/animated pushers; initial velocities; pulleys, ropes, soft bodies, fluids;
non-flat domino paths; a hardened sandbox; an LLM calling loop.
