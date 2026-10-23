# Rube: Rube Goldberg Machine Framework for Blender — Implementation Spec

Status: v1 spec, ready for implementation. Supersedes `architecture.md`.

## 0. Read this first

There are **two different AIs** involved. Do not confuse them:

| Role | Who | What they write |
|---|---|---|
| **Implementer** | Claude Code (you, reading this) | The `rube` Python package itself |
| **Machine author** | An LLM using the finished package | Short declarative scripts like `examples/ball_into_dominoes.py` |

Everything in §5–§7 is the public API the *machine author* sees. It must be small,
forgiving, and produce errors that tell the author exactly what to change.

**Goal of v1:** a machine author writes ~20 lines of Python, runs one command, and gets
back (a) a JSON report saying what physically happened, and (b) preview images / video.
The author iterates on the script using the report.

**Non-goals for v1** (do not build): GUI add-on, final "beauty" renders (EEVEE/Cycles,
materials, lighting), multiple camera cuts, kinematic/animated pushers, initial velocities,
pulleys/ropes/soft bodies/fluids, non-flat domino paths, a hardened sandbox, an LLM
calling loop (the framework is called *by* such a loop; it does not contain one).

---

## 1. Environment (verified on the target machine)

- **Blender 5.2.3 LTS**, binary at `/Applications/Blender.app/Contents/MacOS/Blender`
  (allow override via env var `RUBE_BLENDER`).
- Blender's bundled Python only for Layers 2–3. No `pip install` into Blender.
  Allowed inside Blender: stdlib, `bpy`, `bmesh`, `mathutils`, and `numpy` (bundled).
- Layer 1 + CLI run under ordinary system Python ≥ 3.11 with **no third-party deps**
  (dev-only: `pytest`).
- Every run is a **fresh Blender process**: `Blender -b --factory-startup --python-exit-code 1 --python <bootstrap> -- <args>`.

### 1.1 Verified Blender 5.2.3 API facts (these correct `architecture.md`)

| Topic | Fact | Consequence |
|---|---|---|
| Rigid body world steps | `steps_per_second` **does not exist**. Use `rigidbody_world.substeps_per_frame` (default 10 → 240 Hz at 24 fps) | The old spec's "240 steps/sec" was already the default and the attribute name would raise |
| Solver iterations | `rigidbody_world.solver_iterations` (default 10) | |
| Margin | Property is `rigid_body.collision_margin` (default **0.04**), with `use_margin` | `rigid_body.margin` does not exist |
| Bounciness | Blender name is `restitution` (default 0.0) | |
| Damping defaults | `linear_damping` 0.04, `angular_damping` 0.1 | Must be tuned for rolling balls |
| Cache range | `rigidbody_world.point_cache.frame_end` defaults to 250 independently of `scene.frame_end` | Must be set explicitly, or the sim silently stops at frame 250 |
| Bake | `with bpy.context.temp_override(scene=sc, point_cache=rw.point_cache): bpy.ops.ptcache.bake(bake=True)` works headless | |
| Viewport render | `bpy.ops.render.opengl()` **fails in background mode** ("no opengl context") | Use `BLENDER_WORKBENCH` + `bpy.ops.render.render(write_still=True)`; ~0.2 s/frame at 640×360 |
| Output paths | `//relative` paths fail when no .blend is saved | Always use absolute paths |
| Rigid body add | `bpy.ops.rigidbody.object_add(type=...)` works under `temp_override(object=, active_object=, selected_objects=, selected_editable_objects=)` | Avoid relying on real selection state |
| Bullet failures | A bad scene does **not** raise Python exceptions — objects tunnel, explode, or Blender hangs | `try/except` is not a safety net; use pre-bake validation, post-bake analysis, and a process timeout (§8) |

The first implementation task re-checks this table with a probe script
(`tests/blender/probe_api.py`) and fails loudly if any fact changes.

---

## 2. Conventions (part of the public contract)

