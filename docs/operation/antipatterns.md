---
module: operation/antipatterns
purpose: Enumerate prohibited patterns with rationale; overrides all other files on conflict
dependencies: none
last_updated: 2026-03-01
---

## Purpose

Hard stop list. This file supersedes all other files on conflict. Check before implementing any non-trivial change.

---

## Scope

- Architecture, database, scoring, contact, email, testing, and workflow patterns.
- Applies to Claude Code sessions and human edits equally.

---

## Key Decisions

- All items are final. Changes require a `operation/changelog.md` entry: old rule, new rule, reason.
- The inline rationale after each `❌` is authoritative. Argue against the rationale to justify an exception — not the pattern.

---

## Constraints

- No exceptions without a changelog entry.
- Items must describe a pattern with a concrete failure mode — not style preferences.

---

## Interfaces / Dependencies

None. Standalone by design.

---

## Antipattern List

**Architecture**
- ❌ `sqlite3` outside `src/database.py` — fragments ownership, bypasses parameterised query enforcement
- ❌ `anthropic` client outside `filter_agent.py`, `scoring_agent.py`, `scoring_critic.py`, `outreach_writer.py` — breaks cost tracking and key rotation (scoring_critic.py added 2026-03-03: critic requires direct Claude API access to rescore on validation failure; all other files remain prohibited)
- ❌ `async`/`await` anywhere — incompatible with `signal.alarm` timeout
- ❌ Pandas, SQLAlchemy, or any ORM — unnecessary; raw `sqlite3` sufficient at this volume
- ❌ New top-level `.py` files without updating `agent/overview.md` — undocumented agents invisible to future sessions

**Database**
- ❌ f-strings or `.format()` in SQL — SQL injection risk
- ❌ `eval()` to deserialise JSON — `json.loads()` only
- ❌ Drop-and-recreate for schema changes — use `ALTER TABLE ADD COLUMN IF NOT EXISTS`

**Scoring**
- ❌ Editing `CLIENT_PROFILE` without updating `data/capability-profile.md` — breaks single source of truth
- ❌ Pre-filter LLM in `ScoringAgent` — accuracy insufficient for full RFP deep scoring; scoring LLM only
- ❌ Removing Filter → Scoring two-phase architecture — eliminates primary cost-control mechanism
- ❌ `FILTER_THRESHOLD` below 50 without documented justification — exposes scoring LLM to low-signal volume

**Contact and Email**
- ❌ Sending outreach directly to discovered contacts — CASL; agent surfaces for manual use only
- ❌ `<style>` tags in digest HTML — stripped by Gmail/Outlook; inline only
- ❌ `max_contacts_per_opportunity` above 3 without reviewing `infrastructure/cost.md`
- ❌ `smtplib` — Resend API only; `smtplib` bypasses delivery tracking

**Testing**
- ❌ Live API calls in tests — `DRY_RUN=true` and fixtures only
- ❌ Modifying `tests/fixtures/` to make a test pass — fixtures are the schema contract baseline
- ❌ Tests without `DRY_RUN=true` in CI

**GitHub Actions**
- ❌ Combining scrape and digest into one workflow — prevents independent failure isolation
- ❌ Hardcoding API keys in workflow YAML — GitHub Secrets only
- ❌ Removing `continue-on-error: true` from artifact download — fails when artifact has expired

---

## Risks / Considerations

- **Staleness:** Update immediately when a refactor legitimately removes a prohibited pattern. A stale list loses authority.
- **Conflict resolution:** This file wins. If silent on a conflict, escalate before acting.
- **Scope creep:** Items require a concrete failure mode or they do not belong here.
