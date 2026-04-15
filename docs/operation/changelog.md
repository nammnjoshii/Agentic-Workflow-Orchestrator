---
module: operation/changelog
purpose: Record all meaningful changes with date, description, and affected modules
dependencies: none
last_updated: 2026-02-28
---

## Purpose

Dated audit trail of every meaningful system change.

---

### 2026-03-17 — feat: geo-scoped LinkedIn contact discovery

- `find_linkedin_contacts(org_name, location="")` — appends listing region as quoted term to SerpAPI query (e.g. `"British Columbia"`) to filter out non-local contacts
- `find_linkedin_contacts_by_role(org_name, location="")` — same geo-scope applied to role-targeted pass
- `enrich_opportunity(..., location="")` — threads `location` through to both LinkedIn search functions
- `StakeholderIntelligenceSpecialist.run()` — passes `item.get("location", "")` to `enrich_opportunity`
- `StakeholderValidationAnalyst.run()` — retry call also passes `location` so retries are geo-scoped
- Verified with live test run on 10 DB opportunities — BC ministry contacts correctly landing on BC profiles
- Affected: `src/agents/stakeholder_intelligence_specialist.py`, `src/agents/stakeholder_validation_analyst.py`

### 2026-03-16 — fix: BCBid local session capture helper

- Added `capture_bcbid_session.py` — headful patchright Chromium helper that warms up BCBid's home + browse pages, passes the iV browser_check gate naturally in visible-browser mode, and saves `bcbid_session.json` to the project root
- `scrape_bcbid()` already auto-loads `bcbid_session.json` (lines 1132–1137 of `procurement_intelligence_specialist.py`) — no scraper changes needed
- Fixes: headless patchright blocked by BCBid's IntelligenceView gate locally (browser_check redirect never clears after 60s)
- Updated `docs/agent/overview.md` helpers table

---

### 2026-03-11 — feat: BCBid alternative scraper test scripts (nodriver, proxy, Bright Data)

- Added `scripts/test_nodriver_bcbid.py` — tests BCBid using nodriver (direct CDP, no Playwright wrapper)
- Added `scripts/test_proxy_bcbid.py` — tests BCBid using patchright + residential proxy (BCBID_PROXY_URL secret)
- Added `scripts/test_brightdata_bcbid.py` — tests BCBid using Bright Data Scraping Browser via CDP WebSocket (BRIGHT_DATA_WS_CDP secret)
- Added `.github/workflows/test_bcbid_alternatives.yml` — manual `workflow_dispatch` only; 3 parallel jobs; no concurrency group conflict
- Each script runs 2 keywords ("data", "analytics") and reports: home URL, browse URL, browser_check pass/fail, iV overlay pass/fail, listing count
- No changes to src/, tests/, main.py, requirements.txt, or existing workflows
- Diagnostic matrix: if nodriver passes → Playwright wrapper leaks signals; if proxy passes → IP reputation blocker; if Bright Data passes → their managed fingerprint defeats iV

### 2026-03-11 — fix: MERX/BidNet geo scoring — store `location` field in listing dict

- `scrape_merx()` and `scrape_bidnet()` now include `"location"` in each listing dict (was extracted but discarded)
- `_geo_affinity_score()` now includes `listing.get("location")` in text search alongside title/org/raw_description
- Effect: MERX/BidNet listings with "British Columbia" in the location column now score geo=100 (was 30 — unknown) and surface correctly in digest
- 2 new tests added (`test_bc_location_field_is_100`, `test_bidnet_bc_location_field_is_100`); 197 tests passing

### 2026-03-11 — v4.1: Replace camoufox with patchright for BCBid scraper (Chromium CDP patches)

- **Problem:** camoufox (Firefox stealth) failed BCBid's `/en/bas/browser_check` JS gate on every run — browser_check never auto-redirected within 60s, blocking all 22 keyword searches.
- **Fix:** Replaced `camoufox.sync_api.Camoufox` with `patchright.sync_api.sync_playwright`. patchright patches Chromium CDP signals (`navigator.webdriver`, automation flags) that BCBid's gate uses to detect headless automation. Added explicit viewport (1366x768) and realistic user-agent. Same sync Playwright API; no scraping logic changed.
- **Workflow:** `bcbid_scrape.yml` — replaced camoufox cache/fetch steps with patchright cache + `python -m patchright install chromium`.
- **Dependencies:** `patchright` added to `requirements.txt`; `camoufox` kept for MERX + BidNet.
- **Experiment:** `experiments/v4.1_patchright-bcbid/metrics.json`
- **Files changed:** `src/agents/procurement_intelligence_specialist.py`, `requirements.txt`, `.github/workflows/bcbid_scrape.yml`
- **Tests:** 195 passing

### 2026-03-11 — BCBid browser_check: session warm-up + mouse interaction to trigger redirect

- **Problem:** BCBid's `/en/bas/browser_check` JS gate never auto-redirected within 60s. The check appears to require pre-existing session cookies or a real user interaction event before it issues the redirect cookie.
- **Fix 1 — Session warm-up:** Navigate to BCBid home page (`BASE`) once at the start of `scrape_bcbid()` before the search loop. Establishes session/fingerprint cookies that may allow BROWSE_URL navigations to skip browser_check entirely.
- **Fix 2 — Mouse interaction:** New `_handle_browser_check_page(page)` helper. When browser_check is detected, simulate `mouse.move(760, 400)` + `mouse.click(760, 400)`, then `wait_for_url` up to 60s. Some browser-check implementations gate the redirect cookie on receiving a real interaction event.
- **Refactor:** Extracted browser_check handling into `_handle_browser_check_page()`, called from both the warm-up path and the per-keyword search path.
- **Files changed:** `src/agents/procurement_intelligence_specialist.py`
- **Tests:** 195 passing

### 2026-03-11 — Handle BCBid browser_check redirect gate

- **Problem:** Second `bcbid_scrape` run (same day) still returned 0 results. New failure mode: BCBid routed every request through `/en/bas/browser_check` (a JS browser-compatibility gate separate from the iV challenge overlay) before reaching the browse page. `_wait_for_iv_challenge()` was called while the page was still on `browser_check`, so all 8 search-box probes waited up to 8s each (~64s total) for elements that don't exist on that page, then raised `RuntimeError`. Both retry attempts followed the same path — 0 searches succeeded.
- **Fix:** Added `browser_check` gate detection in the keyword search loop. After `page.goto(BROWSE_URL)` and the networkidle wait, if `page.url` contains `"browser_check"`, call `page.wait_for_url(lambda u: "browser_check" not in u, timeout=60000)` and a follow-up networkidle wait. This allows the BCBid JS to complete its fingerprint check and redirect the browser back to BROWSE_URL before we attempt any DOM interaction. Logs `INFO` on entry, `INFO` on successful exit, `WARNING` if stuck after 60s.
- **Files changed:** `src/agents/procurement_intelligence_specialist.py`
- **Tests:** 195 passing