- Units: meters, kilograms, seconds. Gravity −9.81 m/s² on Z.
- Axes: **Z up**. Right-handed. Ground surface top is `z = 0`.
- Angles in the public API are **degrees**. Convert to radians only in Layer 2.
- `facing_deg`: yaw around +Z, 0° = facing +X, 90° = facing +Y.
- Placement semantics (exact; explain them in the LLM doc):
  - `Ball(center=...)`: sphere center.
  - `Block` / `Domino(position=...)`: **bottom-center** (the point resting on the surface below).
  - `Ramp(start=..., end=...)`: endpoints of the **top surface centerline**; `start` is the high end.
- Positions accept `tuple[float, float, float]` or `Vec3`.
- Names: optional; auto-generated as `<Type>_<n>` (e.g. `Domino_3`). Must be unique;
  duplicate → validation error. The Blender object gets exactly this name.
- Build order = registration order (needed for determinism).
- Frame rate fixed at 24 fps. `duration` is in seconds; frames = `ceil(duration*24)`.
- Placement helpers add `CLEARANCE = 0.002` m so objects start just above surfaces, never intersecting.

---

## 3. Architecture

### 3.1 Layers and ownership

| Layer | Package | Imports `bpy`? | Owns |
|---|---|---|---|
| 1. Spec (declarative) | `rube` (everything except `rube.blender`) | **Never** | Public API, defaults, geometry math, anchors, static validation |
| 2. Builder | `rube.blender.build`, `rube.blender.physics` | Yes | Turning specs into Blender objects, rigid bodies, constraints |
| 3. Simulation & output | `rube.blender.simulate`, `rube.blender.render`, `rube.blender.scene` | Yes | Scene reset, world settings, bake, analysis/report, camera, rendering |
| Runner | `rube.cli` | Never (spawns Blender) | `rube check`, `rube run`, timeout, exit codes |

Rules:
- Layer 1 objects are plain **dataclasses** with no `spawn()` methods. Layer 2 uses a single
  dispatch table `BUILDERS: dict[type, Callable[[Spec, BuildContext], list[bpy.types.Object]]]`.
  (This replaces `Entity.spawn()` / `_apply_rigid_body()` from the old doc, which leaked `bpy` into Layer 1.)
- **All geometry is computed in Layer 1** (vertex lists for custom meshes, domino transforms,
  anchors) so it is unit-testable without Blender. Layer 2 only creates data blocks from it.
- Layer 2 creates meshes with `bpy.data` + `bmesh` / `mesh.from_pydata`, never
  `bpy.ops.mesh.primitive_*`. Geometry is built at true size around the object origin, so
  object scale is always `(1,1,1)` and origin = center of volume **by construction**
  (this removes the need for `transform_apply` / `origin_set`).
- The only `bpy.ops` allowed: `rigidbody.world_add`, `rigidbody.object_add`,
  `rigidbody.constraint_add`, `ptcache.bake`, `ptcache.free_bake_all`, `render.render`,
  `wm.save_as_mainfile`. Each is called under `bpy.context.temp_override(...)` with explicit objects.
- Never read `bpy.context.active_object` / `bpy.context.object`; keep references returned by your own code.
- No singleton. One `Machine` per script.

### 3.2 Layout

```
pyproject.toml              # package "rube", console script "rube = rube.cli:main", no runtime deps
src/rube/
  __init__.py               # re-exports the public API only
  vec.py                    # Vec3 (frozen dataclass: + - * /, dot, cross, length, normalized)
  errors.py                 # Issue, RubeValidationError
  entities.py               # Floor, Ball, Block, Domino, Ramp, Lever + PhysicsProps + anchors
  geometry.py               # channel_mesh(), catmull_rom(), arc-length resampling, MeshSpec
  generators.py             # domino_chain(), spiral_ramp()
  camera.py                 # Camera.static(), Camera.follow()
  machine.py                # Machine: registry, validate(), to_dict()/from_dict()
  cli.py                    # rube check / rube run
  blender/
    bootstrap.py            # entry point inside Blender
    scene.py                # reset scene, units, world settings
    physics.py              # rigid body + constraint helpers
    build.py                # BUILDERS dispatch
    simulate.py             # overlap check, bake, sampling, analysis -> report dict
    render.py               # camera, workbench settings, stills, video, .blend save
tests/
  unit/                     # pytest, system Python
  blender/                  # run inside Blender, see §10
examples/                   # one script per acceptance scenario
docs/API_FOR_LLM.md         # prompt-ready API reference for the machine author (§11)
```

