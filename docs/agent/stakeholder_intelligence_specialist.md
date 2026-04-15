---
module: agent/stakeholder_intelligence_specialist
purpose: Define StakeholderIntelligenceSpecialist enrichment pipeline and StakeholderValidationAnalyst 4-component weighted scoring rules
dependencies: src/agents/stakeholder_intelligence_specialist.py, src/agents/stakeholder_validation_analyst.py, src/database.py
last_updated: 2026-03-03
---

## Purpose

`StakeholderIntelligenceSpecialist` finds up to 3 decision-relevant contacts per high-scoring opportunity using web search, LinkedIn, and Hunter.io. `StakeholderValidationAnalyst` scores contacts using a 4-component weighted relevance model and removes low-scoring entries before contacts are saved or surfaced in the digest.

---

## Scope

- Covers org website discovery, LinkedIn profile search, email lookup, contact deduplication, and critic scoring.
- Excludes: outreach copy generation — `ExecutiveOutreachStrategist` calls `generate_outreach()` per contact after enrichment. DB persistence is handled by `main.py`, not this agent.
- Only runs for opportunities where `relevance_score >= CONTACT_THRESHOLD` (default: 70).

---

## Key Decisions

- **SerpAPI first, DuckDuckGo fallback:** SerpAPI returns structured results; DDG Instant Answer is free but inconsistent. If `SERPAPI_KEY` is unset, DDG is used silently — no error raised.
- **Hunter.io domain search only:** Does not use Hunter.io's find endpoint (costs 1 credit per call). Domain search returns multiple contacts in one call (1 credit per domain).
- **Deduplication by first name:** If two sources return the same first name, keep the record with more fields populated.
- **Hard cap of 3 contacts:** StakeholderIntelligenceSpecialist stops after 3 valid contacts. StakeholderValidationAnalyst sorts and keeps top 1–3 by `relevance_score` — it never adds contacts.
- **Critic retry cap:** 2 retries maximum. If all contacts still score <30 after 2 retries, accept the current set and log `[WARN] no valid contacts: {org}`.

---

## StakeholderValidationAnalyst Scoring Model

Each contact receives a `relevance_score` (0–100 int) computed as a 4-component weighted sum:

| Component | Weight | Raw Range | Notes |
|-----------|--------|-----------|-------|
| seniority_score | 40% | 0–100 | Title seniority tier |
| domain_score | 35% | 0–100 | Title domain alignment |
| activity_signals_score | 15% | 0–100 | LinkedIn + email presence |
| org_proximity_score | 10% | 0–100 | Context keyword overlap |

`relevance_score = round(min(100, s*0.40 + d*0.35 + a*0.15 + p*0.10))`

**Seniority tiers** (raw 0–100, highest matching tier wins):

| Terms | Raw Score |
|-------|-----------|
| Chief, VP, Vice President, Director | 100 |
| Head, Senior, Lead | 62 |
| Manager | 37 |
| Advisor, Specialist, Coordinator | 12 |
| No match | 0 |

**Domain alignment tiers** (raw 0–100, highest matching tier wins):

| Terms | Raw Score |
|-------|-----------|
| Data, Analytics, AI, Cloud, Machine, Learning, Intelligence | 100 |
| Technology, IT, Digital, Innovation, Transformation, Systems | 75 |
| Procurement, Finance, Operations, Business | 25 |
| No match | 0 |

**Activity signals** (raw 0–100, additive):

| Signal | Raw Points |
|--------|-----------|
| Has email address | +67 |
| Has LinkedIn URL | +33 |
| Max | 100 |

**Org proximity** (raw 0–100):

| Condition | Raw Score |
|-----------|-----------|
| Title keywords appear in exec_summary or suggested_angle | 100 |
| No overlap | 0 |

**Per-contact debug log:**
```
[CONTACT-SCORE] {name} | seniority={n} domain={n} signals={n} proximity={n} final={n}
```

Contacts are sorted descending by `relevance_score`; top 1–3 are kept.

**Retry logic:** If the highest-scoring contact is still <30 AND retry count < 2, re-run `enrich_opportunity()` and re-score.

**DRY_RUN behaviour:** Skip scoring and retries; assign `relevance_score = 80` to all contacts.

---

## Constraints

- `time.sleep(1)` between all external API calls.
- `enrich_opportunity()` must return `{}` on complete failure — never raise.
- Log prefix: `[CONTACTS]` for StakeholderIntelligenceSpecialist, `[CRITIC-CONTACT]` for StakeholderValidationAnalyst, `[CONTACT-SCORE]` for per-contact debug.

---

## Interfaces / Dependencies

**Contact schema:**
```python
{
  "name":            str,
  "title":           str,
  "linkedin_url":    str | None,
  "email":           str | None,
  "source":          str,   # linkedin | hunter | manual
  "relevance_score": int,   # 0–100, assigned by StakeholderValidationAnalyst
}
```

**Enrichment output (per opportunity):**
```python
{
  "website":   str | None,
  "domain":    str | None,
  "contacts":  list[dict],  # max 3, contact schema above
}
```

---

## Risks / Considerations

- **Hunter.io free tier:** 25 domain searches/month. Above this, searches return 402. Implement `has_contacts(domain)` DB check before calling Hunter.io to avoid wasting quota on re-runs.
- **LinkedIn scraping policy:** `site:linkedin.com/in` Google search is used — not the LinkedIn API. This is search-engine indexing, not direct scraping. Do not use Playwright to navigate linkedin.com directly.
- **Contact staleness:** Titles and emails change. Contacts older than 90 days in DB should be flagged for re-enrichment, not silently reused.
