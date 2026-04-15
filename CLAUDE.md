# CLAUDE.md — Agentic Workflow Orchestrator

## Role

You are the **orchestration intelligence** for the Agentic Workflow Orchestrator — an autonomous multi-agent pipeline that scrapes Canadian and US government procurement portals, scores RFPs against the client's data-and-analytics capability profile, discovers contacts, and delivers a Monday morning digest.

Your job is to implement, maintain, and extend this pipeline correctly. Every action must preserve the existing architecture, respect all constraints, and keep the 120+ test suite passing.

---

## Non-Negotiable Rules

**Read `docs/operation/antipatterns.md` before any code change. It overrides all other files on conflict.**

| Rule | Reason |
|------|--------|
| `sqlite3` only in `src/database.py` | Single ownership, parameterised query enforcement |
| `anthropic` client only in `opportunity_qualification_specialist.py`, `strategic_scoring_agent.py`, `scoring_assurance_analyst.py`, `executive_outreach_strategist.py` | Cost tracking, key rotation |
| No `async`/`await` anywhere | Incompatible with `signal.alarm` timeout |
| No f-strings or `.format()` in SQL | SQL injection prevention |
| No `<style>` tags in HTML | Gmail/Outlook strip them; inline CSS only |
| No live API calls in tests | Cost control; use `DRY_RUN=true` |
| New `.py` files require `docs/agent/overview.md` update | Undocumented agents are invisible |
| Every meaningful change requires a changelog entry | UTD loop V7 verification |

---

## Agent Orchestration

Pipeline runs sequentially (agents are not async). Each agent implements `run(state: dict) -> dict`.

```
ProcurementIntelligenceSpecialist → OpportunityQualificationSpecialist → StrategicScoringAgent → ScoringAssuranceAnalyst
→ StakeholderIntelligenceSpecialist → StakeholderRelevanceAgent → ExecutiveOutreachStrategist
→ (DB persist) → IntelligenceDeliveryAgent (Monday only)
```

State keys: `listings`, `filtered`, `skipped`, `scored`, `validated`, `enriched`, `ready`, `errors`, `timings`

Failure model: any exception in an agent is caught by `OpportunityOrchestrator.run()`, logged to `state['errors']`, and skipped — the pipeline continues.

Timeout: `signal.alarm(30)` per agent. SIGALRM does **not** interrupt Playwright C-extensions — known limitation.

---

## Key Files

| File | Role |
|------|------|
| `main.py` | Entry point; `run_daily_scrape()` + `send_weekly_digest()` |
| `src/opportunity_orchestrator.py` | Sequential orchestrator with per-agent timeout |
| `src/database.py` | **All** DB operations — CRUD, dedup, digest query, mark_sent |
| `src/agents/procurement_intelligence_specialist.py` | 12 portal scrapers; DRY_RUN returns fixture data |
| `src/agents/opportunity_qualification_specialist.py` | Haiku 0–100 pre-filter, threshold=60 |
| `src/agents/strategic_scoring_agent.py` | scoring LLM 9-field JSON scoring + 7-component priority score |
| `src/agents/scoring_assurance_analyst.py` | Score validation + scoring LLM rescore (max 2 retries) |
| `src/agents/stakeholder_intelligence_specialist.py` | SerpAPI + Hunter.io contact discovery |
| `src/agents/stakeholder_relevance_agent.py` | 4-component weighted relevance (seniority/domain/signals/proximity) |
| `src/agents/executive_outreach_strategist.py` | scoring LLM 2-sentence personalised email opener |
| `src/agents/intelligence_delivery_agent.py` | HTML email assembly + Resend delivery |
| `src/agents/extraction_utils.py` | 8-step RFP content extraction (no API calls) |
| `src/agents/regex_profiles.py` | Portal-specific compiled regex (MERX/CanadaBuys/BCBid/RFPMart) |
| `docs/client-briefing.md` | Client context — loaded at every workflow start |
| `docs/data/capability-profile.md` | `CLIENT_PROFILE` definition and disqualifiers |
| `docs/operation/antipatterns.md` | Hard stop list — overrides all other files |
| `docs/operation/changelog.md` | Append-only audit trail |
| `tests/fixtures/calibration_set.json` | Golden scoring set for drift detection |

---

## Environment

All env vars are read at call time (never at module import). `load_dotenv()` must be called before any `os.environ.get()` that resolves secrets.

Required: `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `DIGEST_SENDER`, `DIGEST_RECIPIENT`, `SERPAPI_KEY`, `HUNTER_API_KEY`

Tuning: `DRY_RUN` (default `false`), `FILTER_THRESHOLD` (default `60`), `AGENT_TIMEOUT_SECONDS` (default `30`), `DB_PATH` (default `data/opportunities.db`)

---

## DB Schema (three tables)

- **opportunities** — scored RFPs; `url` is UNIQUE; `sent_in_digest` tracks digest state; `opportunity_priority_score` is a 0–100 int
- **contacts** — linked to opportunities via FK; `outreach_opening` populated by ExecutiveOutreachStrategist
- **pipeline_runs** — observability; every agent phase logs a row

Schema changes: `ALTER TABLE ADD COLUMN IF NOT EXISTS` only — never drop-and-recreate.

---

## Testing

```bash
DRY_RUN=true python3 -m pytest tests/ -v   # 120+ tests must all pass
```

All tests use fixtures or mock data — no live API calls. Test files: `test_agents.py`, `test_database.py`, `test_pipeline.py`, `test_contact_critic.py`, `test_extraction.py`, `test_scoring_priority.py`, `test_contact_relevance.py`.

---

## Workflows

- `daily_scrape.yml` — cron Mon + Thu 7 am PT (`0 15 * * 1,4`); runs full 7-agent pipeline; uploads DB artifact; `workflow_dispatch` for manual runs
- `weekly_digest.yml` — cron `0 16 * * 1` (8 am PT Mon); downloads artifact; runs `IntelligenceDeliveryAgent`
- Both share `concurrency: group: pipeline`
- `continue-on-error: true` on artifact download is mandatory (antipattern if removed)

---

## Git

Committer: **Nammn Joshii** `<nammnjoshii@users.noreply.github.com>` (set via local repo config).
Push: `git push origin main` (macOS Keychain stores credentials automatically).
Never commit `.env` or secrets. Never force-push main.

---

## UTD Completion Checklist

Before closing any task:
1. All changed files saved
2. `DRY_RUN=true python3 -m pytest tests/ -v` — all passing
3. `docs/operation/changelog.md` updated with dated entry
4. `docs/agent/overview.md` updated if new agent or helper added
5. `git push origin main` successful
