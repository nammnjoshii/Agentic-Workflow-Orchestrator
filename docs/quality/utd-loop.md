---
module: quality/utd-loop
purpose: Define the Understand-Do-Verify protocol and all verification checkpoints
dependencies: none
last_updated: 2026-02-28
---

## Purpose

Mandatory three-phase workflow for every code change. No task is complete until all V1–V7 checkpoints pass. This protocol applies to Claude Code sessions and human edits equally.

---

## Scope

- Covers all three phases: Understand (U), Do (D), Verify (V).
- Applies to: new features, bug fixes, schema changes, prompt edits, config changes.
- Excludes: changelog updates (V7 covers that), documentation-only edits.

---

## Key Decisions

- **Understand before writing.** Ambiguity at U-phase costs less than ambiguity at V-phase.
- **Incremental Do.** One function → verify → next. No batching.
- **V7 is mandatory.** No changelog entry = task is not complete.
- **Escalation over guessing.** Stop when: schema change spans files, task contradicts `operation/antipatterns.md`, or V-step fails twice.

---

## Constraints

- Never skip to a later V-step because an earlier one "seems fine."
- Syntax check (`python3 -m py_compile`) runs before any test — failing syntax blocks all subsequent steps.
- Integration smoke tests use exact copy-pasteable commands. No paraphrasing.

---

## Interfaces / Dependencies

**U — Understand (answer all before writing code):**
1. What exactly is being asked? Restate in one sentence.
2. Which files will this touch?
3. Which interfaces change? (function signatures, dict schemas, DB columns)
4. Does this conflict with `operation/antipatterns.md`?
5. What does "done" look like? Define the test that proves it.

**D — Do:**
- Write incrementally. One function, then verify, then next.
- Follow `data/schema.md` column names exactly.
- One concern per function — no multi-responsibility functions.

**V — Verify (all must pass before declaring done):**

| Step | Command / Check |
|------|----------------|
| V1 | `python3 -m py_compile src/{file}.py` |
| V2 | `pytest tests/test_{module}.py -v` |
| V3 | Integration smoke test (copy-paste from `quality/testing.md`) |
| V4 | `DRY_RUN=true python3 main.py` — full pipeline passes |
| V5 | Trace state dict keys end-to-end — no missing or misnamed keys |
| V6 | Re-read original task — does output match what was asked? |
| V7 | Add one row to `operation/changelog.md` with today's date |

---

## Risks / Considerations

- **Skipping V4:** Full pipeline dry run catches cross-agent key mismatches that unit tests miss. Never skip it.
- **Stale fixtures:** If fixture files are outdated, V3 passes but V4 fails. Update fixtures after any schema change.
- **V7 compliance:** Treat changelog as a code quality gate. Skipping it leaves the next session without context on what changed.