### 2026-03-11 — Harden BCBid search box detection against iV challenge DOM changes

- **Problem:** All 22 BCBid keyword searches failed on the March 11 `bcbid_scrape` workflow run with `Page.fill: Timeout 30000ms exceeded`. Root cause: cascading failure — (1) `_wait_for_iv_challenge()` used a single hardcoded overlay selector (`div.iv-block-overlay`); if BCBid renamed that class the function silently returned "all clear" via bare `except: pass`, leaving the page still on the challenge screen; (2) `page.fill("input#body_x_txtQuery", ...)` then timed out because the challenge page has no search box; (3) no retry — the failure repeated identically for all 22 keywords.
- **Fix:** Rewrote `_wait_for_iv_challenge()` with a 3-layer detection strategy: (1) try 5 overlay CSS selector variants (5s each, silent on miss); (2) quick page-content marker check to shorten wait for fast loads; (3) probe 8 search-box selector fallbacks — **returns the working selector string** on success or **raises RuntimeError** on failure so callers can react. Added `_log_bcbid_page_state()` helper that emits URL, page title, and body[:200] on failure for instant diagnosis from GitHub Actions logs. Rewrote the keyword search loop to use `for attempt in range(2)` retry with 3s back-off, using the selector returned by `_wait_for_iv_challenge` for the `fill()` call instead of a hardcoded ID.
- **Files changed:** `src/agents/procurement_intelligence_specialist.py`
- **Tests:** 195 passing

### 2026-03-10 — Switch MERX and BidNet scrapers to camoufox

- **Problem:** Both scrapers returned 0 listings on GitHub Actions runners (datacenter IPs) because Chromium is detected and served a bot-detection/empty page. Locally they work fine.
- **Fix:** Rewrote `scrape_merx()` and `scrape_bidnet()` to use `camoufox` (Firefox + anti-fingerprint), matching the BCBid pattern already proven to bypass bot-detection.
- **Architecture change:** Both scrapers removed from the shared `sync_playwright()` Chromium block in `scrape_all()`. They now run sequentially in the camoufox section after `sync_playwright()` closes (camoufox manages its own event loop — running it inside an open sync_playwright context causes a crash).
- **Files changed:** `src/agents/procurement_intelligence_specialist.py`
- **Tests:** 195 passing

### 2026-03-10 — Removed TendersOnTime scraper

**Change:** Removed TendersOnTime portal from the scraping pipeline.

**Affected files:**
- `src/agents/procurement_intelligence_specialist.py` — deleted `scrape_tendersontime()` function; removed from Playwright scrapers list; updated docstring (12→11 scrapers)
- `.github/workflows/daily_scrape.yml` — removed `TendersOnTime_LOGIN/PASSWORD` env vars
- `.github/workflows/reset_and_scrape.yml` — removed `TendersOnTime_LOGIN/PASSWORD` env vars
- `.env.example` — removed TendersOnTime credential lines
- `README.md` — updated scraper count 12→11; removed credential example
- `docs/agent/procurement_intelligence_specialist.md` — removed table row + source enum entry
- `docs/CLAUDE.md` — updated portal count and auth list

---

### 2026-03-10 — Workflow fixes: 0-opportunity digest root causes + Node.js 24 opt-in

**Problem:** Weekly digest sent 0 opportunities after manual workflow sequence (Reset → Daily → BCBid → Digest).

**Root causes identified and fixed:**

1. **`reset_and_scrape.yml` missing camoufox** — workflow installed Chromium but BCBid requires camoufox; BCBid scraper silently failed. Fixed: added `actions/cache@v4` + `python -m camoufox fetch` steps before the scrape run.

2. **`daily_scrape.yml` redundant artifact download** — `run_daily_scrape()` calls `clear_all_data()` at startup, making the preceding artifact download pointless. Fixed: removed the `Find latest DB artifact run` (github-script) and `actions/download-artifact@v4` steps.

3. **No observability after scrape** — neither scrape workflow logged how many opportunities were saved or what recommendations they received. Fixed: added `Inspect DB state` step to `daily_scrape.yml` and `bcbid_scrape.yml` that prints opportunity counts by recommendation and digest-ready unsent count.

4. **Node.js 20 deprecation warnings** — all 4 workflows emitted deprecation notices. Fixed: added `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` env to all 4 workflow jobs.

**Files changed:** `.github/workflows/reset_and_scrape.yml`, `daily_scrape.yml`, `bcbid_scrape.yml`, `weekly_digest.yml`

**Note:** `send_weekly_digest()` already had a correct empty-digest notification (sends styled HTML email when 0 opportunities found). No change needed there.

**Tests:** 195 passing (`DRY_RUN=true python3 -m pytest tests/ -v`) A Claude Code session that does not append to this file has not completed the V7 verification step. The most recent entry is always at the top.

---

### 2026-03-10 — Token usage + timing observability across all pipeline agents

**Changes:** `opportunity_qualification_specialist.py` (token accumulator via `_usage_collector`), `opportunity_strategy_analyst.py` (`_score_listing` returns `(scored,usage)` tuple + BCBid skips URL re-fetch), `scoring_assurance_analyst.py` (`_rescore` returns `(rescored,usage)` tuple), `executive_outreach_strategist.py` (`generate_outreach` accepts `_usage_collector`), `opportunity_orchestrator.py` (`_log_agent` passes tokens to `log_pipeline_run`, state init for `token_usage`), `main.py` (`_print_run_summary` per-agent table with secs/tokens/cost), `procurement_intelligence_specialist.py` (`_read_detail_page_content` navigates once with `wait_until="networkidle"`, polls without re-navigating). **Tests:** 195 passing

---

## Scope

- Covers all code changes, threshold adjustments, prompt edits, schema changes, and dependency updates.
- Excludes: typo fixes in documentation, whitespace-only changes.
- One row per logical change. Multiple files changed for one feature = one row.

---

## 2026-03-10 — Email digest: recommendation badge + score label redesign

