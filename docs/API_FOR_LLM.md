# rube API reference (for the machine author)

Write ONE Python script that defines `machine = Machine(...)`. Check it with `rube check script.py`
(no Blender, instant, lists ALL problems), then `rube run script.py --out out/ [--video]`.
Allowed imports: `rube` (and its public modules such as `rube.entities`), `math`, `random`
only. No `__dunder__` attributes, `getattr`/`globals`/`vars`/`eval`/`exec`/`open`/`input`; only
everyday builtins (`range`, `len`, `min`, `print`, ...); the script must finish within 30 s.
Fix every `error` issue using its `hint`.

## Conventions
- Meters, kilograms, seconds, **degrees** for every angle (`facing_deg`, `tilt_deg`, `slope_deg`).
- Z is up; the floor top is at z = 0; yaw 0 deg points along +X, positive turns counter-clockwise.
- Points are `(x, y, z)` tuples. Boxes (Block, Domino) are placed by their **bottom-center**.
- Ball `center` is the sphere center (a ball resting on the floor has `center.z = radius`).
- Everything has `name=` (optional, auto `Type_n`) and `dynamic, mass, friction, bounciness, color`
  keyword overrides (`None` = class default). Colors: red green blue yellow orange purple white black gray brown wood.
- Frames: 24 fps, frame 1 is t = 0. Max 500 rigid bodies, duration 1-60 s.

## API
```python
from rube import Machine, Ball, Block, Domino, Ramp, Lever, Camera, domino_chain, spiral_ramp
Machine(name="machine", duration=10.0, floor=True, floor_size=20.0)
  .add(item) -> item      # entity or group; returns it so you can keep a handle
  .set_camera(Camera)     # optional; default auto-frames the whole machine
  .validate() -> [Issue]
Ball(center, radius=0.1)                              # anchor: .bottom
Block(position, size=(0.2,0.2,0.2), facing_deg=0)     # anchors: .top_center .front
Domino(position, facing_deg=0, tilt_deg=0, size=(0.1,0.4,0.8))  # falls toward facing_deg
Ramp(start, end, width=0.4, thickness=0.05, rails=False)        # start = high end of the TOP surface
  # anchors: .top .bottom .direction .slope_deg .ball_spawn(radius=0.1) .exit(distance=0.0)
  # rails=True makes a U-channel with 0.08 m walls so balls stay on
domino_chain(points, spacing=None, count=None, size=(0.1,0.4,0.8), tilt_first_deg=0, color=None)
  # smooth spline THROUGH flat waypoints (equal z); two points = straight line.
  # spacing 0.3-0.75 x height (default 0.5 x height); give spacing OR count. Group: .dominoes
spiral_ramp(center, radius, height, turns, track_width=0.25, wall_height=0.08,
            thickness=0.03, clockwise=False)   # helix channel + support column
  # anchors: .entry .exit .ball_spawn(r)   slope = height/(2 pi radius turns) must be 4-25 deg
Lever(pivot, length=2.0, width=0.3, thickness=0.05, facing_deg=0, tilt_deg=0, fulcrum_height=None)
  # hinged seesaw; anchors .left_end .right_end (top surface), parts .plank .fulcrum .hinge
Camera.static(position, look_at, lens_mm=35)
Camera.follow(target_entity, offset=(-3,-3,2), lens_mm=35)   # constant world offset
```
Block/Domino `tilt_deg` in [0, 90): a tilted domino falls by itself, the way to start a chain.
Passive bodies (Ramp, Floor, spiral, fulcrum) never move. Bodies must not interpenetrate (`OVERLAP`).

## Default physics (the DEFAULTS table in `rube/entities.py`)
| Type | dynamic | mass | friction | bounce | margin m | color |
|---|---|---|---|---|---|---|
| Floor | no | - | 0.6 | 0 | 0.001 | gray |
| Ball | yes | 0.5 kg | 0.4 | 0.1 | 0.001 | red |
| Block | yes | 600 kg/m3 | 0.5 | 0 | 0.001 | blue |
| Domino | yes | 600 kg/m3 | 0.5 | 0 | 0.001 | yellow |
| Ramp | no | - | 0.3 | 0 | 0.001 | wood |
| RampRails | no | - | 0.3 | 0 | 0.005 | wood |
| SpiralTrack | no | - | 0.3 | 0 | 0.005 | wood |
| SupportColumn | no | - | 0.5 | 0 | 0.001 | gray |
| LeverPlank | yes | 1 kg | 0.5 | 0 | 0.001 | wood |
| Fulcrum | no | - | 0.5 | 0 | 0.001 | gray |
Damping: linear 0.04, angular 0.1 (Ball angular 0.02). Dominoes start deactivated until hit.

## Report (`out/report.json`, written for every outcome)
`status`: `ok | invalid | bake_failed | timeout | internal_error` (exit 0 / 2 / 3 / 4 / 1).
Keys: `issues` (`severity, code, entity, message, hint`), `timing` (`fps, frame_start, frame_end,
duration_s`), `entities`, `events`, `artifacts` (`frames` PNGs, `video`, `blend`), `blender_version`,
`rube_version`, `elapsed_s`. Each dynamic entity record: `name, type, initial_position,
final_position, first_motion_frame, first_motion_time_s, max_speed, final_tilt_deg, fell_over,
left_bounds, at_rest_at_end`. Events: `{frame, time_s, entity, event}` with `started_moving`,
`fell_over`, `left_bounds`, `at_rest`, sorted by frame. **Always check `fell_over` and `events`**:
status `ok` only means the simulation ran, not that the machine did what you wanted.

