---
module: agent/opportunity_qualification_specialist
purpose: Define OpportunityQualificationSpecialist model choice, threshold logic, score caching, and pass/fail contract
dependencies: src/agents/opportunity_qualification_specialist.py, src/database.py (has_score)
last_updated: 2026-02-28
---

## Purpose

`OpportunityQualificationSpecialist` performs a cheap pass/fail score on each new listing before committing to full deep scoring. Listings below threshold are dropped here, not downstream. Score results are not persisted — this stage is purely a gate.

---

## Scope

- Covers model selection, threshold enforcement, cache check, and state output.
- Excludes: full scoring logic, contact discovery, DB writes.
- Operates only on `state['listings']`; writes to `state['filtered']` and `state['skipped']`.

---

## Key Decisions

- **Model: pre-filter LLM only.** The pre-filter LLM costs ~20× less than the scoring LLM. This stage sends ≤500 characters per listing. Scoring LLM accuracy is not justified at this volume and text length.
- **Threshold: 60 (configurable via `FILTER_THRESHOLD` env var).** Listings scoring 40–59 are marginal fits with low win probability. Raising from 40 to 60 reduces downstream scoring LLM calls by ~35%.
- **Cache check first:** `has_score(url)` is called before any API call. Already-scored listings bypass the filter entirely and are added directly to `state['filtered']`.
- **Failure defaults to pass:** If the pre-filter LLM call fails for a listing, that listing passes to `state['filtered']` with a default score of 50. Benefit of doubt prevents silent data loss.

---

## Constraints

- `time.sleep(0.3)` between pre-filter LLM calls.
- Prompt must request a single integer 0–100 — no JSON, no explanation.
- `DRY_RUN=true`: skip all API calls; assign score 75 to all listings; add all to `state['filtered']`.
- Log: `[FILTER] {n} passed, {m} dropped` after processing all listings.

---

## Interfaces / Dependencies

**Input:** `state['listings']` — list of listing dicts (see `agent/procurement_intelligence_specialist.md` for schema).

**DB calls:**
- `has_score(url: str) -> bool`

**State output:**
```python
state['filtered'] = [listing, ...]          # score >= FILTER_THRESHOLD
state['skipped']  = [{**listing,
  'skip_reason': 'below filter threshold',
  'filter_score': int}, ...]
```

---

## Risks / Considerations

- **Threshold drift:** If the sales team reports too many irrelevant leads, raise `FILTER_THRESHOLD` in `.env` — do not edit source code. Current default: 60.
- **Pre-filter LLM deprecation:** If the pre-filter LLM is retired, update this file and `opportunity_qualification_specialist.py` simultaneously. Check `infrastructure/cost.md` for replacement cost impact.
- **False negatives:** A genuinely strong RFP with poor title wording may score below 60. Threshold is a deliberate trade-off — revisit quarterly using `quality/calibration.md` data.
