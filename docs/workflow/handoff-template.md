---
module: workflow/handoff-template
purpose: Record session state so the next Claude Code session can resume without human direction
dependencies: workflow/build-sequence.md, workflow/session-start.md
last_updated: 2026-03-01
---

## Purpose

Solves Claude Code's memory problem. Filled in at the end of every session. Read at the start of the next. Contains everything needed to resume work with zero human prompting — the next session reads this file and knows exactly where to start.

---

## Scope

- Covers session state: what passed, what's next, what decisions were made, what blockers exist.
- Excludes: build instructions (in `workflow/build-sequence.md`), architecture decisions (in the relevant `docs/` file).
- This file is overwritten at the end of every session. It records current state only, not history — history lives in `docs/operation/changelog.md`.

---

## Key Decisions

- **Always overwrite, never append.** This file reflects the current state of the build, not a log of all sessions. Appending creates confusion about which entry is current.
- **`next_step` is the single most important field.** It must be filled in before ending any session. A blank `next_step` forces the next session to infer state from the changelog — slower and error-prone.
- **Decisions made this session must be recorded.** If you changed a threshold, picked a fallback behaviour, or deviated from a doc spec — record it here so the next session doesn't undo it.
- **Blockers are first-class citizens.** A blocker recorded here is more valuable than a blocker kept in memory. The next session or a human reviewer can act on it immediately.

---

## Constraints

- Fill in every field. Do not leave fields blank except `blockers` (if none).
- `next_step` must reference an exact step name from `workflow/build-sequence.md`.
- `decisions_made` entries must reference the relevant doc file if a spec was deviated from.
- Update `last_updated` to today's date every time this file is written.

---

## Interfaces / Dependencies

Read by: `workflow/session-start.md` (O1 step)
Written by: Claude Code at the end of every session
Also readable by: the human operator to check build progress

---

## Risks / Considerations

- **Forgotten update:** If Claude Code finishes a step and the session ends without updating this file, the next session will re-build the same step. O2 verification in session-start.md catches this — the test will pass and the session will auto-advance.
- **Wrong next_step:** If next_step references a step that does not exist in build-sequence.md, session-start.md O1 will fail to find a doc reference. Correct by reading the build-sequence step list and setting a valid step name.
- **Blocker not resolved:** If a blocker is recorded and the next session starts, Claude Code should attempt to resolve the blocker before proceeding to next_step. If unresolvable, flag for human review.

---

## Session State — Fill In At End of Every Session

```
═══════════════════════════════════════════════════════
SESSION HANDOFF — Update this section every session end
═══════════════════════════════════════════════════════

date:              2026-03-03
session_number:    4
duration_estimate: ~1 hour

─── What was completed this session ───────────────────

completed_step:    Operational run — full end-to-end test with fixed RFPMart scraper
test_result:       PASSED — 183 scraped (182 RFPMart + 1 CanadaBuys), 6 filtered, 1 PURSUE (score 82), all agents completed
changelog_updated: yes

─── Where to start next session ────────────────────────

next_step:         BUILD COMPLETE — all 13 steps done. Operational phase: monitor daily runs, set SERPAPI_KEY for LinkedIn contact sourcing, install playwright for MERX.
doc_to_read_first: docs/quality/utd-loop.md (ongoing quality loop)
test_command:      DRY_RUN=true python3 -m pytest tests/ -q

─── Decisions made this session ────────────────────────

decisions_made:
  - "RFPMart fix confirmed working — 182 listings from Canada/USA scraped via anchor-tag parsing."
  - "FilterAgent correctly processed 183 listings via pre-filter LLM (handled 429 rate-limit retries automatically)."
  - "ScoringAgent correctly scored 'Senior Advisor, Data Systems and Analytics Service' at 82 PURSUE."
  - "ContactSourcer ran but found 0 contacts — SERPAPI_KEY not configured; LinkedIn search skipped."

─── Deviations from doc spec ───────────────────────────

deviations:
  - "GitHub Actions created before Step 13 completes — build-sequence says 'after Step 13' but created at user request. No functional impact."
  - "test_resend.py created as one-off connectivity test — not part of pipeline, safe to delete."

─── Blockers ────────────────────────────────────────────

blockers:
  - "MERX scraper returns 0 — site now requires login (merged into SOVRA). Playwright is installed and working; MERX itself has no public listing without credentials."
  - "ContactSourcer finds 0 contacts — SERPAPI_KEY not set in .env. Add key to enable LinkedIn search."

─── Current passing tests ───────────────────────────────

passing:
  - [x] Step 1  — database.py
  - [x] Step 2  — pipeline.py
  - [x] Step 3  — scraper.py
  - [x] Step 4  — filter_agent.py
  - [x] Step 5  — scoring_agent.py + fixtures
  - [x] Step 6  — scoring_critic.py
  - [x] Step 7  — contact_sourcer.py
  - [x] Step 8  — contact_critic.py
  - [x] Step 9  — outreach_writer.py
  - [x] Step 10 — digest_agent.py
  - [x] Step 11 — main.py
  - [x] Step 12 — calibration fixtures
  - [x] Step 13 — final smoke test (DRY_RUN=false)

─── Environment ─────────────────────────────────────────

dry_run_status:    false (DRY_RUN not set in .env — live mode)
db_has_data:       yes (183 listings scraped; 1 PURSUE opportunity saved)
last_live_run:     2026-03-03 (full pipeline — 183 scraped, 6 filtered, 1 PURSUE scored 82)

═══════════════════════════════════════════════════════
END OF HANDOFF
═══════════════════════════════════════════════════════
```
