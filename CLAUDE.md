# CLAUDE.md

Rube: a Python framework where an LLM ("machine author") writes short declarative scripts
describing Rube Goldberg machines; `rube run` simulates them in headless Blender and returns
`report.json` + preview images.

## Source of truth

- `SPEC.md` — product spec (v1).
- `specs/` — spec-driven development artifacts: `clarifications.md`, `requirements.md`
  (FR/NFR IDs), `design.md` (architecture + decisions D-n), `tasks.md` (checklist),
  `progress.md` (log + traceability). **Resume work by reading `specs/tasks.md` and
  `specs/progress.md`, then continue from the first unchecked task.**
- Spec and code must never drift: change `requirements.md`/`design.md`/`tasks.md` first.

## Stack

- Layer 1 + CLI: Python ≥ 3.11 stdlib only (`src/rube/`, never imports `bpy`/`bmesh`/`mathutils`).
- Layers 2–3: `src/rube/blender/`, runs inside Blender 5.2.3 bundled Python
  (`/Applications/Blender.app/Contents/MacOS/Blender`, override with `RUBE_BLENDER`).
- Dev: `.venv` (Python 3.13) with `pytest`, `ruff`.

## Commands

```bash
.venv/bin/pip install -e '.[dev]'          # setup
.venv/bin/pytest tests/unit                # fast unit suite
.venv/bin/pytest -m blender tests/blender  # acceptance tests (launch Blender, slow)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/rube check examples/<file>.py
.venv/bin/rube run examples/<file>.py --out out/<name> [--video]
```

## Conventions

- Every module docstring states its layer, responsibility and the requirement IDs it implements.
  Every public class/function has a docstring; non-obvious logic gets a "why" comment.
- Public API angles in degrees, meters/kg/s, Z up, ground top z=0 (SPEC §2).
- Content problems → `Issue` objects (collect all), never exceptions. Framework bugs raise.
- Only the `bpy.ops` whitelisted in SPEC §3.1, always under `temp_override`; never read
  `bpy.context.active_object`.
- Tests first; never weaken a test to make it pass. Physics default changes go in the one
  `DEFAULTS` table and are logged in `specs/progress.md` and `docs/API_FOR_LLM.md`.
- Commits: one per task on branch `feat/v1`, message `<type>(<area>): T-NNN <summary> [FR-xxx]`.