### 3.3 Data flow

```
machine.py (LLM script, defines `machine`)
   │  rube run machine.py --out out/
   ▼
cli.py: static import check → load spec in system Python → machine.validate()
   │       (invalid → write report.json, exit 2, Blender never starts)
   │  machine.to_dict() → out/spec.json
   ▼
Blender subprocess (timeout) → bootstrap.py → Machine.from_dict(spec.json)
   → scene.reset → build → overlap check → bake → sample & analyze → render → save .blend
   ▼
out/report.json, out/frames/*.png, out/machine.blend, [out/video.mp4]
```

Passing the spec as JSON (instead of re-executing the LLM script inside Blender) means the
untrusted script only ever runs in system Python, and Blender only sees data.

---

## 4. Public API — Machine

```python
class Machine:
    def __init__(self, name: str = "machine", duration: float = 10.0, floor: bool = True,
                 floor_size: float = 20.0): ...
    def add(self, item: Entity | Group) -> Entity | Group   # returns the same object for chaining
    def set_camera(self, camera: Camera) -> None            # optional; default auto-frames everything
    def validate(self) -> list[Issue]                       # pure Layer 1; never raises for content problems
    def to_dict(self) -> dict ;  @classmethod from_dict(d) -> Machine
```

- `floor=True` auto-adds a passive `Floor` (box `floor_size × floor_size × 0.2`, top at z=0).
  Machine authors frequently forget a floor; objects then fall forever.
- `duration` range: 1–60 s.
- `Group` = an object holding several entities (returned by generators and `Lever`). Adding a
  group registers all its members in order.
- Limits: ≤ 500 rigid bodies (bake time). Exceeding → error `TOO_MANY_BODIES`.

## 5. Public API — Entities

Common physics fields on every entity (`PhysicsProps`, keyword-only):

| Field | Meaning | Maps to |
|---|---|---|
| `dynamic: bool` | falls/moves (`ACTIVE`) vs fixed (`PASSIVE`) | `rigid_body.type` |
| `mass: float` (kg) | ignored if not dynamic | `mass` |
| `friction: float` 0–1 | | `friction` |
| `bounciness: float` 0–1 | | `restitution` |
| `color: str` | named color (`"red"`, `"blue"`, …) for previews | `obj.color` + Workbench `OBJECT` color |

Per-class defaults (implementer may tune them **only** to make acceptance tests pass; record final values in `docs/API_FOR_LLM.md`):

| Class | Shape / collision | Dynamic | Mass | Friction | Bounciness | Damping lin/ang | Margin |
|---|---|---|---|---|---|---|---|
| `Floor` | box / `BOX` | no | – | 0.6 | 0.0 | – | 0.001 |
| `Ball(center, radius=0.1)` | UV sphere 32×16 / `SPHERE` | yes | 0.5 | 0.4 | 0.1 | 0.04 / 0.02 | 0.001 |
| `Block(position, size=(x,y,z), facing_deg=0)` | box / `BOX` | yes | from density 600 kg/m³ | 0.5 | 0.0 | defaults | 0.001 |
| `Domino(position, facing_deg=0, tilt_deg=0, size=(0.1,0.4,0.8))` | box / `BOX` | yes | from density 600 kg/m³ | 0.5 | 0.0 | defaults | 0.001 |
| `Ramp(start, end, width=0.4, thickness=0.05, rails=False)` | plank / `BOX`; with rails: channel mesh / `MESH` | no | – | 0.3 | 0.0 | – | 0.001 box, 0.005 mesh |
| `Lever(...)` | see §5.3 | plank yes, fulcrum no | 1.0 | 0.5 | 0.0 | defaults | 0.001 |

