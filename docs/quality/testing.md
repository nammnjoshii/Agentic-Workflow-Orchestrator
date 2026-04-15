---
module: quality/testing
purpose: Define fixture files, per-module test assertions, and copy-pasteable smoke test commands
dependencies: tests/fixtures/, pytest
last_updated: 2026-02-28
---

## Purpose

Authoritative test reference. Every integration smoke test command is copy-pasteable. Assertions are explicit — no vague "it should work" checks. Fixtures are the only data source for tests that would otherwise call live APIs.

---

## Scope

- Covers unit test assertions per module and integration smoke tests.
- Excludes: test framework setup (pytest, no plugins required). CI runs tests via `pytest tests/ -v` in the GitHub Actions job after `pip install`.
- All tests must pass with `DRY_RUN=true` and no network access.

---

## Key Decisions

- **Never call live APIs in tests.** Any test that hits Anthropic, Resend, Hunter.io, or SerpAPI is a misuse of the test suite. `DRY_RUN=true` is enforced in all test commands.
- **Never delete fixture files.** Fixtures are the contract baseline. Modifying a fixture to make a test pass without updating the schema doc is a violation.
- **Fixtures live in `tests/fixtures/`.** Two required: `sample_listing.json`, `sample_scored.json`. Contents sourced from `data/schema.md` schema examples.

---

## Constraints

- All smoke test commands assume `DRY_RUN=true` in `.env`.
- `pytest` must be run from the project root, not from inside `tests/`.
- Test files must not import `sqlite3` directly — only import from `src/database.py`.

---

## Interfaces / Dependencies

**Smoke tests (copy-paste exactly):**

```bash
# database.py
python3 -c "
from src.database import init_db, is_duplicate, save_opportunity, has_score
init_db()
t = {'title':'T','org':'O','deadline':'2026-06-01','value':'100K',
     'url':'https://test.com/1','source':'MERX','raw_description':'R'}
s = {'relevance_score':85,'recommendation':'PURSUE','score_rationale':'Good',
     'capability_match':['Data Engineering'],'risks':[],'estimated_effort':'M',
     'exec_summary':'Summary','suggested_angle':'Lead','decision_log':[]}
assert isinstance(save_opportunity(t, s), int)
assert is_duplicate('https://test.com/1')
assert has_score('https://test.com/1')
print('database: PASS')
"

# FilterAgent
python3 -c "
from src.agents.filter_agent import FilterAgent
state = {'listings':[{'title':'T','org':'O','raw_description':'Data analytics',
         'url':'https://test.com/2','source':'MERX','deadline':'2026-06-01','value':'500K'}],
         'filtered':[],'skipped':[]}
result = FilterAgent().run(state)
assert 'filtered' in result and 'skipped' in result
print('filter: PASS')
"

# Full pipeline dry run
DRY_RUN=true python3 main.py
```

**Per-module required assertions:**

| Module | Key Assertions |
|--------|---------------|
| `database.py` | `save_opportunity` returns int; `is_duplicate` returns True after save |
| `scraper.py` | All 7 listing keys present; returns list on failure (not raises) |
| `filter_agent.py` | `filtered` + `skipped` keys populated; sum equals input count |
| `scoring_agent.py` | All 8 scored keys present; `relevance_score` is int 0–100 |
| `scoring_critic.py` | `validated` key populated; `decision_log` is list |
| `contact_sourcer.py` | Returns dict with `contacts` key; max 3 contacts |
| `digest_agent.py` | `send_digest` returns bool; HTML contains digest subject line |

---

## Risks / Considerations

- **Fixture schema drift:** After any change to scored output schema, update `tests/fixtures/sample_scored.json` before running tests.
- **`DRY_RUN` not set:** Running smoke tests without `DRY_RUN=true` makes live API calls, incurs cost, and may modify production DB. Confirm env before running.
