---
module: agent/overview
purpose: Define the agent's business function, pipeline phases, and scheduling contract
dependencies: none
last_updated: 2026-03-09
---

## Purpose

Replace 5–10 hours/week of manual BD research. The agent runs autonomously on GitHub Actions: scrapes procurement portals daily, scores RFPs, discovers contacts, and delivers a digest every Monday morning. Projected impact: $1.2M net new revenue per year from high-quality bids; $250k and 500+ hours saved annually in non-billable effort.

---

## Scope

- Covers full pipeline from scrape to email delivery.
- Excludes: dashboard UI, CRM integration, automated outreach sending.
- Target geography: BC-primary, Alberta-secondary, Federal-tertiary.

---

## Key Decisions

- **Two separate workflows:** Scrape (Mon + Thu 7am PT, plus on-demand via workflow_dispatch) and Monday digest (8am PT) are distinct GitHub Actions jobs. Never combined into one cron.
- **DRY_RUN mode is mandatory:** Every agent must respect `DRY_RUN=true` — skips real API calls, returns fixture data. Used in testing and cost-controlled CI runs.
- **Agent interface contract:** Each stage is a Python class implementing `run(state: dict) -> dict`. No agent writes to DB or sends network requests outside its designated scope.
- **Failure isolation:** Any single agent failure is logged to `state['errors']` and skipped. Pipeline and digest continue regardless.

---

## Constraints

- Total pipeline must complete within GitHub Actions 6-hour job limit.
- Each agent is subject to a 30-second `signal.alarm` timeout.
- DB is SQLite stored as a GitHub Actions artifact — no persistent server.
- Maximum 3 contacts enriched per opportunity.
- Critic retry loops capped at 2 per stage.

---

## Interfaces / Dependencies

Pipeline execution order and state keys:

| # | Agent Class | File | Reads | Writes |
|---|-------------|------|-------|--------|
| 1 | ProcurementIntelligenceSpecialist | `src/agents/procurement_intelligence_specialist.py` | — | `listings` |
| 2 | OpportunityQualificationSpecialist | `src/agents/opportunity_qualification_specialist.py` | `listings` | `filtered` |
| 3 | StrategicScoringAgent | `src/agents/strategic_scoring_agent.py` | `filtered` | `scored` |
| 4 | ScoringAssuranceAnalyst | `src/agents/scoring_assurance_analyst.py` | `scored` | `validated` |
| 5 | StakeholderIntelligenceSpecialist | `src/agents/stakeholder_intelligence_specialist.py` | `validated` | `contacts` |
| 6 | StakeholderRelevanceAgent | `src/agents/stakeholder_relevance_agent.py` | `contacts` | `enriched` |
| 7 | ExecutiveOutreachStrategist | `src/agents/executive_outreach_strategist.py` | `enriched` | `ready` |
| 8 | IntelligenceDeliveryAgent | `src/agents/intelligence_delivery_agent.py` | DB query | email sent |

All keys are top-level on the shared state dict.

**Helper modules (not agents — no `run()` interface):**

| Module | Purpose |
|--------|---------|
| `src/agents/extraction_utils.py` | Multi-step RFP extraction pipeline (`extract_rfp_content`) + structured metadata parser (`parse_rfp_metadata`) used by OpportunityStrategyAnalyst |
| `src/agents/regex_profiles.py` | Portal-specific compiled regex patterns for MERX, CanadaBuys, BCBid, RFPMart |
| `demo.py` | Rich terminal demo runner — forces `DRY_RUN=true`, renders per-agent spinners/completion lines with colour-coded log output, prints a summary table; used for client demos and asciinema recording |
| `scripts/rescore_null_rows.py` | One-shot maintenance tool — resets false-negative SKIP rows (score=0, filter>=60) caused by auth-wall portals and rescores them + rows where the upsert bug lost scoring results (recommendation=NULL, filter>=60); accepts `--dry-run` and `--limit N`; requires live `ANTHROPIC_API_KEY` |
| `capture_bcbid_session.py` | One-shot local helper — launches a headful patchright Chromium window, warms up the BCBid session (bypassing the iV browser_check gate naturally), and saves `bcbid_session.json` to the project root. `scrape_bcbid()` auto-loads this file on subsequent runs. Re-run whenever the session expires (typically days). |

---

## Risks / Considerations

- **Scraper fragility:** Portal HTML changes every 1–3 months. Budget one fix per quarter per source. BCBid (ivCaptcha) and BidsAndTenders/TendersOnTime (login) are highest-risk for breakage.
- **Digest silence:** If the DB artifact expires between runs, Monday digest is empty. `pipeline_runs` table detects this condition.
- **Cost spikes:** 200+ new listings in one day measurably increases Claude API spend. Review `infrastructure/cost.md` for thresholds.
- **CASL compliance:** Contacts are surfaced for manual review only. Automated sending to discovered addresses is prohibited under any configuration.

---

## Experiment Evaluation Framework

**Location:** `evaluation/` and `experiments/` (both at project root, outside `src/`)

**Purpose:** Structured performance evaluation of the pipeline across architectural versions. Runs 3 evaluation phases, computes 15 metrics, stores versioned artefacts, and supports A/B comparison between architectures.

**Key files:**

| File | Purpose |
|------|---------|
| `evaluation/experiment_agent.py` | Main experiment runner — CLI entry point; orchestrates all 3 phases |
| `evaluation/metrics_calculator.py` | Computes all 15 evaluation metrics (heuristic, no anthropic client) |
| `evaluation/test_dataset/bid_01.json … bid_10.json` | Fixed 10-bid evaluation dataset with ground truth labels |
| `evaluation/experiment_log.json` | Global append-only log of all experiment runs |
| `experiments/{version}_{title}/` | Per-experiment artefact folder (metrics.json, outputs/, errors/, notes.md) |
| `experiments/ab_tests/` | A/B comparison experiments; each contains version_a/, version_b/, comparison.json |

**Evaluation phases:**

| Phase | What runs |
|-------|-----------|
| 1 — Unit testing | Individual skill validation: capability extraction, risk detection, opportunity detection, win probability estimation |
| 2 — Scenario testing | Full pipeline on all 10 bids (3× repeat passes for consistency measurement) |
| 3 — Strategic evaluation | 15 metrics: decision_accuracy, relevance_score, reasoning_quality, hallucination_rate, coverage, average_confidence, evidence_grounding, risk_identification_accuracy, confidence_calibration, consistency, differentiation_insight, strategic_depth_score, real_business_value, tokens_used, runtime_seconds |

**Pipeline integration:** Skips ProcurementIntelligenceSpecialist; injects test bids as `state['listings']`; runs `OpportunityQualificationSpecialist → StrategicScoringAgent → ScoringAssuranceAnalyst`.

**Usage:**
```bash
DRY_RUN=true python3 evaluation/experiment_agent.py --version v1.1 --title rag-improvement
DRY_RUN=true python3 evaluation/experiment_agent.py --ab-test competitor-test \
  --version-a v1.2 --title-a no-competitor --version-b v1.3 --title-b with-competitor
```

**Version naming:** `v{major}.{minor}_{short-change-title}` — e.g. `v1.4_reasoning-refinement`

**Constraints:** No `anthropic` client in `evaluation/`. No async/await. DRY_RUN=true compatible.
