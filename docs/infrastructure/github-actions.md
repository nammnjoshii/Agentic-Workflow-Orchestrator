---
module: infrastructure/github-actions
purpose: Define both workflow files, cron schedules, artifact strategy, and manual trigger pattern
dependencies: .github/workflows/daily_scrape.yml, .github/workflows/weekly_digest.yml
last_updated: 2026-02-28
---

## Purpose

Two separate GitHub Actions workflows automate the agent. `daily_scrape.yml` runs the full pipeline on Monday and Thursday mornings (and on demand via `workflow_dispatch`). `weekly_digest.yml` sends the Monday email. Both use the SQLite DB as an artifact passed between runs.

---

## Scope

- Covers workflow structure, schedule, artifact upload/download, secret injection, and manual trigger.
- Excludes: pipeline logic, agent implementation, cost tracking .

---

## Key Decisions

- **Two workflows, never one.** The digest does not re-scrape. Combining them wastes API calls and complicates debugging.
- **DB persisted as artifact.** GitHub Actions has no persistent filesystem. The DB is uploaded at the end of each run and downloaded at the start of the next. Artifact retention: 7 days.
- **All secrets injected as env vars.** No secrets are hardcoded or passed as CLI args. The `env:` block in each job maps GitHub Secrets to env var names exactly matching `infrastructure/environment.md`.
- **`workflow_dispatch` on both workflows.** Enables manual trigger from the GitHub Actions UI without waiting for the cron schedule.

---

## Constraints

- Cron expressions use UTC. `0 15 * * 1` / `0 15 * * 4` = 7am PT Mon + Thu (UTC-8). Adjust to `0 14 * * 1,4` in summer (PDT) if exact timing matters.
- `actions/upload-artifact` and `actions/download-artifact` must use the same artifact name: `opportunity-db`.
- Workflow files must not shell-date-switch between scrape and digest logic — that is prohibited in `operation/antipatterns.md`.
- Python version pinned to `3.12` in both workflows.

---

## Interfaces / Dependencies

**`daily_scrape.yml` structure:**
```yaml
name: Daily RFP Scrape
on:
  schedule: [{cron: '0 15 * * 1'}, {cron: '0 15 * * 4'}]
  workflow_dispatch:
jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.12'}
      - run: pip install -r requirements.txt
      - run: playwright install chromium
      - uses: actions/download-artifact@v4
        with: {name: opportunity-db, path: data/}
        continue-on-error: true
      - run: python main.py
        env: {ANTHROPIC_API_KEY: ${{secrets.ANTHROPIC_API_KEY}}, ...}
      - uses: actions/upload-artifact@v4
        with: {name: opportunity-db, path: data/opportunities.db}
```

**`weekly_digest.yml` structure:** Identical except `cron: '0 16 * * 1'` and `run: python main.py digest`.

---

## Risks / Considerations

- **Artifact expiry:** After 7 days without a run, the artifact expires and the next digest is empty. `continue-on-error: true` on download prevents job failure; the stats block `0 scraped` signals expiry.
- **Concurrent runs:** Add `concurrency: group: pipeline` to both workflows. Without it, two overlapping cron triggers can corrupt the DB artifact.
- **Free tier:** GitHub Actions provides 2000 min/month. ~8 scrapes/month (Mon + Thu) × 8 min = ~64 min/month. Well within limits at current volume.
