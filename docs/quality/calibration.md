---
module: quality/calibration
purpose: Define the golden scoring set structure, seed entries, and storage contract
dependencies: tests/fixtures/calibration_set.json, data/capability-profile.md
last_updated: 2026-03-01
---

## Purpose

Provides the ground-truth scoring baseline used by `ScoringCritic`. The golden set is the only authoritative reference for whether a score is plausible — not the prompt, not intuition.

---

## Scope

- Covers golden set schema, the 10 required seed examples, and storage contract.
- Excludes: critic comparison logic and drift detection (those live in `quality/drift.md`).
- Capability profile score bands are defined in `data/capability-profile.md` and not repeated here.

---

## Key Decisions

- **10 examples minimum: 5 PURSUE, 5 SKIP.** Drawn from real past bid/no-bid decisions. CONSIDER examples are optional — PURSUE/SKIP poles define the scoring range.
- **No client-sensitive data.** Use generalised descriptions. File may be committed to a shared repo.
- **Stored in `tests/fixtures/calibration_set.json` only.** Never hardcoded in source. `ScoringCritic` loads this path at runtime via `CALIBRATION_PATH` env var (default: `tests/fixtures/calibration_set.json`).
- **Rebuild after any capability profile change.** A golden set built against an outdated profile produces false calibration signals.

---

## Constraints

- Required fields: `id`, `title`, `org`, `domain_keywords`, `expected_score`, `expected_recommendation`, `rationale`, `active`.
- `rationale`: ≤2 sentences. One on fit, one on the deciding factor.
- `expected_score` must fall within the band for its `expected_recommendation`. A PURSUE example scoring 61 is invalid.
- Do not delete entries. Mark stale examples `"active": false`.

---

## Interfaces / Dependencies

**Schema:**
```python
{
  "id":                      str,
  "title":                   str,
  "org":                     str,
  "domain_keywords":         list[str],
  "expected_score":          int,
  "expected_recommendation": str,   # PURSUE | CONSIDER | SKIP
  "rationale":               str,
  "active":                  bool,
}
```

**Seed entries:**

| ID | Description | Expected | Score |
|----|-------------|----------|-------|
| golden-001 | Crown Corp Snowflake warehouse | PURSUE | 88 |
| golden-002 | Federal Power BI dashboard | PURSUE | 82 |
| golden-003 | Municipal data governance | PURSUE | 79 |
| golden-004 | Provincial ML pipeline | CONSIDER | 68 |
| golden-005 | City digital transformation | CONSIDER | 55 |
| golden-006 | Highway construction | SKIP | 4 |
| golden-007 | Medical device procurement | SKIP | 3 |
| golden-008 | Court administration staffing | SKIP | 8 |
| golden-009 | IT hardware refresh | SKIP | 12 |
| golden-010 | Legal services retainer | SKIP | 5 |

---

## Risks / Considerations

- **Stale examples:** Rebuild within the same sprint as any capability profile change.
- **Sparse CONSIDER band:** Only 2 CONSIDER examples weakens mid-range calibration. Add 3 more from real past opportunities.
- **Silent skip on missing fixture:** If `calibration_set.json` is missing, `ScoringCritic` must log `[WARN] calibration file not found — skipping` rather than passing silently or raising.
