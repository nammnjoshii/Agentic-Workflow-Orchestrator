---
module: agent/stakeholder_relevance_agent
purpose: Define StakeholderRelevanceAgent 4-component weighted scoring rules, retry logic, and contact validation contract
dependencies: src/agents/stakeholder_relevance_agent.py, src/agents/stakeholder_intelligence_specialist.py
last_updated: 2026-04-15
---

## Purpose

`StakeholderRelevanceAgent` scores contacts using a 4-component weighted relevance model, sorts them by score, and removes low-scoring entries before contacts are saved or surfaced in the digest.

---

## Scope

- Covers contact scoring, sorting, capping, and retry logic.
- Excludes: contact discovery — `StakeholderIntelligenceSpecialist` populates `state['enriched']` upstream. DB persistence is handled by `main.py`.

---

## Key Decisions

- **4-component weighted model:** Seniority (40%), domain alignment (35%), activity signals (15%), org proximity (10%).
- **Retry up to 2× if all scores <30:** Re-runs `enrich_opportunity()` on upstream agent and re-scores. After 2 retries, accepts current set and logs warning.
- **Hard cap of top 3 contacts:** Sorts descending by `relevance_score`; keeps top 1–3 only.
- **No `anthropic` client:** Scoring is fully deterministic.

---

## Scoring Model

Each contact receives a `relevance_score` (0–100 int) computed as:

`relevance_score = round(min(100, seniority*0.40 + domain*0.35 + signals*0.15 + proximity*0.10))`

| Component | Weight | Top tier |
|-----------|--------|----------|
| Seniority | 40% | Chief/VP/President/Director = 100 |
| Domain | 35% | Data/AI/Cloud/ML = 100 |
| Signals | 15% | LinkedIn + Email = 100 |
| Proximity | 10% | Title overlap with suggested_angle = 100 |

**Seniority tiers:**

| Terms | Raw Score |
|-------|-----------|
| Chief, VP, Vice President, Director | 100 |
| Head, Senior, Lead | 62 |
| Manager | 37 |
| Advisor, Specialist, Coordinator | 12 |
| No match | 0 |

**Domain alignment tiers:**

| Terms | Raw Score |
|-------|-----------|
| Data, Analytics, AI, Cloud, Machine, Learning, Intelligence | 100 |
| Technology, IT, Digital, Innovation, Transformation, Systems | 75 |
| Procurement, Finance, Operations, Business | 25 |
| No match | 0 |

**Activity signals:**

| Signal | Raw Points |
|--------|-----------|
| Has email address | +67 |
| Has LinkedIn URL | +33 |

**Org proximity:**

| Condition | Raw Score |
|-----------|-----------|
| Title keywords appear in exec_summary or suggested_angle | 100 |
| No overlap | 0 |

---

## Constraints

- `DRY_RUN=true` → assign `relevance_score = 80` to all contacts; skip scoring and retries.
- Log prefix: `[CRITIC-CONTACT]` for agent-level events, `[CONTACT-SCORE]` for per-contact debug.
- Per-contact debug log format: `[CONTACT-SCORE] {name} | seniority={n} domain={n} signals={n} proximity={n} final={n}`
- Never raise from `run()` — return state unchanged on complete failure.

---

## Interfaces / Dependencies

**Reads:** `state['enriched']` — contacts enriched by StakeholderIntelligenceSpecialist.
**Writes:** `state['enriched']` — contacts sorted descending, capped at top 3, each gains `relevance_score`.

---

## Risks / Considerations

- **Stop-word pollution:** Raw title words like "of"/"and"/"the" can cause false proximity matches. Filter stop words from both title and context before overlap check.
- **Contact staleness:** Titles and emails change. Contacts older than 90 days in DB should be flagged for re-enrichment.
