---
module: workflow/build-sequence
purpose: Define the exact build order, per-step doc reference, test command, and done criteria
dependencies: all docs/agent/*.md, docs/data/*.md, docs/quality/*.md
last_updated: 2026-03-01
---

## Purpose

Master execution plan for building the full agent. Claude Code works through this file top to bottom. Each step is atomic: read the doc, build the file, run the test, confirm done, move on. Do not proceed to the next step until the current step's done criteria pass.

---

## Scope

- Covers all 11 source files in build order plus 2 fixture files and 2 workflow files.
- Excludes: GitHub Actions setup — workflow files live in `.github/workflows/` and are created after Step 13. Threshold tuning is a post-build operational task.
- This file is the single authority on build order. `docs/operation/antipatterns.md` governs what is prohibited within each step.

---

## Key Decisions

- **Order is non-negotiable.** Each file depends on the one before it. Skipping ahead causes import errors that are harder to debug than building in order.
- **DRY_RUN=true for all tests.** No live API calls during build. Flip to false only for a final end-to-end smoke test after Step 11.
- **One step per Claude Code prompt.** Never ask for two files in one prompt. Splitting keeps context clean and errors isolated.
- **Test failure blocks progression.** If a test fails, fix it before moving to the next step. A broken foundation breaks everything above it.

---

## Constraints

- Run all test commands exactly as written. Do not paraphrase or abbreviate.
- After every step: append one row to `docs/operation/changelog.md`.
- If a step produces an error Claude Code cannot fix in 2 attempts: record the blocker in `workflow/handoff-template.md` and stop.

---

## Interfaces / Dependencies

State keys written by each agent (for reference during build):

| Step | File | Reads | Writes |
|------|------|-------|--------|
| 2 | pipeline.py | — | errors, timings |
| 3 | scraper.py | — | listings |
| 4 | filter_agent.py | listings | filtered, skipped |
| 5 | scoring_agent.py | filtered | scored |
| 6 | scoring_critic.py | scored | validated |
| 7 | contact_sourcer.py | validated | enriched |
| 8 | contact_critic.py | enriched | enriched |
| 9 | outreach_writer.py | enriched | ready |
| 10 | digest_agent.py | DB query | email sent |
| 11 | main.py | — | orchestrates all |

---

## Build Steps

**Step 1 — src/database.py**
- Read: `docs/data/schema.md`
- Build: all 9 functions listed in that file
- Test: `python3 -c "from src.database import init_db, is_duplicate, has_score, save_opportunity; init_db(); print('OK')"`
- Done: prints OK, no exceptions

**Step 2 — src/pipeline.py**
- Read: `docs/agent/orchestrator.md`
- Build: Pipeline class + run_with_timeout helper
- Test: `python3 -c "from src.pipeline import Pipeline; p = Pipeline([]); r = p.run({}); print('OK')"`
- Done: prints OK, stop signal test passes

**Step 3 — src/agents/scraper.py**
- Read: `docs/agent/scraper.md`
- Build: ScraperAgent with scrape_all, scrape_merx, scrape_rfpmart, scrape_canadabuys
- Test (DRY_RUN=true): `python3 -c "from src.agents.scraper import ScraperAgent; r = ScraperAgent().run({'listings':[]}); assert len(r['listings']) > 0; print('OK')"`
- Done: returns ≥1 listing with all 7 required keys

**Step 4 — src/agents/filter_agent.py**
- Read: `docs/agent/filter.md`
- Build: FilterAgent — pre-filter LLM, threshold check, cache check, failure defaults to pass
- Test (DRY_RUN=true): `python3 -c "from src.agents.filter_agent import FilterAgent; r = FilterAgent().run({'listings':[{'title':'T','org':'O','raw_description':'D','url':'https://t.com/1','source':'MERX','deadline':'2026-06-01','value':'100K'}],'filtered':[],'skipped':[]}); assert 'filtered' in r; print('OK')"`
- Done: filtered and skipped keys present, counts sum to input count

**Step 5 — tests/fixtures + src/agents/scoring_agent.py**
- Read: `docs/agent/scorer.md`, `docs/data/capability-profile.md`
- Build fixtures first: `tests/fixtures/sample_listing.json`, `tests/fixtures/sample_scored.json`
- Build: ScoringAgent — fetch, extract_relevant_sections, scoring LLM call, JSON parse, cache check
- Test (DRY_RUN=true): `python3 -c "import json; from src.agents.scoring_agent import ScoringAgent; l=json.load(open('tests/fixtures/sample_listing.json')); r=ScoringAgent().run({'filtered':[l],'scored':[]}); assert len(r['scored'])==1; print('OK')"`
- Done: scored has 1 item with all 9 required keys

**Step 6 — src/agents/scoring_critic.py**
- Read: `docs/agent/scorer.md` (critic section), `docs/quality/drift.md`
- Build: ScoringCritic — schema validation, score band check, calibration_check, 2-loop cap
- Test (DRY_RUN=true): `python3 -c "from src.agents.scoring_critic import ScoringCritic; import json; s=json.load(open('tests/fixtures/sample_scored.json')); r=ScoringCritic().run({'scored':[s],'validated':[]}); assert len(r['validated'])==1; print('OK')"`
- Done: validated has 1 item, decision_log is a list

**Step 7 — src/agents/contact_sourcer.py**
- Read: `docs/agent/contact.md`
- Build: ContactSourcer — website find, LinkedIn search, Hunter.io, merge, max 3 contacts
- Test (DRY_RUN=true): run with one validated item scoring ≥70, assert enriched has contacts key
- Done: enriched populated, contacts list present (may be empty in DRY_RUN)

**Step 8 — src/agents/contact_critic.py**
- Read: `docs/agent/contact.md` (critic section)
- Build: ContactCritic — seniority check, domain check, 2-loop cap
- Test (DRY_RUN=true): pass 2 contacts (1 valid, 1 invalid title), assert only valid one survives
- Done: invalid contacts filtered, enriched key populated

**Step 9 — src/agents/outreach_writer.py**
- Read: `docs/agent/outreach.md`
- Build: OutreachWriter — scoring LLM call, 200 token cap, fallback string, sanitise rfp_title
- Test (DRY_RUN=true): pass 1 contact, assert outreach_opening key present in result
- Done: ready key populated, outreach_opening on every contact

**Step 10 — src/agents/digest_agent.py**
- Read: `docs/agent/digest.md`
- Build: DigestAgent — HTML build (inline styles only), Resend send, mark_sent, log_pipeline_run
- Test (DRY_RUN=true): `python3 -c "from src.agents.digest_agent import DigestAgent; from src.database import init_db; init_db(); r=DigestAgent().run({}); assert isinstance(r, bool); print('OK')"`
- Done: returns bool, HTML contains digest subject line

**Step 11 — main.py**
- Read: `docs/agent/overview.md`
- Build: run_daily_scrape, send_weekly_digest, send_failure_alert
- Test (DRY_RUN=true): `python3 main.py` — all 8 agent log lines must appear
- Done: Run complete line printed, no unhandled exceptions

**Step 12 — Calibration fixtures**
- Read: `docs/quality/calibration.md`, `docs/quality/drift.md`
- Build: `tests/fixtures/calibration_set.json` with 10 golden examples
- Update: scoring_critic.py to load and run calibration_check
- Test: `python3 -c "import json; d=json.load(open('tests/fixtures/calibration_set.json')); assert len(d)==10; print('OK')"`
- Done: 10 valid examples, all 8 required fields present

**Step 13 — Final smoke test (DRY_RUN=false)**
- Set DRY_RUN=false in .env
- Run: `python3 main.py`
- Expected: real scrape runs, real listings scored, pipeline_runs table has 1 row
- Done: no crashes, at least 1 listing in DB, log shows all 8 agent lines

---

## Risks / Considerations

- **Step 5 is the most complex.** If scoring_agent.py fails, check JSON fence stripping and section extraction before debugging the prompt itself.
- **Step 13 costs real API money.** Budget ~$0.50–$2.00 for the first live run depending on listing volume that day.
- **Import errors at any step** mean a prior step is broken. Do not debug the current step — go back and fix the broken dependency first.
