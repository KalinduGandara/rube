# rube

Declarative Rube Goldberg machines. A machine is a short Python script (balls, ramps,
domino chains, spirals, levers); `rube` validates it, simulates it with Blender rigid-body
physics, and writes a JSON report plus preview images and optional video. Built to be written
by an LLM: errors are structured issues with concrete fixes.

## Setup

Requires Python 3.11+ and Blender (tested with 5.2.3). Set `RUBE_BLENDER` if Blender is not at
`/Applications/Blender.app/Contents/MacOS/Blender`.

```
python3 -m venv .venv
.venv/bin/pip install -e .[dev]
```

## Usage

```
.venv/bin/rube check examples/a5_ball_ramp_chain.py          # validate only, no Blender; exit 0/2
.venv/bin/rube run examples/a5_ball_ramp_chain.py --out out/ # simulate; add --video, --timeout N
```

Exit codes of `rube run`: 0 ok, 2 invalid, 3 bake failed, 4 timeout, 1 internal error.

## Output layout

```
out/report.json        status, issues, per-entity results, events, artifacts
out/spec.json          the machine as data (what Blender consumed)
out/frames/f_XXXX.png  6 preview stills
out/video.mp4          with --video
out/machine.blend      open in Blender to inspect or re-render
out/blender.log        Blender stdout/stderr
```

## Writing machines

See `docs/API_FOR_LLM.md` (compact API reference with examples, meant to be pasted into an
LLM prompt) and `examples/`.

In Claude Code, the project skill `.claude/skills/rube/` (invoke with `/rube` or just ask for a
machine) runs the design → check → run → read report → fix loop, and
`.claude/skills/rube/scripts/summarize_report.py out/<name>` turns a report into a short summary.

## Testing

```
.venv/bin/pytest tests/unit -q       # pure Python, fast
.venv/bin/pytest tests/blender -q    # needs Blender; slower
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

## Project docs

`SPEC.md` (product spec), `specs/` (requirements, design, tasks, progress), `CLAUDE.md`
(conventions). Layer 1 (everything except `src/rube/blender`) never imports `bpy`.
