---
module: infrastructure/cost
purpose: Define per-service cost model, free-tier limits, monthly estimates, and upgrade triggers
dependencies: infrastructure/environment.md
last_updated: 2026-02-28
---

## Purpose

Track actual and projected costs for all paid services. Provides upgrade decision criteria and cost-reduction levers. Review monthly; update after any architecture change that affects API call volume.

---

## Scope

- Covers Anthropic, Resend, Hunter.io, SerpAPI, and GitHub Actions.
- Excludes: infrastructure provisioning costs (agent runs serverless), developer time.

---

## Key Decisions

- **Pre-filter model for filtering, scoring model for scoring and outreach.** Pre-filter model: ~$0.80/1M input tokens. Scoring model: ~$15/1M input tokens. Using the pre-filter model only at the filter stage and the scoring model downstream reduces weekly Claude cost by ~60% vs scoring-model-only.
- **Document truncation before scoring.** 4000-token cap on RFP input reduces average scoring LLM cost per listing from ~$0.04 to ~$0.012.
- **Score caching prevents repeat billing.** Re-scraping a known URL without `has_score()` check wastes scoring LLM credits. Current implementation prevents this.

---

## Constraints

- Monthly Claude budget target: under $20 USD.
- If weekly Claude cost exceeds $8, investigate listing volume spike before raising budget.
- Hunter.io free tier: 25 domain searches/month. At 3 PURSUE/week = 12/month. Free tier is sufficient at current volume.
- SerpAPI free tier: 100 searches/month. At 3 contact lookups × 2 searches each = ~24/month. Free tier sufficient.

---

## Interfaces / Dependencies

**Monthly cost model (baseline: 150 new listings/week):**

| Service | Usage | Unit Cost | Monthly Est. |
|---------|-------|-----------|-------------|
| Anthropic pre-filter model | ~150 filter calls/day × 500 tokens | $0.80/1M | ~$1.80 |
| Anthropic scoring model | ~50 score calls/day × 4000 tokens | $15/1M | ~$9.00 |
| Anthropic scoring model | ~12 outreach calls/week × 200 tokens | $15/1M | ~$0.14 |
| Resend | 4 digest emails/month | Free tier (3000/month) | $0 |
| Hunter.io | ~12 domain searches/month | Free tier (25/month) | $0 |
| SerpAPI | ~24 searches/month | Free tier (100/month) | $0 |
| GitHub Actions | ~150 min/month | Free tier (2000/month) | $0 |
| **Total** | | | **~$11/month** |

---

## Risks / Considerations

- **Volume spikes:** 400+ listings/day at full scoring model usage costs $6–8 in one run. `FILTER_THRESHOLD=60` absorbs most of the impact.
- **Upgrade triggers:** Hunter.io → $49/month if PURSUE volume exceeds 20/month. Add Apollo.io ($49/month) if Hunter.io coverage is insufficient.
- **SerpAPI fallback:** Free tier rate-limited to 1 req/sec. DuckDuckGo fallback degrades contact quality, not stability.
- **Cost visibility:** Monitor at `console.anthropic.com`. Set a $15/week email alert. No in-agent cost tracking is implemented.
