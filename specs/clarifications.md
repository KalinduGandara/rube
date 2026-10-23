# Clarifications

Source of truth: [`SPEC.md`](../SPEC.md) (supersedes the deleted `architecture.md` / `srs.md`).
This file records questions asked before implementation, the answers, and agreed assumptions.

## Round 1 — 2026-10-23

| # | Question | Answer | Consequence |
|---|---|---|---|
| Q1 | System `python3` is 3.10 (spec requires ≥ 3.11) and has no pytest. Dev environment? | **venv on Python 3.13** | `.venv` created from `/opt/homebrew/bin/python3.13`; package installed editable with dev extras (`pytest`, `ruff`). |
| Q2 | Approval gates (requirements / design / tasks)? | **One combined gate** | `requirements.md`, `design.md`, `tasks.md` are approved together; the implementation workflow then runs M0–M7 without stopping except for real spec gaps. |
| Q3 | Git strategy? | **Branch `feat/v1` + one commit per task** | The deletion of `srs.md` goes into the first commit. Nothing is pushed. |
| Q4 | Quality tools besides pytest? | **ruff only** (lint + format check) | No type checker. Runtime stays dependency-free. |

## Agreed assumptions (no question needed; derived from SPEC.md or defaults)

- **A-1 Physics tuning.** Per SPEC §5, default physics values may be tuned *only* to make
  acceptance tests A1–A7 pass. They live in one table in code (`rube/entities.py: DEFAULTS`)
  and every change is mirrored in `docs/API_FOR_LLM.md` and logged in `specs/progress.md`.
- **A-2 Unpassable acceptance test.** If an acceptance scenario cannot pass after reasonable
  tuning, implementation stops and asks; tests are never weakened or deleted to go green.
- **A-3 Analysis math in Layer 1.** Post-bake analysis (first motion, tilt, fell_over, …)
  operates on plain sampled transforms, so it lives in pure-Python `rube/analysis.py` and is
  unit-tested; `rube/blender/simulate.py` only samples and calls it. (Small layout deviation
  from SPEC §3.2; the behaviour is unchanged. See design D-6.)
- **A-4 Report builder in Layer 1.** `report.json` must be written by the CLI (invalid,
  timeout, internal error) *and* by Blender (ok, bake_failed), so one builder lives in
  `rube/report.py` and both sides use it. (Design D-7.)
- **A-5 A12 check.** "Ball in the middle 50 % of the frame" is verified by a test helper script
  run inside Blender against the saved `machine.blend`, not by adding fields to the report
  schema. (Design D-10.)
- **A-6 Blender tests** are marked `@pytest.mark.blender` and are skipped when the Blender
  binary is not found, so the unit suite stays fast.
- **A-7 Documentation.** Every module carries a docstring stating its layer, responsibility and
  the requirement IDs it implements; every public symbol has a docstring; non-obvious logic has
  "why" comments. Decisions are recorded in `specs/design.md` (§9 Decisions).
