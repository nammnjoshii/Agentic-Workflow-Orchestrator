# docs/CLAUDE.md — Sub-Agent Reference

> Concise per-agent rules for Claude Code sessions. Always read root `CLAUDE.md` and `docs/operation/antipatterns.md` first. This file defines each sub-agent's scope, constraints, and interface.

---

## ProcurementIntelligenceSpecialist (`src/agents/procurement_intelligence_specialist.py`)

**Role:** Collect raw RFP listings from 11 procurement portals.

**Reads:** nothing from state
**Writes:** `state['listings']` — `{title, org, deadline, value, url, source, raw_description}`

**Rules:**
- `DRY_RUN=true` → 8 fixture listings (including BCBid), no network calls
- Deduplicate by URL before writing to state
- Each scraper `try/except` — failure logs warning, does not halt `scrape_all()`
- Playwright (sequential, shared Chromium browser): CanadaBuys, BidsAndTenders
- camoufox (Firefox stealth, runs AFTER sync_playwright() closes): MERX, BidNet, BCBid — datacenter IPs (GitHub Actions) are blocked by Chromium bot-detection on these portals; camoufox bypasses it. camoufox has its own event loop and must not run inside an open sync_playwright() context.
- Requests+BS4 (parallel): RFPMart, BidsCanada, CanadaTenders, SaskTenders, AlbertaPurchasing, TorontoBids
- Auth from env at call time: `BIDSCANADA_LOGIN/PASSWORD`, `BIDS_AND_TENDERS_LOGIN/PASSWORD`, `CanadaTenders_LOGIN/PASSWORD`, `BCBid_LOGIN/PASSWORD`
- BCBid: uses camoufox (Firefox stealth) to bypass iV browser-fingerprinting check that blocks Chromium/requests; paginates all pages via JS button clicks; keyword-filtered listing → opportunity detail page → RFx Documents PDFs downloaded and text-extracted via pypdf; browser arg accepted but ignored (camoufox manages its own context)
- CanadaTenders: login + keyword search across `_PROCUREMENT_KEYWORDS` + detail page extraction (org, deadline, summary); falls back to public listing if keyword search empty
- GlobalTenders removed (no org/deadline/description data — zero BD value)
- No `anthropic` client

---

## OpportunityQualificationSpecialist (`src/agents/opportunity_qualification_specialist.py`)

**Role:** pre-filter LLM pre-filter (0–100, drop below `FILTER_THRESHOLD=60`).

**Reads:** `state['listings']`
**Writes:** `state['filtered']`, `state['skipped']`

**Rules:**
- Model: pre-filter LLM only (never scoring LLM — cost)
- `DRY_RUN=true` → score 75, pass all through
- `has_score(url)` cache check first — skip API if already scored
- Max 8 tokens response (single integer)

---

## StrategicScoringAgent (`src/agents/strategic_scoring_agent.py`)

**Role:** Deep RFP scoring (scoring LLM) + deterministic 7-component priority score.

**Reads:** `state['filtered']`
**Writes:** `state['scored']` — 9 scored fields + `opportunity_priority_score`

**Rules:**
- Model: scoring LLM only (never pre-filter LLM)
- `DRY_RUN=true` → return fixture scored data
- JSON fields: `relevance_score` (0–100), `recommendation` (PURSUE|CONSIDER|SKIP), `score_rationale`, `capability_match`, `risks`, `estimated_effort` (S|M|L|XL), `exec_summary`, `suggested_angle`, `decision_log`
- Bands: ≥75=PURSUE, 50–74=CONSIDER, <50=SKIP; disqualifiers override to SKIP
- `opportunity_priority_score` computed deterministically after LLM — never asked of LLM
- Use `CLIENT_PROFILE` verbatim in prompts

---

## ScoringAssuranceAnalyst (`src/agents/scoring_assurance_analyst.py`)

**Role:** Validate scores; rescore via scoring LLM on failure (max 2 retries).

**Reads:** `state['scored']`
**Writes:** `state['validated']`

