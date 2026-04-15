---
module: agent/strategic_scoring_agent
purpose: Define StrategicScoringAgent deep-score logic, ScoringAssuranceAnalyst validation rules, and output schema
dependencies: src/agents/strategic_scoring_agent.py, src/agents/scoring_assurance_analyst.py, src/agents/extraction_utils.py, src/agents/regex_profiles.py, data/capability-profile.md
last_updated: 2026-04-15
---

## Purpose

`StrategicScoringAgent` fetches full RFP text, runs it through the multi-step extraction pipeline (`extract_rfp_content()`), and produces a structured score via the scoring LLM. It also computes a deterministic `opportunity_priority_score` from the scored result and listing metadata. `ScoringAssuranceAnalyst` validates the output schema and score calibration, retrying up to 2 times before accepting.

---

## Scope

- Covers document fetch, section extraction, prompt construction, JSON parsing, priority score computation, and critic validation.
- Excludes: filter-stage quick scoring — `OpportunityQualificationSpecialist` uses the pre-filter LLM on ≤500 chars before this stage runs. Contact enrichment and digest formatting are downstream.
- CLIENT_PROFILE content lives exclusively in `data/capability-profile.md` — not duplicated here.
- Extraction logic lives in `src/agents/extraction_utils.py` and `src/agents/regex_profiles.py`.

---

## Key Decisions

- **Multi-step extraction replaces simple section extraction:** `extract_rfp_content()` in `extraction_utils.py` runs 8 steps (paragraph segmentation, title similarity, regex extraction, capability matching, header-based extraction, deduplication, token budget, fallback). Emits `[SCORER-EXTRACT]` debug log on every call.
- **Capability keywords drive semantic segmentation:** `CAPABILITY_KEYWORDS` list in `strategic_scoring_agent.py` (flat; derived from full lifecycle taxonomy in `capability-profile.md`) is passed to `extract_rfp_content()` for paragraph scoring.
- **Portal-specific regex:** `regex_profiles.py` provides compiled patterns for MERX, CanadaBuys, BCBid, and RFPMart. Unknown portals fall back gracefully to empty pattern list.
- **`opportunity_priority_score` is computed locally:** Computed after LLM response using `compute_priority_score(listing, scored)`. No API call. Weighted composite of 7 factors (see schema below). Validated by ScoringAssuranceAnalyst.
- **Score caching:** `has_score(url)` is checked before fetching the document. Cache hit loads the existing DB record and skips the API call entirely. Priority score is re-computed on cache hit if absent.
- **Critic cap at 2 loops:** After 2 failed validations, ScoringAssuranceAnalyst accepts the best available result and appends `{warn: 'critic_capped'}` to `decision_log`.
- **Model locked to scoring LLM:** Do not substitute the pre-filter LLM here. Scoring accuracy on full RFP sections requires the higher-capability scoring model.

---

## Constraints

- `time.sleep(0.5)` between scoring LLM calls.
- StrategicScoringAgent response must be valid JSON — parse with `json.loads()`.
- `DRY_RUN=true`: return contents of `tests/fixtures/sample_scored.json` without API call. Priority score is still computed from fixture + listing data.
- Log prefix: `[SCORER]` for StrategicScoringAgent, `[SCORER-EXTRACT]` for extraction pipeline, `[CRITIC-SCORE]` for ScoringAssuranceAnalyst.

---

## Extraction Pipeline (`extract_rfp_content`)

Located in `src/agents/extraction_utils.py`. Steps:

1. **Paragraph segmentation** — blank-line split, 60–250 words per segment
2. **Title similarity scoring** — Jaccard similarity between paragraph and RFP title
3. **Portal regex extraction** — `regex_profiles.find_regex_hits(text, source)` for MERX/CanadaBuys/BCBid/RFPMart
4. **Capability keyword matching** — count of `CAPABILITY_KEYWORDS` hits per paragraph
5. **Section-header extraction** — target sections: scope, background, objectives, requirements, eligibility, evaluation, deliverables, qualifications
6. **Merge + dedupe** — 90% Jaccard threshold removes near-duplicates
7. **Fallback check** — if extracted content < 500 words, use first 2000 words of raw document (runs before budget so budget applies to fallback output too)
8. **Token budget enforcement** — hard cap at 3500 tokens (~2600 words) applied last

**Debug log block `[SCORER-EXTRACT]`:**
```
[SCORER-EXTRACT] source={source} paragraphs_count={n} embedded_chunks={n}
regex_hits={n} capability_hits={n} final_token_estimate={n}
fallback_used={bool} extraction_time_ms={n}
```

---

## opportunity_priority_score Computation

Weighted composite (0–100 int, computed locally — no API call):

| Component | Weight | Range | Notes |
|-----------|--------|-------|-------|
| relevance_score | 35% | 0–100 | From scoring LLM |
| rfp_type_score | 10% | 0–100 | RFP=100, RFQ=70, RFI=50, other=30 |
| estimated_contract_value_score | 20% | 0–100 | <100K=20, 100K–500K=60, 500K–1M=80, >1M=100 |
| time_left_score | 10% | 0–100 | >60d=100, 30–60d=70, 14–30d=40, <14d=20 |
| capability_match_count_score | 15% | 0–100 | 0=0, 1=25, 2=50, 3=75, 4+=100 |
| risk_profile_score | 5% | 0–100 | 0 risks=100, 1=70, 2=40, 3+=20 |
| strategic_fit_score | 5% | 0–100 | PURSUE=100, CONSIDER=60, SKIP=20 |

---

## Interfaces / Dependencies

**Scored output schema (all keys required from scoring LLM — 9 keys):**
```python
{
  "relevance_score":          int,        # 0–100
  "recommendation":           str,        # PURSUE | CONSIDER | SKIP
  "score_rationale":          str,        # ≤2 sentences
  "capability_match":         list[str],  # matched CLIENT_PROFILE items
  "risks":                    list[str],  # disqualifying or limiting factors
  "estimated_effort":         str,        # S | M | L | XL
  "exec_summary":             str,        # ≤3 sentences for digest
  "suggested_angle":          str,        # 1 sentence positioning statement
  "decision_log":             list[dict], # appended by critic
  # Added by StrategicScoringAgent post-scoring (not from scoring LLM):
  "opportunity_priority_score": int,      # 0–100, composite weighted score
}
```

---

## Risks / Considerations

- **JSON parse failures:** The scoring LLM occasionally wraps JSON in markdown fences. Strip ` ```json ` and ` ``` ` before parsing.
- **Score inflation:** Without calibration baseline, scores drift upward over time. Validate quarterly against `quality/calibration.md` golden set.
- **Extraction fallback rate:** If `[SCORER-EXTRACT] fallback_used=True` appears frequently, review paragraph segmentation thresholds or portal regex coverage.
- **Token budget accuracy:** Word count is used as a proxy (1.35 words/token). Actual token count may vary by content type. Monitor `final_token_estimate` vs actual scoring LLM input token count.
