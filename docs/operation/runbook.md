---
module: operation/runbook
purpose: Define first-run setup procedure, weekly health checks, and monthly tuning tasks
dependencies: infrastructure/environment.md, infrastructure/github-actions.md, quality/utd-loop.md
last_updated: 2026-02-28
---

## Purpose

Operational reference for setup, monitoring, and maintenance. Each section is a discrete checklist. No knowledge of system internals is required to execute these steps.

---

## Scope

- Covers initial setup, ongoing weekly checks, and monthly calibration tasks.
- Excludes: code changes (follow `quality/utd-loop.md`), cost decisions , debugging individual agents (see relevant `agent/*.md`).

---

## Key Decisions

- **First run uses `DRY_RUN=true`.** Never run the live pipeline until dry-run passes end-to-end.
- **Weekly check is manual, under 5 minutes.** Performed every Monday after the digest arrives.
- **Monthly tuning = threshold adjustment only.** Prompt changes require a full UTD-loop cycle. Threshold changes need only `.env` edit and changelog row.

---

## Constraints

- Do not edit `.env` during an active GitHub Actions run — the run reads env at job start.
- Database artifact must be downloaded before any manual pipeline run to avoid resetting sent-state.
- All threshold changes must be logged in `operation/changelog.md` with the old and new value.

---

## Interfaces / Dependencies

**First-run setup checklist:**
- [ ] All 4 required env vars in `.env` (`infrastructure/environment.md`)
- [ ] `pip install -r requirements.txt` — no errors
- [ ] `playwright install chromium` — completed
- [ ] `CLAUDE.md` present in project root
- [ ] `DRY_RUN=true python3 main.py` — all 8 agent log lines appear
- [ ] GitHub repo (private), Secrets added, workflows pushed
- [ ] Manual `workflow_dispatch` on `daily_scrape.yml` passes green

**Weekly check (every Monday after digest arrives):**
- [ ] Digest email received by 8:15am PT
- [ ] `weekly_digest.yml` → green checkmark
- [ ] Previous week's `daily_scrape.yml` runs → green (note any failures)
- [ ] Stats block shows `>0 scraped` — artifact healthy
- [ ] Spot-check 2–3 PURSUE scores for face validity

**Monthly tuning tasks:**
- [ ] Compare average PURSUE score against golden set (`quality/calibration.md`)
- [ ] Anthropic dashboard (`console.anthropic.com`) — weekly cost under $8; investigate volume spike if exceeded
- [ ] Hunter.io quota — at 80%+ of 25 free searches/month, upgrade to $49/month plan
- [ ] If any source shows `found 0 listings` for 3+ consecutive days, fix that scraper

---

## Risks / Considerations

- **Digest is empty:** Query `pipeline_runs` for recent `status=FAILED`. Verify DB artifact uploaded after last scrape.
- **Actions fails every run:** Expired API key or wrong secret name. Verify exact names against `infrastructure/environment.md`.
- **Local works, cloud fails:** Env var mismatch between `.env` and GitHub Secrets. Compare names character by character.