**Files:** `src/agents/opportunity_intelligence_advisor.py`, `tests/test_scoring_priority.py`
**Change:** Left circular number badge replaced with pill-shaped recommendation label ("Pursue" / "Consider") in client brand colors (#172C51 / #2D73C4). Right badge label changed from "PRIORITY xx" to "Score xx". Test updated to match new label text.

---

## 2026-03-10 — BCBid iV challenge fixes + dedicated weekly workflow

**Files:** `src/agents/procurement_intelligence_specialist.py`, `src/database.py`, `main.py`, `.github/workflows/daily_scrape.yml`, `.github/workflows/bcbid_scrape.yml`, `tests/test_database.py`, `tests/test_pipeline.py`

- **Fix: detail page iV race condition** — replaced 4-line `goto/wait/read` pattern with `_read_detail_page_content()` helper that uses content-based detection (`"iv-block-overlay"` / `"browser-check"` in HTML) and retries up to 3× with 8s wait; previous approach used `wait_for_selector(state="hidden")` which returned immediately when the overlay hadn't appeared yet, causing browser-check HTML to be sent to scoring agents (every opportunity scored 28/SKIP)
- **Fix: pagination iV race condition** — `next_btn.click()` (ElementHandle) replaced with `_wait_for_iv_challenge` + `page.locator(...).evaluate("el => el.click()")` (JS click bypasses pointer-event interception by overlay)
- **Fix: search submission stale handle** — `page.locator('button[type=submit]').first.click()` replaced with `page.keyboard.press("Enter")` — no element reference, immune to DOM mutation mid-click
- **BCBid workflow split** — `BCBidOnlyProcurementSpecialist` subclass added; `scrape_all(skip_bcbid=False)` param added; `SKIP_BCBID=true` env var gates BCBid in daily scrape; `run_bcbid_scrape()` added to `main.py`; `bcbid_scrape.yml` workflow (cron Tue 7 AM PT, camoufox cache, artifact pass-through)
- **`clear_source_data(source)`** added to `src/database.py` — deletes contacts + opportunities for one portal without touching others; FK-safe (contacts deleted first)
- 195 tests passing; 4 new tests (`test_clear_source_data_*`, `TestRunBcbidScrape`)

## 2026-03-10 — BCBid scraper: expanded search terms, opportunity type filter, Opportunity Details tab email

**Files:** `src/agents/procurement_intelligence_specialist.py`

- Expanded `SEARCH_TERMS` from 10 → 22 terms: added "machine learning", "artificial intelligence", "cloud", "Azure", "data warehouse", "ETL", "geospatial", "GIS", "database", "managed services", "Microsoft", "software" — covers full client capability profile
- Added `_SKIP_OPP_TYPES` set (Timber Auction, Invitation to Tender, ITT Simplified, MOT ITT, Notice of Sale) — construction/goods types now skipped at detail-page extraction, not scored
- Opportunity Type now extracted via regex from detail page and prepended to `raw_description` for downstream scoring context
- Commodity Codes extracted from detail page (more complete than listing-table column) and appended to `raw_description`
- Added fallback: if email not found on Overview tab, navigate to "Opportunity Details" left-nav tab (Official Contact Information section, per supplier guide p.32) before giving up
- Two new output fields: `opportunity_type`, `commodity_codes` (for scoring agents and future filtering)
- Improved email regex: added `.bc.ca`, `viha.ca`, `vch.ca` TLD variants
- 195 tests passing (no schema/test changes required)

**Why:** Supplier guide PDF + BC Bid Appendix - Opportunity Type Groupings identified 12 missing client-relevant keywords and confirmed that ITT/Timber Auction listings (dominant in BCBid's non-IT inventory) polluted the scoring queue. The Opportunity Details tab navigation ensures Official Contact email is captured even when not rendered on the Overview page.

---

## 2026-03-10 — BCBid split into dedicated weekly workflow

**Files:** `.github/workflows/bcbid_scrape.yml` (new), `.github/workflows/daily_scrape.yml`,
`main.py`, `src/database.py`, `src/agents/procurement_intelligence_specialist.py`,
`tests/test_database.py`, `tests/test_pipeline.py`

- New `bcbid_scrape.yml` — weekly Tuesday 7 AM PT (`0 15 * * 2`); `concurrency: group: pipeline`; caches camoufox binary via `actions/cache@v4`; calls `python main.py bcbid`
- `clear_source_data(source)` added to `database.py` — deletes contacts + opportunities for one portal without touching others; parameterised queries only
- `scrape_all(skip_bcbid=False)` — added `skip_bcbid` parameter; `ProcurementIntelligenceSpecialist.run()` reads `SKIP_BCBID` env var to guard camoufox call
- `daily_scrape.yml` — added `SKIP_BCBID: 'true'`; camoufox 713 MB binary never downloaded in Mon/Thu main pipeline
- `BCBidOnlyProcurementSpecialist` — new class in `procurement_intelligence_specialist.py`; calls `scrape_bcbid()` directly; used by `run_bcbid_scrape()` in `main.py`
- `run_bcbid_scrape()` — new entry point in `main.py`; clears BCBid source data → runs full 7-agent pipeline → persists; callable via `python main.py bcbid`
- 3 new `clear_source_data` tests in `test_database.py`; 1 new `TestRunBcbidScrape` in `test_pipeline.py`; 195 tests passing

**Why:** BCBid uses camoufox (713 MB Firefox binary) downloaded on every Mon/Thu run. Isolated to its own weekly Tuesday schedule with a persistent binary cache. BCBid reliability issues no longer block or delay the main pipeline.

---

## 2026-03-10 — Contact relevance pipeline fixes + fresh-run reset

**Files:** `src/database.py`, `main.py`, `.github/workflows/daily_scrape.yml`, `tests/test_agents.py`

- `contacts` table: added `relevance_score INTEGER` column to schema + migration
- `save_contacts()`: now persists `relevance_score` (8-column INSERT)
- `get_contacts_for_opportunity()`: added `ORDER BY relevance_score DESC`
- Added `clear_all_data()` — deletes all `contacts` and `opportunities` rows; `pipeline_runs` kept
- `run_daily_scrape()` calls `clear_all_data()` after `init_db()` — every run starts from scratch
- `daily_scrape.yml`: added `APOLLO_API_KEY` secret — Apollo source now active in production
- `tests/test_agents.py`: updated digest title assertion (191 tests passing)

**Why:** `relevance_score` computed but never saved — contacts appeared in random insertion order. Re-scrapes accumulated duplicate rows. Apollo was wired in v2 but secret was missing from workflow.

---

## Key Decisions

- **Most recent entry at the top.** Reverse chronological order. Do not re-sort.
- **Format is fixed:** `| YYYY-MM-DD | Description | Affected module(s) |`
- **No entries are deleted.** Changelog is append-only. If a change is reverted, add a new row describing the revert.
- **V7 of the UTD loop requires this file to be updated.** A task without a changelog entry is not complete.

---

## Constraints

- Date format: `YYYY-MM-DD` only — no relative dates, no "today."
- Description: one sentence, past tense, specific. Not "updated scorer" — write "Raised document truncation cap from 3000 to 4000 tokens in ScoringAgent."
- Affected module: file path or module name from the folder map in `README.md`.

---

## Interfaces / Dependencies

None. This file is standalone.

---

## Risks / Considerations

- **Merge conflicts:** If two developers edit changelog simultaneously, the top row will conflict. Resolve by keeping both rows, most recent first.
- **Missing entries:** A gap in the changelog between two known working states makes debugging regressions significantly harder. Enforce at code review.

---

## Log

| 2026-03-10 | v3 weight tuning: contact relevance proximity raised 10→20%, seniority lowered 30→25%, domain lowered 25→20% (reduces title-parsing dominance, rewards bid-specific role fit); opportunity priority score simplified to 6 components — removed rfp_type_score (captured by Claude relevance) and description_richness_score (not a business signal), raised contract value 5→10% and risk profile 5→10%; all 191 tests pass | `src/agents/stakeholder_validation_analyst.py`, `src/agents/opportunity_strategy_analyst.py` |

| Date | Change | Module(s) |
|------|--------|-----------|
| 2026-03-10 | Added scrape_leadership_page() and find_apollo_contacts() to StakeholderIntelligenceSpecialist — website scraping tries 11 common paths using BeautifulSoup (source="website", _org_affiliation_score=90); Apollo.io People API integration (APOLLO_API_KEY env var, source="apollo", returns LinkedIn+title, no email from basic search); Clearbit not integrated (deprecated post-HubSpot acquisition); DRY_RUN fixture updated with source="website" contact | `src/agents/stakeholder_intelligence_specialist.py` |
| 2026-03-10 | Added _org_affiliation_score() 5th component to StakeholderValidationAnalyst (email domain match=100, website=90, hunter/apollo=75, linkedin=50, unknown=50 neutral); weights updated to seniority/domain/affiliation/signals/proximity=30/25/25/10/10 (research-grounded: government CIO formal authority, ABM fit-first principle); domain-match email bonus removed from _activity_signals_score (moved to affiliation); expanded _SENIORITY_TIERS (minister→tier-1, enterprise+architect→tier-2) and _DOMAIN_TIERS (tier-1: +engineering/science/governance/platform/decision; tier-2: +strategy/services/performance/evaluation/policy/architecture/architect/information; tier-3: +financial) to cover Enterprise Architect, Deputy Minister, Director Decision Science, Head of Data Platform, CIO, etc.; _score_contact returns 6-tuple; 191 tests pass | `src/agents/stakeholder_validation_analyst.py`, `tests/test_contact_relevance.py` |
| 2026-03-10 | Finalized compute_priority_score weights (v2 final): relevance_score 30→35%, rfp_type_score 10→5%, geographic_affinity_score 10→15% (BC/WA/OR/CA primary markets elevated), description_richness_score 10→5%; capability_quality_score stays at 20%, time_left at 10%, value and risk at 5%; 178 tests pass | `src/agents/opportunity_strategy_analyst.py` |
| 2026-03-10 | Rebalanced compute_priority_score weights: estimated_contract_value 15→5% (contract value frequently absent/unspecified in RFPs), capability_quality_score 15→20% (strongest signal of actual technical fit), description_richness_score 5→10% (more metadata = higher scoring confidence); 178 tests pass | `src/agents/opportunity_strategy_analyst.py` |
| 2026-03-10 | v2: replaced global 30s signal.alarm with per-agent TIMEOUT_SECONDS class attribute — ProcurementIntelligenceSpecialist defaults to SCRAPER_TIMEOUT_SECONDS env var (1800s/30min), StakeholderIntelligenceSpecialist defaults to CONTACT_TIMEOUT_SECONDS env var (600s/10min); added per-portal heartbeat logging in scrape_all() and per-org progress logging in StakeholderIntelligenceSpecialist so stuck agents are visible in CI logs; raised _MAX_CONTACTS from 3 to 5; added find_linkedin_contacts_by_role() for a role-targeted second SerpAPI pass (Director/VP/Chief/Manager + data); added email-based contact deduplication in merge_contacts(); all requests.get timeouts raised from 15s to 30s; added _geo_affinity_score() to opportunity_strategy_analyst — BCBid source or BC keyword = 100, WA/OR/CA keyword = 100, other Canada/US = 50, unknown = 30; updated compute_priority_score weights to include 10% geographic_affinity_score component (relevance 35→30%, value 20→15%); added TestGeoAffinityScore with 11 tests | `src/opportunity_orchestrator.py`, `src/agents/procurement_intelligence_specialist.py`, `src/agents/stakeholder_intelligence_specialist.py`, `src/agents/opportunity_strategy_analyst.py`, `tests/test_scoring_priority.py` |
| 2026-03-10 | Scoped digest footer stats to period since last sent digest: get_scrape_stats() determines cutoff from most recent DIGEST pipeline_runs row with delivery_status=sent (epoch if DB was reset or no prior digest), then sums ProcurementIntelligenceSpecialist/OpportunityQualificationSpecialist listings_out and counts opportunities by recommendation since cutoff — footer now shows period-accurate scraped/filtered/pursue/consider/skip instead of all-time totals | `src/database.py` |
| 2026-03-10 | Fixed contact enrichment threshold: replaced relevance_score >= 70 gate in StakeholderIntelligenceSpecialist with recommendation IN (PURSUE, CONSIDER) so all digest-bound opportunities receive contact enrichment regardless of score; added get_scrape_stats() to database.py querying pipeline_runs and opportunities tables; updated _build_stats() in OpportunityIntelligenceAdvisor to fall back to DB-sourced counts when state is empty (digest job), so the email footer shows real scraped/filtered/pursue/consider/skip totals instead of zeros | `src/agents/stakeholder_intelligence_specialist.py`, `src/database.py`, `src/agents/opportunity_intelligence_advisor.py` |
| 2026-03-10 | Added experiment evaluation framework: evaluation/experiment_agent.py (3-phase evaluation runner with CLI), evaluation/metrics_calculator.py (15 heuristic metrics, no API calls), evaluation/test_dataset/ (10-bid labeled dataset with ground truth), evaluation/experiment_log.json (global append-only run log), experiments/v1.0_base-architecture/ (pre-populated baseline artefacts), experiments/ab_tests/ scaffold, A/B comparison.json generator; updated docs/agent/overview.md with Experiment Evaluation Framework section | `evaluation/experiment_agent.py`, `evaluation/metrics_calculator.py`, `evaluation/test_dataset/`, `evaluation/experiment_log.json`, `experiments/`, `docs/agent/overview.md` |
| 2026-03-09 | Fixed scoring calibration: (1) wrapped _fetch_rfp_text() in try/except and added raw_description fallback in _score_listing() — when extracted content < 150 words (auth-wall portals return login-page HTML with near-zero useful text), prepend Title/Org/raw_description so scoring LLM scores from the scraped summary rather than an empty page, preventing all-zero false-negative SKIP results; (2) added scripts/rescore_null_rows.py to reset 17 BidsCanada false-negative rows (score=0/SKIP/filter>=60, all caused by auth walls) and rescore them + the 19 lost-score rows (recommendation=NULL/filter>=60, lost due to prior upsert bug) using the fixed fallback; 167 tests pass | `src/agents/opportunity_strategy_analyst.py`, `scripts/rescore_null_rows.py` |
| 2026-03-09 | Wired 8 missing scraper credential env vars into daily_scrape.yml run step: BIDS_AND_TENDERS_LOGIN/PASSWORD, BIDSCANADA_LOGIN/PASSWORD, TendersOnTime_LOGIN/PASSWORD, CanadaTenders_LOGIN/PASSWORD — secrets existed in GitHub repository but were absent from the workflow env block, causing all 4 authenticated portals to read empty strings and log 0 listings on every CI run | `.github/workflows/daily_scrape.yml` |
| 2026-03-09 | Fixed critical upsert bug in save_opportunity(): function used INSERT OR IGNORE which silently skipped writing scored fields (recommendation, relevance_score, opportunity_priority_score, etc.) whenever save_filter_result() had already inserted the URL with recommendation=NULL; changed to INSERT OR IGNORE followed by unconditional UPDATE of all scored fields for the URL — this guarantees recommendation is always persisted and the digest query (WHERE recommendation IN ('PURSUE', 'CONSIDER')) returns eligible rows; root cause of empty digest confirmed by DB inspection (all 473 rows had recommendation=NULL); 167 tests pass | `src/database.py` |
| 2026-03-09 | Fixed empty digest root causes: (1) moved scrape_bcbid() to run independently after sync_playwright() block closes — camoufox has its own asyncio event loop which conflicts with sync_playwright context, causing "Playwright Sync API inside asyncio loop" crash and 0 BCBid listings; (2) raised AGENT_TIMEOUT_SECONDS 30→120 in both workflow env blocks — ProcurementIntelligenceSpecialist legitimately takes 35s+ (Playwright 10s + CanadaTenders 17s sequential), 30s timeout zeroed state["listings"] and left DB empty for the digest; 167 tests pass | `src/agents/procurement_intelligence_specialist.py`, `.github/workflows/daily_scrape.yml`, `.github/workflows/weekly_digest.yml`, `docs/CLAUDE.md` |
| 2026-03-09 | End-to-end pipeline audit fixed 4 bugs: (1) wrong import `scoring_agent` → `opportunity_strategy_analyst` in ScoringAssuranceAnalyst rescore path (latent ModuleNotFoundError in production rescore); (2) `advisor._send_via_resend()` AttributeError in production digest send — added instance method wrapper on OpportunityIntelligenceAdvisor; (3) `_AGENT_IO` output key for StakeholderIntelligenceSpecialist corrected from `"enriched"` to `"contacts"` for accurate pipeline_runs listings_out; (4) ExecutiveOutreachStrategist model corrected from pre-filter LLM to scoring LLM per spec; updated README test count (120+ → 167) and scraper list (GlobalTenders → BCBid); fixed docs/CLAUDE.md StakeholderIntelligenceSpecialist writes key; 167 tests pass | `src/agents/scoring_assurance_analyst.py`, `src/agents/opportunity_intelligence_advisor.py`, `src/opportunity_orchestrator.py`, `src/agents/executive_outreach_strategist.py`, `docs/CLAUDE.md`, `README.md` |
| 2026-03-09 | Added permissions: actions: read + contents: read to both workflow jobs; default GITHUB_TOKEN lacked actions scope causing github-script listArtifactsForRepo to return 403 Resource not accessible by integration | `.github/workflows/daily_scrape.yml`, `.github/workflows/weekly_digest.yml` |
| 2026-03-09 | Fixed cross-run DB persistence: replaced bare actions/download-artifact@v4 (defaults to current run only — never finds previous artifact) with github-script step that queries the API for the most recent non-expired artifact run-id and passes it to download-artifact@v4 with GITHUB_TOKEN; added overwrite: true and if-no-files-found: warn to upload step; increased retention-days from 7 to 90 to prevent expiration gaps; applied to both daily_scrape.yml and weekly_digest.yml | `.github/workflows/daily_scrape.yml`, `.github/workflows/weekly_digest.yml` |
| 2026-03-09 | Expanded _PRIMARY_CAPABILITY_KEYWORDS round 3 (~170 to ~215 terms, user-provided RFP keyword list): added data fundamentals (data analytics, data warehouse, data science, data modeling, information management, data modernization, cloud data platform, enterprise data platform, data lifecycle); cloud expansions (amazon web services, google dataflow, hybrid cloud, cloud security, cloud-first, logic apps, secure data sharing); ML/AI expansions (forecasting, model governance, classification models, regression models, time series); security/gov (phi, cybersecurity, audit log, data classification, security assessment); gov program language (shared services, digital acceleration, im/it, enterprise architecture); project descriptors (center of excellence, analytics modernization, ai adoption, data-driven, enterprise data program); role signals (data engineer, data architect, data scientist, ml engineer, bi developer, analytics consultant, database administrator); 167 tests pass | `src/agents/opportunity_strategy_analyst.py` |
| 2026-03-09 | Expanded _PRIMARY_CAPABILITY_KEYWORDS round 2 (~120 to ~170 terms, 8.5/10 → 9.5/10): added NoSQL/modern databases (mongodb, redis, elasticsearch, opensearch, dynamodb, cassandra, cosmosdb, neo4j); legacy ETL tools (talend, informatica, ssis, matillion, airbyte, boomi, mulesoft, pentaho); cloud ML platforms (sagemaker, azure machine learning, vertex ai, kubeflow); data catalog/governance platforms (collibra, alation, microsoft purview, datahub, apache atlas); query engines (hive, trino, presto, athena, aws glue, aws emr, databricks sql); monitoring tools (grafana, prometheus, datadog, splunk, elk stack, new relic, dynatrace); privacy/regulatory (gdpr, pipeda, hipaa, fedramp, privacy, data residency, privacy by design); identity/auth (active directory, okta, sso, saml, ldap, oauth, zero trust); analytics domain patterns (predictive analytics, geospatial, gis, self-service analytics, data platform, medallion architecture, data products, data contracts, event-driven); integration middleware (mulesoft, api gateway, service mesh, interoperability); data engineering frameworks (dask, polars, pandas, numpy); cloud services (aws lambda, azure functions, google cloud run); 2 new tests; 167 tests pass | `src/agents/opportunity_strategy_analyst.py`, `tests/test_scoring_priority.py` |
| 2026-03-09 | Expanded _PRIMARY_CAPABILITY_KEYWORDS from ~65 to ~120 terms (rated 6.5/10 → 10/10 holistic coverage): added Data Processing/ELT sub-domain (spark sql, dag, orchestration, elt, semantic modeling, data transformation); streaming platforms (pubsub, eventhub, confluent, apache flink, apache beam); ML additions (supervised/unsupervised learning, rag, retrieval augmented, batch/streaming inference, generative ai, deep learning); deployment tools (github actions, azure devops, mlops, dataops); monitoring specifics (metrics, logs, tracing); security additions (secret manager, encryption at rest/in transit, data masking, tokenization); cloud infra (landing zone, vpc, vnet, security scanning, cloud migration, modernization); data management category (data mesh, data fabric, data lake, data integration, data migration, master data, mdm, data catalog, data lineage, open data, data sharing, data architecture, data governance, data strategy); platform tools (azure synapse, azure data factory, microsoft fabric, dbt cloud, great expectations, prefect, dagster, databricks unity catalog); secondary/strategic (digital transformation, public sector, indigenous data, data sovereignty, real-time, microservices, serverless); 2 new tests; 165 tests pass | `src/agents/opportunity_strategy_analyst.py`, `tests/test_scoring_priority.py` |
| 2026-03-09 | Pushed scoring to ~9.5/10 (opportunity) and ~9/10 (stakeholder): (1) replaced _capability_count_score with _capability_quality_score — checks matched capabilities against PRIMARY_CAPABILITY_KEYWORDS set extracted from CLIENT_PROFILE (3+ primary=100, 2=85, 1=60, generic-only=30, none=0); (2) added _HARD_RISK_PATTERNS to _risk_profile_score — risks mentioning disqualifier patterns (construction, medical device, legal, etc.) trigger max penalty regardless of count; (3) added temperature=0 to messages.create() in OpportunityStrategyAnalyst to eliminate LLM non-determinism; (4) updated _activity_signals_score to validate LinkedIn /in/ URLs (company pages score 0) and add org-domain email match boost (matching domain=100pts vs standard 67pts); (5) pass org_domain through _score_contact and StakeholderValidationAnalyst.run(); (6) lowered calibration keyword threshold from >=2 to >=1 for better drift detection coverage; 163 tests pass | `src/agents/opportunity_strategy_analyst.py`, `src/agents/stakeholder_validation_analyst.py`, `src/agents/scoring_assurance_analyst.py`, `tests/test_scoring_priority.py`, `tests/test_contact_relevance.py` |
| 2026-03-09 | Improved opportunity + stakeholder scoring: (1) fixed stop-word bug in _org_proximity_score — raw title words including "of"/"and"/"the" were matching every exec_summary causing proximity to fire as 100 for nearly all contacts; added _STOP_WORDS set filtered from both title and context; (2) replaced binary proximity (0/100) with graded scoring (0 overlaps→0, 1→40, 2→70, 3+→100); (3) replaced circular _strategic_fit_score (5%) with independent _description_richness_score — old component derived from recommendation which derived from relevance_score making relevance effectively control ~40% of priority; new component scores metadata completeness (title+org+value+deadline+description); (4) fixed _rescore to send full structured context (value, deadline, capability_match, risks, score_rationale, description[:1000]) instead of raw description[:500]; 6 new tests added; 156 tests pass | `src/agents/stakeholder_validation_analyst.py`, `src/agents/opportunity_strategy_analyst.py`, `src/agents/scoring_assurance_analyst.py`, `tests/test_contact_relevance.py`, `tests/test_scoring_priority.py` |
| 2026-03-08 | Added demo.py — rich terminal demo runner that forces DRY_RUN=true, subclasses OpportunityOrchestrator with per-agent spinner and completion lines (colour-coded by agent prefix), installs a custom logging handler routing all [PREFIX] log messages to rich console, and prints a summary results table; added rich>=13.0.0 to requirements.txt; updated docs/agent/overview.md helper modules table | `demo.py`, `requirements.txt`, `docs/agent/overview.md` |
| 2026-03-08 | Replaced Playwright-based scrape_bcbid() with camoufox (Firefox stealth) implementation to bypass BCBid's iV (IntelligenceView) browser-fingerprinting challenge that blocked all Chromium/requests approaches; new implementation paginates all result pages via JS button clicks, filters by keyword regex against title+commodities columns, and fetches detail pages + PDFs using the same extraction logic; camoufox browser arg signature kept for API compat; 152 tests pass | `src/agents/procurement_intelligence_specialist.py`, `requirements.txt` |
| 2026-03-08 | Added scrape_bcbid() — Playwright scraper for bcbid.gov.bc.ca: ivCaptcha auto-resolves in headless Chromium, keyword filter on listing table, navigates to opportunity detail page, downloads up to 2 PDFs from RFx Documents section, extracts text via pypdf; enhanced scrape_canadatenders() with CanadaTenders_LOGIN/PASSWORD auth + _PROCUREMENT_KEYWORDS search + _fetch_canadatenders_detail() extracting org/deadline/summary; removed scrape_globaltenders() (zero BD value); added pypdf>=4.0.0 to requirements.txt; added BCBid fixture listing (#8); updated docs/CLAUDE.md and docs/agent/overview.md; 152 tests pass | `src/agents/procurement_intelligence_specialist.py`, `requirements.txt`, `docs/CLAUDE.md`, `docs/agent/overview.md` |
| 2026-03-07 | Replaced duration_ms INTEGER with duration_secs REAL in pipeline_runs for human-readable timing; added tokens_in INTEGER, tokens_out INTEGER, output_validity_rate REAL columns to pipeline_runs; updated log_pipeline_run() signature (ms → secs param, 3 new keyword args); all callers in orchestrator and main.py updated to use round(monotonic, 3); state timings dict key renamed duration_ms → duration_secs; 1 new test (test_log_pipeline_run_tokens_and_validity); 152 tests pass | `src/database.py`, `src/opportunity_orchestrator.py`, `main.py`, `tests/test_database.py` |
| 2026-03-07 | Moved digest email delivery from OpportunityIntelligenceAdvisor to send_weekly_digest() in main.py (Option B architecture); DigestAgent.run() now returns payload dict {html, subject, opportunity_ids, stats, n} with no side effects; send_weekly_digest() owns Resend API call, mark_sent(), and delivery log; orchestrator calls log_pipeline_run() after each agent capturing per-agent throughput (scraped/qualified/scored/assured/contacts/final); pipeline_runs table gains email_sent_at, delivery_status, resend_message_id columns; _send_via_resend() returns (bool, message_id) tuple; 6 new tests added; 151 tests pass | `src/agents/opportunity_intelligence_advisor.py`, `src/opportunity_orchestrator.py`, `main.py`, `src/database.py`, `tests/test_agents.py`, `tests/test_database.py`, `tests/test_pipeline.py` |
| 2026-03-07 | Renamed all 9 agents and orchestrator to enterprise operating model titles (ScraperAgent → ProcurementIntelligenceSpecialist, FilterAgent → OpportunityQualificationSpecialist, ScoringAgent → OpportunityStrategyAnalyst, ScoringCritic → ScoringAssuranceAnalyst, ContactSourcer → StakeholderIntelligenceSpecialist, ContactCritic → StakeholderValidationAnalyst, OutreachWriter → ExecutiveOutreachStrategist, DigestAgent → OpportunityIntelligenceAdvisor, Pipeline → OpportunityOrchestrator); renamed all 9 source files to match; updated all import paths in main.py, all 5 test files, and all mock patch strings; updated 14 documentation files including CLAUDE.md, docs/CLAUDE.md, docs/agent/overview.md, README.md, and architecture diagrams; renamed 6 agent doc files; 145 tests pass throughout | `src/opportunity_orchestrator.py`, `src/agents/procurement_intelligence_specialist.py`, `src/agents/opportunity_qualification_specialist.py`, `src/agents/opportunity_strategy_analyst.py`, `src/agents/scoring_assurance_analyst.py`, `src/agents/stakeholder_intelligence_specialist.py`, `src/agents/stakeholder_validation_analyst.py`, `src/agents/executive_outreach_strategist.py`, `src/agents/opportunity_intelligence_advisor.py`, `main.py`, `tests/` |
| 2026-03-04 | Reduced scrape frequency from daily (7×/week) to twice-weekly (Mon + Thu 7 AM PT); API costs unchanged (filter cache means recurring URLs cost $0 regardless of run frequency); saves ~40 GitHub Actions compute minutes/week with no BD value loss given Monday-only digest; workflow_dispatch retained for on-demand manual runs | `.github/workflows/daily_scrape.yml` |
| 2026-03-04 | Added contract value enrichment: scoring_agent._score_listing() now backfills listing["value"] from parse_rfp_metadata() budget field when value is empty or "Not specified", so parsed budget persists to DB and is available to the priority score; updated digest_agent._opp_section() to render value with "Contract Value:" label and suppress "Not specified" strings; added 5 tests (3 digest rendering, 2 scoring agent enrichment/preservation) | `src/agents/scoring_agent.py`, `src/agents/digest_agent.py`, `tests/test_agents.py` |
| 2026-03-04 | Switched outreach generation model from scoring LLM to pre-filter LLM (93% cost reduction, comparable output quality confirmed by 3-scenario live evaluation); added prompt guard "Do NOT reference specific years of the client's experience or history" to prevent unverifiable historical claims observed in output during evaluation | `src/agents/outreach_writer.py` |
| 2026-03-04 | Pipeline quality and efficiency upgrade (items 1–5 of 7.5→10/10 plan): fixed OutreachWriter to instantiate anthropic.Anthropic() once in __init__ instead of per-contact (was creating a new HTTP session per API call); moved CLIENT_PROFILE (~800 tokens) to Anthropic system role with cache_control ephemeral to enable prompt caching across scoring LLM calls; persisted pre-filter LLM filter results (pass and fail) to DB via new filter_score/filter_scored_at columns and get_filter_result()/save_filter_result() functions to eliminate re-scoring recurring URLs across daily runs; added parse_rfp_metadata() to extraction_utils.py to extract structured fields (budget, duration, department, closing date) from raw HTML before passing to scoring LLM; added cross-source deduplication via deterministic content_hash (SHA-256 of normalized title+org+deadline) with filter_hash_duplicates() function and idx_content_hash index; updated ScraperAgent to apply hash dedup after URL dedup; updated save_opportunity() to persist content_hash; added 20 new tests (get_filter_result, save_filter_result, filter_hash_duplicates ×6, parse_rfp_metadata ×6); eval_outreach_model.py added as one-shot quality/cost evaluation script for item 6 (not part of pipeline) | `src/agents/outreach_writer.py`, `src/agents/scoring_agent.py`, `src/agents/filter_agent.py`, `src/agents/extraction_utils.py`, `src/agents/scraper.py`, `src/database.py`, `tests/test_database.py`, `tests/test_extraction.py` |
| 2026-03-04 | Playwright scraper optimizations: added _block_resources() route handler to abort image/stylesheet/font/media requests in all 5 Playwright scrapers; refactored scrape_merx/bidnet/canadabuys/bidsandtenders/tendersontime to accept optional browser= param and create isolated browser.new_context() per scraper; scrape_all() now launches one sync_playwright() + one shared browser for the sequential Playwright block (5 launches → 1, ~8s saved); replaced wait_for_load_state("networkidle") with wait_for_selector() on target elements for MERX, BidNet, CanadaBuys, and BidsAndTenders listings page (auth flows keep networkidle); added per-scraper wall-clock timing logs and total block timing for runtime instrumentation | `src/agents/scraper.py` |
| 2026-03-04 | Pipeline performance optimizations: added filter_new_urls() batch dedup (single IN-clause query replaces N individual is_duplicate() calls); converted mark_sent() loop to single IN-clause UPDATE; converted save_contacts() loop to executemany; removed time.sleep(0.3/0.5) between Claude API calls in filter/scoring/outreach agents, replaced with retry-on-429 exponential backoff; removed redundant time.sleep(2) after Playwright networkidle waits in MERX, BidNet, CanadaBuys, BidsAndTenders; reduced TendersOnTime login sleeps (3→1s, 5→2s, 5→3s); parallelized 7 requests-based scrapers via ThreadPoolExecutor(max_workers=7) in scrape_all() | `src/database.py`, `src/agents/filter_agent.py`, `src/agents/scoring_agent.py`, `src/agents/outreach_writer.py`, `src/agents/scraper.py`, `tests/test_database.py` |
| 2026-03-03 | Documentation and dependency overhaul: created root README.md (GitHub-profile standard with architecture diagram, scoring tables, setup guide); created root CLAUDE.md (agent orchestration rules, non-negotiable constraints, UTD checklist); rewrote docs/CLAUDE.md as token-efficient per-sub-agent reference (role, reads/writes, rules for all 8 agents + 2 helpers); updated requirements.txt — removed unused google-search-results package (SerpAPI called via requests REST, not SDK), updated anthropic floor to >=0.40.0 for scoring LLM/pre-filter LLM model IDs, switched from exact pins to >= minimums | `README.md`, `CLAUDE.md`, `docs/CLAUDE.md`, `requirements.txt` |
| 2026-03-03 | Fixed weekly digest reliability: added load_dotenv() and init_db() to send_weekly_digest() in main.py (digest crashed when DB artifact missing); removed module-level _SENDER/_RECIPIENT/_RESEND_KEY constants from digest_agent.py (captured empty at import before load_dotenv ran); fixed stale _RECIPIENT NameError in DigestAgent.run() log line (crashed after mark_sent() was called, after Resend 2xx) | `main.py`, `src/agents/digest_agent.py` |
| 2026-03-03 | Full production audit: removed stale `import time` from main.py; rewrote mark_sent() to per-row UPDATE eliminating .format() SQL antipattern; added scoring_critic.py to allowed anthropic-client list in antipatterns.md with rationale (rescoring requires direct API access); corrected extraction_utils.py step-comment numbering (fallback runs before budget in implementation); corrected scorer.md extraction steps 7/8 ordering to match code; created docs/client-briefing.md client context loaded at workflow start; set local git identity to Nammn Joshii | `main.py`, `src/database.py`, `src/agents/extraction_utils.py`, `docs/agent/scorer.md`, `docs/operation/antipatterns.md`, `docs/client-briefing.md` |
| 2026-03-03 | Implemented full unified system upgrade: expanded capability taxonomy to 12 end-to-end data lifecycle domains; replaced extract_relevant_sections() with multi-step extract_rfp_content() pipeline (paragraph segmentation, title similarity, portal regex, capability matching, dedup, token budget, fallback) with [SCORER-EXTRACT] debug log; added opportunity_priority_score (0–100 int, 7-component weighted composite) computed post-scoring and validated by ScoringCritic; upgraded ContactCritic to 4-component weighted model (seniority 40%, domain 35%, signals 15%, proximity 10%) with [CONTACT-SCORE] per-contact debug logging; added colour-coded PRIORITY badge to digest sorted by (opportunity_priority_score DESC, relevance_score DESC); added opportunity_priority_score column to DB with migration; created extraction_utils.py and regex_profiles.py helper modules; added 3 new test files (test_extraction.py, test_scoring_priority.py, test_contact_relevance.py) | `src/agents/extraction_utils.py`, `src/agents/regex_profiles.py`, `src/agents/scoring_agent.py`, `src/agents/scoring_critic.py`, `src/agents/contact_critic.py`, `src/agents/digest_agent.py`, `src/database.py`, `docs/data/capability-profile.md`, `docs/agent/scorer.md`, `docs/agent/contact.md`, `docs/agent/digest.md`, `docs/agent/overview.md` |
| 2026-03-03 | Refactored ContactCritic from binary seniority/domain pass-fail to weighted scoring model (0–100); replaced `_is_valid_contact()` with `_score_contact()` using tiered seniority (+5/+15/+25/+40), domain (+10/+30/+40), and signal bonuses (+5/+10/+10); contacts sorted descending and capped at top 3; retry threshold changed from `len<1` to `all scores<30`; added `relevance_score` field to contact schema; DRY_RUN assigns fixed score 80 | `src/agents/contact_critic.py`, `docs/agent/contact.md` |
| 2026-03-03 | Added TorontoBids scraper (54 listings, pure requests via public OData API at secure.toronto.ca; no auth required); added TendersOnTime scraper (40 listings: 20 Canada + 20 USA, Playwright login via TendersOnTime_LOGIN/PASSWORD) | `src/agents/scraper.py`, `docs/agent/scraper.md` |
| 2026-03-03 | Activated BidsCanada (50 listings, requests-based login with BIDSCANADA_LOGIN/PASSWORD) and BidsAndTenders Metro Vancouver (20 listings, Playwright login with BIDS_AND_TENDERS_LOGIN/PASSWORD); both previously returned 0 | `src/agents/scraper.py`, `docs/agent/scraper.md` |
| 2026-03-03 | Added SaskTenders (49 public listings, requests+BS4) and AlbertaPurchasing (public REST API, 100 most-recent from 16k+ listings) scrapers; evaluated and documented 7 other candidate sources (4 paywalled, 2 login-required, 1 CAPTCHA-blocked) | `src/agents/scraper.py`, `docs/agent/scraper.md` |
| 2026-03-03 | Expanded scraper to 8 sources — added MERX public URL fix, BidNet, BidsCanada, BidsAndTenders, CanadaTenders, GlobalTenders; rewrote CanadaBuys with Playwright; updated scope to Canada + USA | `src/agents/scraper.py`, `docs/agent/scraper.md` |
| 2026-03-03 | Expanded ideal client profile to include US government agencies and private sector in Canada/USA | `docs/data/capability-profile.md` |
| 2026-03-03 | Ran full end-to-end live test with fixed RFPMart scraper — 183 scraped (182 RFPMart + 1 CanadaBuys), 6 filtered, 1 PURSUE scored 82, all agents completed successfully | `main.py`, all agents |
| 2026-03-03 | Fixed RFPMart scraper — replaced 404 URL with two working category pages; switched from JSON-LD to anchor-tag parsing; now returns 182 Canada/USA listings | `src/agents/scraper.py` |
| 2026-03-02 | Completed Step 13 final smoke test — live pipeline ran end-to-end, Anthropic API 200 OK, filter correctly dropped non-RFP listing | `main.py`, all agents |
| 2026-03-02 | Created GitHub Actions workflows for daily scrape (7am PT) and weekly digest (8am Mon PT) | `.github/workflows/daily_scrape.yml`, `.github/workflows/weekly_digest.yml` |
| 2026-03-02 | Wrote 44-test pytest suite covering all modules; all passing | `tests/test_database.py`, `tests/test_agents.py`, `tests/test_pipeline.py` |
| 2026-03-02 | Built calibration_check() in ScoringCritic with CALIBRATION_PATH env var and 10-entry golden set | `src/agents/scoring_critic.py`, `tests/fixtures/calibration_set.json` |
| 2026-03-02 | Migrated email delivery from SendGrid to Resend across all code, docs, and requirements | `src/agents/digest_agent.py`, `main.py`, `requirements.txt`, multiple docs |
| 2026-03-02 | Built main.py, digest_agent.py, outreach_writer.py — completing Steps 9–11 | `main.py`, `src/agents/digest_agent.py`, `src/agents/outreach_writer.py` |
| 2026-03-02 | Built Steps 1–8: database, pipeline, scraper, filter, scorer, critic, contact sourcer, contact critic | `src/database.py`, `src/pipeline.py`, `src/agents/*.py`, `tests/fixtures/*.json` |
| 2026-02-28 | Raised FILTER_THRESHOLD from 40 to 60; updated filter.md and antipatterns.md | `agent/filter.md`, `operation/antipatterns.md` |
| 2026-02-28 | Added `decision_log` TEXT column to opportunities table | `data/schema.md`, `src/database.py` |
| 2026-02-28 | Added `pipeline_runs` table for observability | `data/schema.md`, `src/database.py` |
| 2026-02-28 | Added `has_score()` function for score caching | `src/database.py`, `agent/filter.md` |
| 2026-02-28 | Pinned all requirements to exact versions (`==`) | `requirements.txt`, `infrastructure/environment.md` |
| 2026-02-28 | Added failure alert email to `main.py` on unrecoverable exception | `src/main.py` |
| 2026-02-28 | Added `concurrency: group: pipeline` to both GitHub Actions workflows | `infrastructure/github-actions.md` |
| 2026-02-28 | Initial multi-agent architecture built: 8 agents + Pipeline orchestrator | All `agent/*.md`, `src/agents/*.py` |
