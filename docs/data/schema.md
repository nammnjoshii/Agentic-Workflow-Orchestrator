---
module: data/schema
purpose: Define all database table schemas, column types, constraints, and access patterns
dependencies: src/database.py
last_updated: 2026-02-28
---

## Purpose

Single source of truth for all SQLite table definitions. Any change to column names, types, or constraints must be reflected here before editing `src/database.py`.

---

## Scope

- Covers three tables: `opportunities`, `contacts`, `pipeline_runs`.
- Excludes: ORM usage (prohibited), migration tooling (not used — schema is append-only by convention).
- DB file path: loaded from `DB_PATH` env var, defaulting to `data/opportunities.db`.

---

## Key Decisions

- **No ORM.** Raw `sqlite3` only. SQLAlchemy adds dependency weight and obscures query behaviour.
- **List fields as JSON strings.** `capability_match`, `risks`, `decision_log` stored as `TEXT`. Use `json.dumps()` / `json.loads()`. Never `str()` or `eval()`.
- **`sent_in_digest` default 0.** DigestAgent sets to 1 post-send. Sole digest deduplication mechanism.
- **Parameterised queries only.** f-strings and `.format()` in SQL are prohibited.

---

## Constraints

- All DB access through `src/database.py` functions only. No module imports `sqlite3` directly.
- `conn.close()` must be called in a `finally` block or context manager in every function.
- Schema changes require a new `init_db()` that adds columns via `ALTER TABLE IF NOT EXISTS` — never drop and recreate in production.

---

## Interfaces / Dependencies

**opportunities table:**
```sql
CREATE TABLE IF NOT EXISTS opportunities (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  scraped_at        TEXT    NOT NULL,
  title             TEXT    NOT NULL,
  org               TEXT    NOT NULL,
  deadline          TEXT,
  value             TEXT,
  url               TEXT    UNIQUE NOT NULL,
  source            TEXT    NOT NULL,
  raw_description   TEXT,
  relevance_score   INTEGER,
  recommendation    TEXT,
  score_rationale   TEXT,
  capability_match  TEXT,   -- JSON array
  risks             TEXT,   -- JSON array
  estimated_effort  TEXT,
  exec_summary      TEXT,
  suggested_angle   TEXT,
  decision_log      TEXT,   -- JSON array of {agent, decision, ms}
  sent_in_digest    INTEGER DEFAULT 0
);
```

**contacts table:**
```sql
CREATE TABLE IF NOT EXISTS contacts (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  opportunity_id   INTEGER NOT NULL REFERENCES opportunities(id),
  name             TEXT    NOT NULL,
  title            TEXT,
  linkedin_url     TEXT,
  email            TEXT,
  outreach_opening TEXT,
  source           TEXT
);
```

**pipeline_runs table:**
```sql
CREATE TABLE IF NOT EXISTS pipeline_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at        TEXT    NOT NULL,
  phase         TEXT    NOT NULL,
  status        TEXT    NOT NULL,  -- OK | PARTIAL | FAILED
  listings_in   INTEGER DEFAULT 0,
  listings_out  INTEGER DEFAULT 0,
  errors        TEXT,              -- JSON array
  duration_ms   INTEGER,
  completed_at  TEXT
);
```

---

## Risks / Considerations

- **SQLite locking:** Concurrent writes cause `database is locked`. GitHub Actions serialises jobs — that is the safeguard. Never run two local pipeline instances simultaneously.
- **URL uniqueness:** Use `INSERT OR IGNORE` when saving opportunities to handle re-scrape of known URLs.