**Rules:**
- Validates: `relevance_score` int 0–100, recommendation matches band, `capability_match` non-empty if ≥60, `opportunity_priority_score` int 0–100
- On failure: `_rescore()` scoring LLM with failures in prompt, max 2 retries
- `_calibration_check()`: `tests/fixtures/calibration_set.json`, warn if deviation >15
- `anthropic` client allowed (rescoring requires API)
- `DRY_RUN=true` → pass through without validation

---

## StakeholderIntelligenceSpecialist (`src/agents/stakeholder_intelligence_specialist.py`)

**Role:** Discover decision-maker contacts via SerpAPI + Hunter.io.

**Reads:** `state['validated']`
**Writes:** `state['contacts']` — dict keyed by URL; each value is `{website, domain, contacts: [{name, title, linkedin_url, email, source}]}`

**Rules:**
- `DRY_RUN=true` → 2 fixture contacts per opportunity
- Max 3 contacts (Hunter.io credit conservation)
- Lookup order: org website (SerpAPI) → LinkedIn (SerpAPI `site:linkedin.com/in`) → email (Hunter.io)
- `SERPAPI_KEY`, `HUNTER_API_KEY` from env at call time
- No `anthropic` client

---

## StakeholderRelevanceAgent (`src/agents/stakeholder_relevance_agent.py`)

**Role:** Score contacts by relevance; retry enrichment if all scores <30.

**Reads:** `state['enriched']`
**Writes:** `state['enriched']` — contacts sorted desc, capped at top 3, each gains `relevance_score`

| Component | Weight | Top tier |
|-----------|--------|----------|
| Seniority | 40% | Chief/VP/President/Director = 100 |
| Domain | 35% | Data/AI/Cloud/ML = 100 |
| Signals | 15% | LinkedIn + Email = 100 |
| Proximity | 10% | Title overlap with suggested_angle = 100 |

**Rules:**
- `DRY_RUN=true` → `relevance_score=80` fixed
- Retry up to 2× if **all** contacts <30
- No `anthropic` client; log `[CONTACT-SCORE]` per contact

---

## ExecutiveOutreachStrategist (`src/agents/executive_outreach_strategist.py`)

**Role:** Generate 2-sentence personalised email openers via scoring LLM.

**Reads:** `state['enriched']`
**Writes:** `state['ready']` — each contact gains `outreach_opening`

**Rules:**
- Model: scoring LLM; max 200 tokens; fallback to template on failure
- `DRY_RUN=true` → templated string, no API call
- Must reference RFP name + contact role + `suggested_angle`
- **CASL:** copy for manual review only — never automate sending

---

## IntelligenceDeliveryAgent (`src/agents/intelligence_delivery_agent.py`)

**Role:** HTML email assembly + Resend delivery.

**Reads:** DB (`get_opportunities_for_digest()`)
**Writes:** DB `sent_in_digest=1`; `pipeline_runs` log

**Rules:**
- `DRY_RUN=true` → print HTML[:500], do not send, log OK
- All CSS inline — no `<style>` tags
- Sort: `opportunity_priority_score DESC`, `relevance_score DESC`
- PRIORITY badge: ≥80 `#15803d`, ≥60 `#1d4ed8`, ≥40 `#b45309`, <40 `#6b7280`
- Env reads (`RESEND_API_KEY`, `DIGEST_SENDER`, `DIGEST_RECIPIENT`) inside `_send_via_resend()` only
- Mark sent only after Resend 2xx
- No `anthropic`; no `smtplib`

---

## Helpers (no `run()`)

| Module | Role | Import restriction |
|--------|------|--------------------|
| `extraction_utils.py` | 8-step RFP extraction (zero API calls) | Only `strategic_scoring_agent.py` |
| `regex_profiles.py` | Portal-specific compiled regex | Only `extraction_utils.py` |

---

## Adding a New Agent

1. `src/agents/<name>.py` — implement `run(state) -> dict`
2. Add to `OpportunityOrchestrator([...])` in `main.py`
3. Update interface table in `docs/agent/overview.md`
4. Add tests in `tests/test_agents.py`
5. Append entry to `docs/operation/changelog.md`
6. `DRY_RUN=true python3 -m pytest tests/ -v` — all passing
