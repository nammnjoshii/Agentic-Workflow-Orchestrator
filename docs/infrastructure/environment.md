---
module: infrastructure/environment
purpose: Define all environment variables, required vs optional status, defaults, and load pattern
dependencies: python-dotenv, .env file, GitHub Actions Secrets
last_updated: 2026-02-28
---

## Purpose

Authoritative list of all env vars consumed by the agent. Any new variable introduced in code must be documented here first. Load order and validation pattern are defined here and followed everywhere.

---

## Scope

- Covers all vars for local `.env` and GitHub Actions Secrets.
- Excludes: var values (never committed), cost thresholds — upgrade to $49/month Hunter.io if PURSUE volume exceeds 20/month, DB schema — `data/opportunities.db`.

---

## Key Decisions

- **`python-dotenv` loads `.env` at process start.** Call `load_dotenv()` once in `main.py` only — not in individual agent files.
- **Required vars fail fast.** Missing required var → `EnvironmentError` before first agent. No silent degradation.
- **Optional vars degrade gracefully.** Missing optional vars trigger a `[WARN]` log and use the documented fallback behaviour.
- **`DRY_RUN` controls all external calls.** Any agent making a network or API call must check `os.getenv('DRY_RUN','false').lower() == 'true'` before executing.

---

## Constraints

- `.env` must be listed in `.gitignore` — never committed.
- GitHub Actions Secrets must match var names exactly (case-sensitive).
- `DB_PATH` must point to a path writable by the GitHub Actions runner (`data/opportunities.db`).

---

## Interfaces / Dependencies

**Required (pipeline fails without these):**

| Variable | Used By | Description |
|----------|---------|-------------|
| `CLIENT_NAME` | All agents | Organization name injected into AI prompts and email subjects |
| `CLIENT_DESCRIPTION` | All agents | One-line descriptor for AI prompt context |
| `ANTHROPIC_API_KEY` | FilterAgent, ScoringAgent, OutreachWriter | Claude API authentication |
| `RESEND_API_KEY` | DigestAgent | Email delivery via Resend |
| `DIGEST_SENDER` | DigestAgent | Verified Resend sender address (e.g. `noreply@yourdomain.com`) |
| `DIGEST_RECIPIENT` | DigestAgent, failure alerts | Destination email address |

**Optional (fallback behaviour on missing):**

| Variable | Default | Fallback Behaviour |
|----------|---------|-------------------|
| `HUNTER_API_KEY` | — | Skip Hunter.io; log `[WARN]` |
| `SERPAPI_KEY` | — | Use DuckDuckGo Instant Answer |
| `DB_PATH` | `data/opportunities.db` | SQLite in project root |
| `FILTER_THRESHOLD` | `60` | Filter drops listings scoring below 60 |
| `CONTACT_THRESHOLD` | `70` | ContactSourcer skips below-70 opportunities |
| `PURSUE_THRESHOLD` | `75` | DigestAgent sorts PURSUE at 75+ |
| `AGENT_TIMEOUT_SECONDS` | `30` | Per-agent `signal.alarm` duration |
| `DRY_RUN` | `false` | Full live execution |

---

## Risks / Considerations

- **Key rotation:** Rotating a key requires updating both the local `.env` and the GitHub Actions Secret simultaneously. A mismatch causes cloud runs to fail while local runs succeed — difficult to diagnose.
- **`DIGEST_SENDER` verification:** Resend requires the sender domain to have a DNS TXT record added for verification. A valid key with an unverified domain returns 403. Verify at `resend.com/domains`.
- **Secret name typos:** GitHub Actions Secret names are case-sensitive. `Anthropic_API_Key` ≠ `ANTHROPIC_API_KEY`. Verify exact match after creating.
