---
name: rube
description: Design, simulate and debug Rube Goldberg machines with the rube framework (Blender rigid-body physics). Use when the user asks to build, design, simulate, render or fix a Rube Goldberg machine, chain reaction, domino run, marble/ball run, ramp, spiral track or lever contraption, or asks to write, check or run a rube machine script.
---

# rube: build a working Rube Goldberg machine

You are the **machine author**. You write a short declarative Python script and let `rube`
validate it, simulate it in headless Blender and report what physically happened. You never
call Blender or `bpy` yourself, and you never edit the framework to make a machine work.

## 0. Learn the API (every time)

Read `docs/API_FOR_LLM.md` in full before writing a script. It is the only API reference:
signatures, defaults, anchors, report format, issue codes and three worked examples. More
examples are in `examples/`; they are the acceptance suite, so read them but don't edit them.

Commands (from the repo root; outside this repo use `rube` from wherever it is installed):

```bash
.venv/bin/rube check machines/<name>.py                              # instant, no Blender
.venv/bin/rube run machines/<name>.py --out out/<name> [--video]     # simulate + render
python3 .claude/skills/rube/scripts/summarize_report.py out/<name>   # readable report
```

## 1. Plan the chain of causation

Before writing code, break the user's idea into **stages**. For each stage, write down the
trigger and the report fact that proves it happened. Example:

| # | Stage | Proof in report |
|---|---|---|
| 1 | Ball rolls down ramp | `Ball_1` `started_moving` early; reaches the ramp exit area |
| 2 | Ball hits the chain | `Domino_1` `started_moving` **after** `Ball_1` |
| 3 | Chain runs to the end | every Domino `fell_over`, fall times increasing |

Put this table in the script's module docstring. It is your test plan, and it shows the user
what the machine is meant to do. If the request is vague, pick a modest design (3–5 stages),
state your choice and go; don't stall on questions a run can answer.

## 2. Write the script

- Save it as `machines/<snake_name>.py`. It must define a top-level `machine = Machine(...)`.
  Only `rube`, `math` and `random` can be imported, and if you use `random`, seed it.
- **Connect stages with anchors, not hand arithmetic**: `ramp.ball_spawn(r)`, `ramp.exit(d)`,
  `spiral.ball_spawn(r)` / `spiral.exit`, `chain.first` / `chain.last`, `lever.left_end`,
  `block.top_center`. Anchors already include the 2 mm start clearance.
- Prefer generators (`domino_chain`, `spiral_ramp`, `Lever`) over placing pieces one by one.
- Give key bodies explicit `name=`s so the report reads well, and set `duration` with slack
  (8–10 s for anything that includes a chain).
- Tune behaviour with per-entity overrides (`mass=`, `friction=`, `bounciness=`, sizes,
  slopes). Never change the framework's `DEFAULTS` table.

## 3. Check, then run

1. `rube check`. Fix **every** `error` using its `hint`, and re-run until it exits 0. Read the
   warnings too: `MASS_RATIO` often predicts a failed hand-off.
2. `rube run --out out/<name>`. Exit codes: 0 means the simulation ran; 2 invalid (e.g.
   `OVERLAP`, found only in Blender); 3 bake failed; 4 timeout; 1 internal error (a framework
   bug: show the traceback to the user rather than working around it).
3. Summarize the report with `summarize_report.py`. **`status: ok` only means the simulation
   ran.** Check every stage of your plan against the entity lines, the "N/M fell over" totals
   and the event timeline.
4. Look at the stills when a stage fails or when placement matters. Open the PNG paths listed
   under `artifacts:` with your image-reading tool, and check at least the first, a middle and
   the last frame.

## 4. Diagnose and fix

Change one thing per iteration and keep a short log (what you changed and what happened).

| Symptom in report | Likely cause | Fix |
|---|---|---|
| `OVERLAP A,B` | Bodies interpenetrate at frame 1 | Move one apart; place it with an anchor |
| First domino never moves after the ball arrives | Ball too light for the domino, or it stops short | Smaller dominoes `size=(0.05,0.2,0.4)`, heavier ball, steeper ramp, or a shorter `exit(d)` gap |
| Chain stops part-way (`k/N fell over`) | Spacing too wide or a turn too tight | Spacing ≈ 0.5 × height; widen the curves; check `CHAIN_TURN` |
| Domino moves before the ball reaches it | Too close to the ramp, or pre-tilted | Increase the `exit(d)` distance; set `tilt_first_deg=0` |
| Ball `LEFT_BOUNDS` or flies off a track | Too fast, or no walls | `rails=True`, a gentler slope (10–20°), a lower drop |
| Ball stalls on a ramp or spiral | Slope too shallow or friction too high | Raise the slope (spiral 6–15° works well); lower the `friction` |
| Lever end doesn't rise | Load too light or too close to the pivot | Drop it nearer the end (`lever.left_end`); heavier ball |
| `UNSTABLE` warning | Huge speeds or masses | Lower the drops and mass ratios; avoid tiny, heavy bodies |
| Nothing reached the last stage in time | `duration` too short | Raise `duration` (max 60 s) |

Stop after about 8 run cycles without progress. Report what works, what doesn't and the best
next idea, rather than looping.

## 5. Deliver

Tell the user:
- the script path and the stage table, with each stage marked ✅/❌ and its proof (times, fell-over counts);
- the output paths (`report.json`, the stills, `video.mp4` if you ran with `--video`, and `machine.blend`, which opens in Blender);
- any physics overrides you used and why.

Offer a `--video` run if you haven't made one.
