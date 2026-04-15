---
module: quality/drift
purpose: Define score drift detection logic, comparison algorithm, and quarterly review process
dependencies: src/agents/scoring_critic.py, tests/fixtures/calibration_set.json
last_updated: 2026-03-01
---

## Purpose

Defines how `ScoringCritic` compares new scores against the golden set and how quarterly drift reviews are conducted. Separated from `quality/calibration.md` to isolate the detection algorithm from the data it operates on.

---

## Scope

- Covers critic comparison logic, drift thresholds, and the quarterly review checklist.
- Excludes: golden set contents and schema (`quality/calibration.md`), prompt engineering (`agent/scorer.md`).

---

## Key Decisions

- **Keyword similarity:** Match if ≥2 `domain_keywords` overlap. No match → skip check, never block scoring.
- **Tolerance band: ±15 points.** Within ±15 of closest golden `expected_score` → accepted. Outside → `[WARN]` appended to `decision_log`.
- **Critic compares only.** Does not re-score golden examples. Recalibration is a human task.
- **Drift threshold: ±10 points over 4 weeks.** Mean PURSUE score per keyword cluster shifting >10 points vs prior 4-week mean → flag for prompt review. Computed from `opportunities` table.

---

## Constraints

- Calibration check runs after schema and score-band validation — not before.
- Maximum 1 calibration warning per listing in `decision_log`.
- Drift computation requires ≥10 scored listings in window. Fewer → log `[INFO] insufficient data` and skip.
- Drift flag is a warning only. Appears in `pipeline_runs.errors`. Never blocks delivery.

---

## Interfaces / Dependencies

**Critic comparison pseudologic:**
```python
def calibration_check(scored: dict, golden_set: list) -> str | None:
    matches = [g for g in golden_set
               if g["active"]
               and len(set(scored["keywords"]) & set(g["domain_keywords"])) >= 2]
    if not matches:
        return None  # no baseline — skip
    closest = min(matches, key=lambda g: abs(g["expected_score"] - scored["relevance_score"]))
    delta = abs(closest["expected_score"] - scored["relevance_score"])
    if delta > 15:
        return f"score {scored['relevance_score']} deviates {delta}pt from golden-{closest['id']}"
    return None
```

**Quarterly review checklist:**
- [ ] Pull mean PURSUE score for last 90 days from `opportunities` table
- [ ] Compare against prior 90-day mean — flag if delta > 10
- [ ] Review any listing where `decision_log` contains a calibration warning
- [ ] If systematic drift confirmed: update scorer prompt and rebuild golden set

---

## Risks / Considerations

- **Keyword sparsity:** Unusual RFP terminology matches zero examples — calibration is skipped, not failed.
- **Golden set lag:** Failing to rebuild after a prompt change causes false outlier flags. Rebuild within the same sprint as any scorer prompt update.
- **Drift masking:** Inflation and deflation cancel in aggregate. Always review cluster means, not overall mean.