## Issue codes and fixes
- `NAME_DUPLICATE`: give entities unique names. `INVALID_ARGUMENT`/`OUT_OF_RANGE`: read the hint.
- `TOO_MANY_BODIES`: at most 500 rigid bodies. `TOO_SMALL`: every dimension >= 0.02 m.
- `OUTSIDE_FLOOR`: move inside the floor or raise `floor_size`.
- `CHAIN_SPACING`: spacing 0.3-0.75 x height; use `count=` instead. `CHAIN_TURN`: widen the curve
  (turn radius too tight for the spacing). `CHAIN_NOT_FLAT`: all waypoints need the same z.
- `SLOPE_TOO_SHALLOW`/`SLOPE_TOO_STEEP`: spiral slope must be 4-25 deg (change height or turns).
- `TRACK_TOO_NARROW`: spiral `track_width` >= 2.5 x ball radius, `wall_height` >= 0.6 x radius.
- `MASS_RATIO` (warning): > 100:1 between bodies; reduce the mass difference.
- `OVERLAP`: two bodies interpenetrate; move one (resting contact is fine, overlap is not).
- `UNSTABLE` (warning): speeds > 30 m/s; lower drops or masses. `BAKE_FAILED`/`TIMEOUT`: simplify.
- `DISALLOWED_IMPORT`/`SCRIPT_ERROR`/`NO_MACHINE`: only rube/math/random; define `machine`.

## Rules of thumb
- Domino spacing about half the height. A default 0.5 kg ball cannot topple a default 0.8 m
  domino (19.2 kg): use smaller dominoes (`size=(0.05, 0.2, 0.4)`) behind a ball, or a heavier ball.
- Ramp slope 10-30 deg. Use `end.z = 0` so the ramp meets the floor. Start balls with
  `ramp.ball_spawn(r)`; hand off with `ramp.exit(distance)`.
- Use `rails=True` or a spiral when a ball must stay on its track.
- Duration: leave room (8-10 s) for chains to finish. Prefer anchors over hand arithmetic.

## Example: straight domino chain (A3)
```python
"""Acceptance scenario A3: a straight chain of 20 dominoes started by tilting the first one.

Expected (``rube run``): all 20 dominoes ``fell_over``, and their ``fell_over`` event frames
strictly increase along the chain (each domino falls after the one before it).
"""

from rube import Machine, domino_chain

machine = Machine(name="a3_domino_chain", duration=8)

# 20 dominoes 0.4 m apart (half their 0.8 m height) along a 7.6 m line; the first one is
# pre-tilted 10 degrees so it falls on its own and starts the chain.
chain = machine.add(domino_chain([(-3.8, 0, 0), (3.8, 0, 0)], count=20, tilt_first_deg=10))
```

## Example: ball, ramp, chain (A5)
```python
"""Acceptance scenario A5: a ball rolls down a ramp and knocks over a domino chain (no tilt).

Expected (``rube run``): the first domino's ``started_moving`` comes after the ball's, and the
last domino ``fell_over``. Running it twice gives identical final positions (A9).

Why 0.4 m dominoes: the default 0.5 kg ball cannot topple a default 0.8 m domino (19.2 kg at
600 kg/m^3); a 0.4 m domino (2.4 kg) falls easily. Spacing defaults to half the height.
"""

import math

from rube import Ball, Machine, Ramp, domino_chain

machine = Machine(name="a5_ball_ramp_chain", duration=8)

# 20 degree ramp with 2 m of run; its low end meets the floor at x = -1.
ramp = machine.add(Ramp(start=(-3, 0, 2 * math.tan(math.radians(20))), end=(-1, 0, 0)))
ball = machine.add(Ball(center=ramp.ball_spawn(0.1), radius=0.1))

# The chain starts on the floor 0.5 m past the ramp and runs straight on to x = 3.
chain = machine.add(domino_chain([ramp.exit(0.5), (3, 0, 0)], size=(0.05, 0.2, 0.4)))
```

## Example: spiral ramp (A6)
```python
"""Acceptance scenario A6: a ball rolls down a 2-turn spiral ramp and out onto the floor.

Expected (``rube run``): the ball passes within 0.3 m of ``spiral.exit`` and never leaves
the floor area. Shows the spiral anchors: ``spiral.ball_spawn(r)`` puts the ball in the
groove just after the entry (and enables the TRACK_TOO_NARROW check for that radius).

Slope = height / (2 pi radius turns) = 1.5 / (2 pi 0.8 2) ~ 8.5 deg (allowed 4-25 deg).
The 0.08 m ball fits the default track: track_width 0.25 >= 2.5 r, wall_height 0.08 >= 0.6 r.
"""

from rube import Ball, Machine, spiral_ramp

machine = Machine(name="a6_spiral", duration=8)

spiral = machine.add(spiral_ramp(center=(0, 0, 0), radius=0.8, height=1.5, turns=2))
ball = machine.add(Ball(center=spiral.ball_spawn(0.08), radius=0.08))
```