Domino size is `(thickness, width, height)`; `facing_deg` is the direction it falls toward.
`tilt_deg` pre-tilts it toward `facing_deg` around its bottom front edge — this is the
v1 way to start a chain. Tilt is applied in Layer 1 math (position + rotation), not by Blender.

### 5.1 Deactivation (domino stability)

Dominoes set `use_deactivation=True, use_start_deactivated=True` so long chains don't
jitter before being hit — **except** a domino with `tilt_deg > 0`, which must start active
(a start-deactivated body ignores gravity until struck).

### 5.2 Anchors (critical for the machine author)

LLMs are bad at 3D arithmetic. Every entity exposes read-only anchor points (`Vec3`) so
components can be connected without trigonometry:

| Entity | Anchors / helpers |
|---|---|
| `Ramp` | `.top` (= start), `.bottom` (= end), `.direction` (unit, downhill), `.slope_deg`, `.ball_spawn(radius) -> Vec3` (center just above the surface, 1.5·radius in from the top edge, includes clearance, correct for slope) , `.exit(distance=0.0) -> Vec3` (ground-level point beyond the bottom end) |
| `Block` / `Domino` | `.top_center`, `.front` (bottom point on the falling side) |
| `Ball` | `.bottom` |
| `DominoChain` (Group) | `.first`, `.last` (`Domino`), `.dominoes`, `.start`, `.end` (path endpoints) |
| `SpiralRamp` (Group) | `.entry`, `.exit` (top-surface centerline points), `.ball_spawn(radius)` |
| `Lever` (Group) | `.left_end`, `.right_end` (top surface points of plank ends) |

### 5.3 `Lever(pivot, length=2.0, width=0.3, thickness=0.05, facing_deg=0, tilt_deg=0, fulcrum_height=None)`

A seesaw: dynamic plank + passive triangular-prism fulcrum + a `HINGE` rigid-body
constraint at `pivot` (axis horizontal, perpendicular to `facing_deg`), with
`disable_collisions=True` between plank and fulcrum. `pivot` is the hinge point;
fulcrum height defaults to `pivot.z`. This exercises the constraint subsystem
(`rigidbody_world.constraints` collection, constraint on an Empty at the pivot).

## 6. Public API — Generators (pure Layer 1 math)

### 6.1 `domino_chain(points, *, spacing=None, count=None, size=(0.1,0.4,0.8), tilt_first_deg=0, color=None) -> DominoChain`

- `points`: ≥ 2 waypoints on flat ground (all equal z). Path = **Catmull-Rom spline through
  the waypoints** (passes through them, unlike Bezier control points; 2 points = straight line).
- Exactly one of `spacing` / `count`; if neither, `spacing = 0.5 × height`.
- Dominoes placed at **equal arc length** (sample the spline densely, build cumulative length table,
  invert) — *not* equal spline parameter `t`, which gives uneven gaps.
- Each domino faces the path tangent (`facing_deg = atan2(ty, tx)`).
- Validation (errors, with hints suggesting a concrete fix):
  - `CHAIN_SPACING`: spacing must be within `[0.3, 0.75] × height` (closer = touching/overlap,
    farther = chain stops).
  - `CHAIN_TURN`: yaw change between neighbours must be ≤ 15° (sharper turns break the chain).
  - `CHAIN_NOT_FLAT`: waypoint z values differ.
  - Too few dominoes (< 2).

### 6.2 `spiral_ramp(center, radius, height, turns, *, track_width=0.25, wall_height=0.08, thickness=0.03, clockwise=False) -> SpiralRamp`

- `center` = ground point under the spiral axis; the track descends from `center.z + height`
  to `center.z + thickness`.
- Geometry: a **U-channel** (floor + two side walls, solid thickness) swept along a helix.
  The channel mesh comes from `geometry.channel_mesh(path_points, width, wall_height, thickness)`;
  `Ramp(rails=True)` uses the **same function** with a straight path.
- Passive, collision shape `MESH`.
- Plus a passive support column at the center (cylinder, radius = `radius − track_width/2 − 0.01`)
  so it looks and behaves like a structure.
- Validation: `SLOPE_TOO_SHALLOW` if slope = `height / (2π·radius·turns)` < tan(4°);
  `SLOPE_TOO_STEEP` if > tan(25°) (ball skips over walls); `TRACK_TOO_NARROW` checked when
  a ball is spawned with `ball_spawn(r)`: requires `track_width ≥ 2.5 r` and `wall_height ≥ 0.6 r`.
  Segment count: ≥ 48 per turn.

## 7. Public API — Camera

```python
Camera.static(position, look_at, lens_mm=35)
Camera.follow(target: Entity, offset=(-3, -3, 2), lens_mm=35)
```

- Default (no camera set): static camera auto-framed on the bounding box of all non-floor
  entities from a 3/4 elevated view, entire box in frame.
- `follow`: camera gets `COPY_LOCATION` (target, `use_offset=True`, base location = `offset`)
  + `TRACK_TO` (target, `TRACK_NEGATIVE_Z`, up `UP_Y`). **Never parent the camera to a rigid
  body** (the old doc's approach): the camera would inherit the ball's spin.
- Exactly one camera per machine in v1.

---

## 8. Layer 2–3 behaviour (inside Blender)

Executed in this order by `bootstrap.py`. Each step is a function with a single responsibility.

1. **Reset**: delete all objects, meshes, materials, cameras, lights, collections in
   `bpy.data` (do **not** use `read_factory_settings`; it can invalidate the running script's
   context and is redundant with `--factory-startup`).
2. **Scene settings**: metric units, scale 1.0, fps 24, `frame_start=1`,
   `frame_end = 1 + ceil(duration·24)`.
3. **Rigid body world**: create; `substeps_per_frame = 20`, `solver_iterations = 20`,
   `use_split_impulse = True`; `point_cache.frame_start/end` = scene range.
4. **Build** entities in registration order via `BUILDERS`. For each rigid body set: type,
   shape, mass, friction, restitution, damping, `use_margin=True`, `collision_margin` (per table),
   deactivation flags. Assign `obj["rube_name"]`, `obj["rube_type"]` custom props.
5. **Overlap check** (pre-bake): for every pair of rigid bodies whose world AABBs intersect,
   test `mathutils.bvhtree.BVHTree.FromObject(...).overlap(...)`. Skip pairs joined by a
   constraint with `disable_collisions`. Any overlap → issue `OVERLAP` naming both entities,
   status `invalid`, **skip bake**. (Overlaps at frame 1 are the #1 cause of explosions.)
6. **Bake**: `free_bake_all`, `scene.frame_set(1)`, bake with `temp_override` (§1.1).
   Catch `RuntimeError` → status `bake_failed` with message. Hangs are handled by the CLI timeout.
7. **Sample & analyze**: for each frame, `scene.frame_set(f)` and read every body's
   `matrix_world`. Compute per entity:
   - `first_motion_frame`: first frame where displacement > 5 mm or rotation > 2° from frame 1.
   - `max_speed` (m/s), `final_position`, `final_tilt_deg` (angle of local +Z vs world +Z).
   - `fell_over`: dominoes/blocks with `final_tilt_deg > 60`.
   - `left_bounds`: center outside floor area, or below z = −1.
   - `at_rest_at_end`: speed < 0.01 m/s over the last 0.5 s.
   - Events list (sorted by frame): `started_moving`, `fell_over`, `left_bounds`.
   - Instability warning `UNSTABLE` if any `max_speed > 30 m/s` or a body moved > 2 m in one frame.
8. **Render** (`BLENDER_WORKBENCH`, solid shading, `color_type='OBJECT'`, 960×540, PNG):
   still frames at 6 evenly spaced times including first and last → `out/frames/f_XXXX.png`.
   With `--video`: FFMPEG MP4 (H.264) of the full range → `out/video.mp4`.
9. **Save** `out/machine.blend` (with baked cache) for human inspection.
10. Write `out/report.json` (§9). Exit 0 even if the machine "didn't work" physically —
    that is information for the author, not a crash.

## 9. Report and errors (the machine author's feedback channel)

### 9.1 `Issue`

```python
@dataclass(frozen=True)
class Issue:
    severity: Literal["error", "warning"]
    code: str          # stable identifier, e.g. "CHAIN_SPACING"
    entity: str | None # entity name(s), comma-separated for pairs
    message: str       # what is wrong, with the actual numbers
    hint: str          # concrete fix, e.g. "use spacing between 0.24 and 0.60"
```

Validation collects **all** issues before returning (an LLM fixing one error per run is slow).
Codes in v1: `NAME_DUPLICATE`, `OUT_OF_RANGE`, `INVALID_ARGUMENT`, `TOO_MANY_BODIES`,
`CHAIN_SPACING`, `CHAIN_TURN`, `CHAIN_NOT_FLAT`, `SLOPE_TOO_SHALLOW`, `SLOPE_TOO_STEEP`,
`TRACK_TOO_NARROW`, `OUTSIDE_FLOOR`, `TOO_SMALL` (any dimension < 0.02 m — Bullet is unstable
below this), `MASS_RATIO` (warning, > 100:1 between touching-candidate bodies),
`OVERLAP`, `UNSTABLE` (warning), `DISALLOWED_IMPORT`, `SCRIPT_ERROR`, `NO_MACHINE`,
`BAKE_FAILED`, `TIMEOUT`.

Programming errors in the framework itself are not Issues — let them raise and surface as
status `internal_error` with traceback in the report.

### 9.2 `report.json`

```json
{
  "status": "ok | invalid | bake_failed | timeout | internal_error",
  "issues": [{"severity": "error", "code": "OVERLAP", "entity": "Ball_1,Ramp_1", "message": "...", "hint": "..."}],
  "timing": {"fps": 24, "frame_start": 1, "frame_end": 241, "duration_s": 10.0},
  "entities": [{"name": "Domino_1", "type": "Domino", "initial_position": [0,0,0],
                "final_position": [0.3,0,0.05], "first_motion_frame": 37, "first_motion_time_s": 1.5,
                "max_speed": 2.1, "final_tilt_deg": 84.0, "fell_over": true,
                "left_bounds": false, "at_rest_at_end": true}],
  "events": [{"frame": 37, "time_s": 1.5, "entity": "Domino_1", "event": "started_moving"}],
  "artifacts": {"frames": ["frames/f_0001.png"], "video": null, "blend": "machine.blend"},
  "blender_version": "5.2.3", "rube_version": "0.1.0", "elapsed_s": 12.4
}
```

Passive bodies are omitted from `entities` (they never move).

## 10. CLI, safety, testing

### 10.1 CLI

```
rube check machine.py            # system Python only; validate and print issues; exit 0/2
rube run machine.py --out DIR [--video] [--timeout 300]
```

- Script contract: the script must define a top-level variable `machine` of type `Machine`.
  Missing → `NO_MACHINE`. Scripts must not call `bpy` or any run method.
- **Static import check** before executing the script: parse with `ast`; allow only imports of
  `rube`, `math`, `random`; anything else → `DISALLOWED_IMPORT`. Also reject `__import__`,
  `eval`, `exec`, `open` names. This is a guard rail, not a sandbox — document that untrusted
  scripts should run in a container.
- Script exceptions → `SCRIPT_ERROR` with the traceback's last frame in the user script.
- Blender runs as a subprocess with `--timeout` (default 300 s); on expiry kill the process
  group and write status `timeout`.
- Exit codes: 0 ran (check report), 2 invalid, 3 bake_failed, 4 timeout, 1 internal_error.
  `report.json` is written in **every** case.
- Determinism: no randomness inside the framework; `random` in scripts is allowed but the
  author should seed it. Same spec → identical results on the same machine and Blender build.

### 10.2 Tests

- `tests/unit` (pytest, system Python): Vec3, every validation code, anchors, arc-length
  spacing uniformity (gap variance < 1 mm), domino yaw follows tangent, spiral slope and
  entry/exit, `to_dict`/`from_dict` round-trip, CLI import check, and a test asserting
  **no module outside `rube/blender/` imports `bpy`, `bmesh` or `mathutils`**.
- `tests/blender`: driven by `pytest` in system Python, each test calls `rube run` on an
  `examples/` script into a tmp dir and asserts on `report.json`.
- `tests/blender/probe_api.py`: re-verifies §1.1.

### 10.3 Acceptance scenarios (each is an `examples/*.py` + a blender test)

| # | Scenario | Pass condition |
|---|---|---|
| A1 | Ball dropped from 1 m onto floor | status ok; final z = radius ± 0.01; at rest; no warnings |
| A2 | Ball rolls down a 20° `Ramp` | ball's final x is beyond `ramp.bottom.x`; no `UNSTABLE` |
| A3 | Straight chain of 20 dominoes, `tilt_first_deg=10` | all 20 `fell_over`; fall frames strictly increase along the chain |
| A4 | Chain along a 90° curve (3 waypoints) | all fell over |
| A5 | Ball → ramp → chain (no tilt) | first domino `started_moving` after ball does; last domino fell over |
| A6 | Ball through `spiral_ramp` (2 turns) | ball passes within 0.3 m of `spiral.exit`; never `left_bounds` |
| A7 | Ball dropped on one end of a `Lever` | other end rises ≥ 0.1 m |
| A8 | Ball placed intersecting a block | status invalid, `OVERLAP` naming both, no bake performed |
| A9 | Run A5 twice | final positions identical to 1e-6 |
| A10 | A5 with 6 stills | total wall time < 60 s on this Mac |
| A11 | Script with `import os` | `DISALLOWED_IMPORT`, Blender not launched |
| A12 | `Camera.follow(ball)` in A2 | video renders; ball is within the middle 50% of the frame in every still (check via projected coordinates with `bpy_extras.object_utils.world_to_camera_view`) |

If default physics values must change to pass A1–A7, change them in one place (the defaults
table in code) and update §5 and `docs/API_FOR_LLM.md`.

## 11. `docs/API_FOR_LLM.md` (deliverable)

A compact (< 300 lines) reference meant to be pasted into the machine author's prompt:
conventions (§2), every public signature with defaults, anchors, the report format, all
issue codes with typical fixes, three complete example scripts (A3, A5, A6), and practical
rules of thumb (domino spacing ≈ half height, ramp slope 10–30°, start balls with
`ramp.ball_spawn(r)`, always check `fell_over`/`events` in the report).

## 12. Implementation milestones

Each milestone ends with its tests green. Do not start the next one before.

1. **M0 – Probe**: `probe_api.py` confirms §1.1 on Blender 5.2.3.
2. **M1 – Layer 1 core**: Vec3, Issue, entities (Floor, Ball, Block, Domino), Machine,
   validation, serialization, `rube check`, import guard. Unit tests.
3. **M2 – Pipeline**: CLI `run`, bootstrap, reset, world settings, builders for M1 entities,
   overlap check, bake, analysis, report. Acceptance A1, A8, A9, A11.
4. **M3 – Ramp + chains**: `Ramp` (plank), `domino_chain`. A2–A5.
5. **M4 – Rendering**: default camera, stills, video, `.blend`, `Camera.static/follow`. A10, A12.
6. **M5 – Channels**: `channel_mesh`, `Ramp(rails=True)`, `spiral_ramp`. A6.
7. **M6 – Lever**: hinge constraints. A7.
8. **M7 – LLM docs + examples**: `docs/API_FOR_LLM.md`, README with setup and usage.
