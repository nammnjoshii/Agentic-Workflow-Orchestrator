import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", "data/opportunities.db")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _connect()
    try:
        conn.executescript("""
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
                capability_match  TEXT,
                risks             TEXT,
                estimated_effort  TEXT,
                exec_summary      TEXT,
                suggested_angle   TEXT,
                decision_log               TEXT,
                opportunity_priority_score INTEGER,
                sent_in_digest             INTEGER DEFAULT 0
            );

            -- Migration: add column if upgrading from a pre-existing DB
            -- SQLite ignores ALTER TABLE errors for already-existing columns via executescript
            CREATE TABLE IF NOT EXISTS contacts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id   INTEGER NOT NULL REFERENCES opportunities(id),
                name             TEXT    NOT NULL,
                title            TEXT,
                linkedin_url     TEXT,
                email            TEXT,
                outreach_opening TEXT,
                source           TEXT,
                relevance_score  INTEGER
            );

            CREATE TABLE IF NOT EXISTS raw_listings (
                url             TEXT PRIMARY KEY,
                title           TEXT,
                org             TEXT,
                deadline        TEXT,
                value           TEXT,
                source          TEXT,
                raw_description TEXT,
                scraped_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at               TEXT    NOT NULL,
                phase                TEXT    NOT NULL,
                status               TEXT    NOT NULL,
                listings_in          INTEGER DEFAULT 0,
                listings_out         INTEGER DEFAULT 0,
                errors               TEXT,
                duration_secs        REAL,
                completed_at         TEXT,
                tokens_in            INTEGER,
                tokens_out           INTEGER,
                output_validity_rate REAL
            );
        """)
        conn.commit()
        # Migrate existing DBs: add columns if absent (safe to run repeatedly)
        for _ddl in [
            "ALTER TABLE opportunities ADD COLUMN opportunity_priority_score INTEGER",
            "ALTER TABLE opportunities ADD COLUMN filter_score INTEGER",
            "ALTER TABLE opportunities ADD COLUMN filter_scored_at TEXT",
            "ALTER TABLE opportunities ADD COLUMN content_hash TEXT",
            "ALTER TABLE pipeline_runs ADD COLUMN email_sent_at TEXT",
            "ALTER TABLE pipeline_runs ADD COLUMN delivery_status TEXT",
            "ALTER TABLE pipeline_runs ADD COLUMN resend_message_id TEXT",
            "ALTER TABLE pipeline_runs ADD COLUMN duration_secs REAL",
            "ALTER TABLE pipeline_runs ADD COLUMN tokens_in INTEGER",
            "ALTER TABLE pipeline_runs ADD COLUMN tokens_out INTEGER",
            "ALTER TABLE pipeline_runs ADD COLUMN output_validity_rate REAL",
            "ALTER TABLE contacts ADD COLUMN relevance_score INTEGER",
        ]:
            try:
                conn.execute(_ddl)
                conn.commit()
            except Exception:
                pass  # Column already exists — safe to ignore

        # Index for cross-source dedup lookups
        try:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_content_hash ON opportunities(content_hash)"
            )
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()


def is_duplicate(url):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM opportunities WHERE url = ?", (url,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def filter_new_urls(urls):
    """Return only URLs from the input list not already in the DB.

    Single connection + single IN-clause query instead of N individual lookups.
    Preserves original order. Safe for up to ~900 URLs (SQLite IN limit is 999).
    """
    if not urls:
        return []
    conn = _connect()
    try:
        placeholders = ",".join("?" for _ in urls)
        rows = conn.execute(
            "SELECT url FROM opportunities WHERE url IN (" + placeholders + ")",
            urls,
        ).fetchall()
        existing = {row[0] for row in rows}
        return [u for u in urls if u not in existing]
    finally:
        conn.close()


def has_score(url):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT relevance_score FROM opportunities WHERE url = ?", (url,)
        ).fetchone()
        return row is not None and row[0] is not None
    finally:
        conn.close()


def get_filter_result(url):
    """Return the cached Haiku filter_score for a URL, or None if not yet evaluated."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT filter_score FROM opportunities WHERE url = ?", (url,)
        ).fetchone()
        return row[0] if row is not None else None
    finally:
        conn.close()


def save_filter_result(url, listing, score):
    """Persist Haiku filter score for a listing (pass or fail).

    Uses INSERT OR IGNORE so already-scored opportunities are not overwritten.
    If URL already exists with no filter_score, backfills filter_score only.
    """
    conn = _connect()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT OR IGNORE INTO opportunities
                (scraped_at, title, org, deadline, value, url, source,
                 raw_description, filter_score, filter_scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                listing["title"],
                listing["org"],
                listing.get("deadline"),
                listing.get("value"),
                listing["url"],
                listing["source"],
                listing.get("raw_description"),
                score,
                now,
            ),
        )
        # Backfill filter_score on existing rows that don't have it yet
        conn.execute(
            """
            UPDATE opportunities
               SET filter_score = ?, filter_scored_at = ?
             WHERE url = ? AND filter_score IS NULL
            """,
            (score, now, url),
        )
        conn.commit()
    finally:
        conn.close()


def filter_hash_duplicates(listings):
    """Return only listings whose content_hash is not already in the DB.

    Computes a deterministic 16-char hex hash from (normalized_title, org, deadline).
    Attaches the hash to each returned listing dict as 'content_hash'.
    Listings that are within-batch duplicates of each other are also collapsed
    (first occurrence wins).
    """
    import hashlib
    import re as _re

    if not listings:
        return listings

    def _hash(listing):
        title = _re.sub(r"\W+", " ", (listing.get("title") or "")).lower().strip()
        org = _re.sub(r"\W+", " ", (listing.get("org") or "")).lower().strip()
        deadline = (listing.get("deadline") or "").strip()
        return hashlib.sha256(
            (title + "|" + org + "|" + deadline).encode()
        ).hexdigest()[:16]

    hashes = [_hash(l) for l in listings]

    conn = _connect()
    try:
        placeholders = ",".join("?" for _ in hashes)
        rows = conn.execute(
            "SELECT content_hash FROM opportunities WHERE content_hash IN ("
            + placeholders
            + ")",
            hashes,
        ).fetchall()
        existing_hashes = {row[0] for row in rows}
    finally:
        conn.close()

    new_listings = []
    seen = set()
    for listing, h in zip(listings, hashes):
        if h not in existing_hashes and h not in seen:
            listing["content_hash"] = h
            new_listings.append(listing)
            seen.add(h)

    return new_listings


def save_opportunity(listing, scored):
    """Upsert a scored opportunity. Returns the row id (new or existing).

    Uses INSERT OR IGNORE to create the row if it doesn't exist, then always
    UPDATE to write scored fields — this handles the case where save_filter_result()
    already inserted the URL with recommendation=NULL (the row would be silently
    skipped by INSERT OR IGNORE alone, leaving recommendation forever NULL).
    """
    conn = _connect()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT OR IGNORE INTO opportunities (
                scraped_at, title, org, deadline, value, url, source,
                raw_description, relevance_score, recommendation,
                score_rationale, capability_match, risks,
                estimated_effort, exec_summary, suggested_angle, decision_log,
                opportunity_priority_score, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                listing["title"],
                listing["org"],
                listing.get("deadline"),
                listing.get("value"),
                listing["url"],
                listing["source"],
                listing.get("raw_description"),
                scored.get("relevance_score"),
                scored.get("recommendation"),
                scored.get("score_rationale"),
                json.dumps(scored.get("capability_match", [])),
                json.dumps(scored.get("risks", [])),
                scored.get("estimated_effort"),
                scored.get("exec_summary"),
                scored.get("suggested_angle"),
                json.dumps(scored.get("decision_log", [])),
                scored.get("opportunity_priority_score"),
                listing.get("content_hash"),
            ),
        )
        # Always write scored fields — handles pre-inserted rows from save_filter_result().
        # Reset sent_in_digest if content_hash changed (RFP was updated since last send).
        new_hash = listing.get("content_hash")
        conn.execute(
            """
            UPDATE opportunities
               SET relevance_score          = ?,
                   recommendation           = ?,
                   score_rationale          = ?,
                   capability_match         = ?,
                   risks                    = ?,
                   estimated_effort         = ?,
                   exec_summary             = ?,
                   suggested_angle          = ?,
                   decision_log             = ?,
                   opportunity_priority_score = ?,
                   content_hash             = ?,
                   sent_in_digest           = CASE
                       WHEN ? IS NOT NULL AND content_hash IS NOT NULL AND ? != content_hash
                       THEN 0
                       ELSE sent_in_digest
                   END
             WHERE url = ?
            """,
            (
                scored.get("relevance_score"),
                scored.get("recommendation"),
                scored.get("score_rationale"),
                json.dumps(scored.get("capability_match", [])),
                json.dumps(scored.get("risks", [])),
                scored.get("estimated_effort"),
                scored.get("exec_summary"),
                scored.get("suggested_angle"),
                json.dumps(scored.get("decision_log", [])),
                scored.get("opportunity_priority_score"),
                new_hash,
                new_hash,  # CASE WHEN arg 1
                new_hash,  # CASE WHEN arg 2
                listing["url"],
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM opportunities WHERE url = ?", (listing["url"],)
        ).fetchone()
        return row[0]
    finally:
        conn.close()


def save_contacts(opp_id, contacts):
    """Insert a list of contact dicts for the given opportunity id."""
    if not contacts:
        return
    conn = _connect()
    try:
        rows = [
            (
                opp_id,
                c["name"],
                c.get("title"),
                c.get("linkedin_url"),
                c.get("email"),
                c.get("outreach_opening"),
                c.get("source"),
                c.get("relevance_score"),
            )
            for c in contacts
        ]
        conn.executemany(
            """
            INSERT INTO contacts
                (opportunity_id, name, title, linkedin_url, email, outreach_opening, source,
                 relevance_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def get_scored_opportunity(url):
    """Return the 9 scored fields for a single URL, or None if not found."""
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT relevance_score, recommendation, score_rationale,
                      capability_match, risks, estimated_effort,
                      exec_summary, suggested_angle, decision_log,
                      opportunity_priority_score
               FROM opportunities WHERE url = ?""",
            (url,),
        ).fetchone()
        if row is None:
            return None
        keys = ["relevance_score", "recommendation", "score_rationale",
                "capability_match", "risks", "estimated_effort",
                "exec_summary", "suggested_angle", "decision_log",
                "opportunity_priority_score"]
        d = dict(zip(keys, row))
        for field in ("capability_match", "risks", "decision_log"):
            d[field] = json.loads(d[field]) if d[field] else []
        return d
    finally:
        conn.close()


def get_opportunities_for_digest():
    """Return unsent PURSUE and CONSIDER rows, ordered by score descending."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, title, org, deadline, value, url, source,
                   relevance_score, recommendation, score_rationale,
                   capability_match, risks, estimated_effort,
                   exec_summary, suggested_angle, decision_log,
                   opportunity_priority_score
            FROM opportunities
            WHERE sent_in_digest = 0
              AND recommendation IN ('PURSUE', 'CONSIDER')
            ORDER BY opportunity_priority_score DESC, relevance_score DESC
            """
        ).fetchall()
        cols = [
            "id", "title", "org", "deadline", "value", "url", "source",
            "relevance_score", "recommendation", "score_rationale",
            "capability_match", "risks", "estimated_effort",
            "exec_summary", "suggested_angle", "decision_log",
            "opportunity_priority_score",
        ]
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            for field in ("capability_match", "risks", "decision_log"):
                d[field] = json.loads(d[field]) if d[field] else []
            result.append(d)
        return result
    finally:
        conn.close()


def get_all_pursue_consider(skip_orgs=None):
    """Return ALL PURSUE/CONSIDER rows regardless of sent_in_digest.

    Used for force-send digest runs. skip_orgs is an optional list of org
    names to exclude (case-insensitive exact match).
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, title, org, deadline, value, url, source,
                   relevance_score, recommendation, exec_summary,
                   suggested_angle, opportunity_priority_score, capability_match
            FROM opportunities
            WHERE recommendation IN ('PURSUE', 'CONSIDER')
            ORDER BY opportunity_priority_score DESC, relevance_score DESC
            """
        ).fetchall()
        keys = (
            "id", "title", "org", "deadline", "value", "url", "source",
            "relevance_score", "recommendation", "exec_summary",
            "suggested_angle", "opportunity_priority_score", "capability_match",
        )
        results = []
        for row in rows:
            d = dict(zip(keys, row))
            d["capability_match"] = json.loads(d["capability_match"]) if d["capability_match"] else []
            results.append(d)
        if skip_orgs:
            skip_lower = {s.lower() for s in skip_orgs}
            results = [r for r in results if r["org"].lower() not in skip_lower]
        return results
    finally:
        conn.close()


def get_contacts_for_opportunity(opp_id):
    """Return all contacts for the given opportunity id, ordered by relevance."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, opportunity_id, name, title, linkedin_url,
                   email, outreach_opening, source, relevance_score
            FROM contacts
            WHERE opportunity_id = ?
            ORDER BY relevance_score DESC
            """,
            (opp_id,),
        ).fetchall()
        cols = ["id", "opportunity_id", "name", "title",
                "linkedin_url", "email", "outreach_opening", "source", "relevance_score"]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def clear_all_data():
    """Delete all contacts, opportunities, and raw_listings rows before a fresh scrape run.

    Keeps pipeline_runs intact for observability. Called at the start of
    every run_daily_scrape() so each run is fully authoritative.
    """
    conn = _connect()
    try:
        conn.execute("DELETE FROM contacts")
        conn.execute("DELETE FROM opportunities")
        conn.execute("DELETE FROM raw_listings")
        conn.commit()
    finally:
        conn.close()


def upsert_raw_listings(listings: list):
    """Bulk INSERT OR REPLACE raw scraped listings.

    Called progressively as each portal completes — persists listings to DB
    immediately so data is never lost if the pipeline times out mid-scrape.
    Uses INSERT OR REPLACE with URL PRIMARY KEY so repeated calls are idempotent.
    Thread-safe: each call opens its own connection.
    """
    if not listings:
        return
    conn = _connect()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO raw_listings "
            "(url, title, org, deadline, value, source, raw_description, scraped_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            [
                (
                    l.get("url", ""), l.get("title", ""), l.get("org", ""),
                    l.get("deadline", ""), l.get("value", ""), l.get("source", ""),
                    l.get("raw_description", ""),
                )
                for l in listings
            ],
        )
        conn.commit()
    finally:
        conn.close()


def get_raw_listings() -> list:
    """Return all raw_listings rows as dicts.

    Used as fallback by OpportunityQualificationSpecialist when state['listings']
    is empty — recovers data from a prior run that timed out mid-scrape.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT url, title, org, deadline, value, source, raw_description "
            "FROM raw_listings"
        ).fetchall()
        keys = ("url", "title", "org", "deadline", "value", "source", "raw_description")
        return [dict(zip(keys, r)) for r in rows]
    finally:
        conn.close()


def clear_raw_listings():
    """Wipe raw_listings — called by clear_all_data() at start of each fresh run."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM raw_listings")
        conn.commit()
    finally:
        conn.close()


def count_raw_listings() -> int:
    """Return count of rows in raw_listings — used by the progress reporter thread."""
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM raw_listings").fetchone()[0]
    finally:
        conn.close()


def clear_source_data(source):
    """Delete all contacts and opportunities for a single named source.

    Used by run_bcbid_scrape() to wipe stale BCBid rows before re-scraping
    without touching opportunities from other portals.
    Contacts deleted first to respect FK constraint. pipeline_runs preserved.
    """
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM contacts WHERE opportunity_id IN "
            "(SELECT id FROM opportunities WHERE source = ?)",
            (source,),
        )
        conn.execute("DELETE FROM opportunities WHERE source = ?", (source,))
        conn.commit()
    finally:
        conn.close()


def mark_sent(ids):
    """Set sent_in_digest=1 for a list of opportunity ids."""
    if not ids:
        return
    conn = _connect()
    try:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            "UPDATE opportunities SET sent_in_digest = 1 WHERE id IN (" + placeholders + ")",
            ids,
        )
        conn.commit()
    finally:
        conn.close()


def get_scrape_stats():
    """Return pipeline counts since the last sent digest (or last reset), whichever is more recent.

    Cutoff = run_at of the most recent DIGEST row with delivery_status='sent' in pipeline_runs.
    If no such row exists (DB was reset or digest has never been sent), cutoff = epoch so all
    records in the current DB are included.

    - scraped  : sum of listings_out from ProcurementIntelligenceSpecialist runs since cutoff
    - filtered : sum of listings_out from OpportunityQualificationSpecialist runs since cutoff
    - pursue / consider / skip : count of opportunities by recommendation where scraped_at > cutoff
    """
    conn = _connect()
    try:
        digest_row = conn.execute(
            """SELECT run_at FROM pipeline_runs
               WHERE phase = 'DIGEST' AND delivery_status = 'sent'
               ORDER BY run_at DESC LIMIT 1"""
        ).fetchone()
        cutoff = digest_row[0] if digest_row else "1970-01-01T00:00:00+00:00"

        scraper_row = conn.execute(
            """SELECT COALESCE(SUM(listings_out), 0) FROM pipeline_runs
               WHERE phase = 'ProcurementIntelligenceSpecialist'
                 AND run_at > ?""",
            (cutoff,),
        ).fetchone()
        filter_row = conn.execute(
            """SELECT COALESCE(SUM(listings_out), 0) FROM pipeline_runs
               WHERE phase = 'OpportunityQualificationSpecialist'
                 AND run_at > ?""",
            (cutoff,),
        ).fetchone()
        rec_rows = conn.execute(
            """SELECT recommendation, COUNT(*) FROM opportunities
               WHERE recommendation IS NOT NULL
                 AND scraped_at > ?
               GROUP BY recommendation""",
            (cutoff,),
        ).fetchall()
        rec_counts = {r[0]: r[1] for r in rec_rows}
        return {
            "scraped": scraper_row[0] if scraper_row else 0,
            "filtered": filter_row[0] if filter_row else 0,
            "pursue": rec_counts.get("PURSUE", 0),
            "consider": rec_counts.get("CONSIDER", 0),
            "skip": rec_counts.get("SKIP", 0),
        }
    finally:
        conn.close()


def log_pipeline_run(
    phase, status, listings_in, listings_out, errors, secs,
    *,
    tokens_in=None,
    tokens_out=None,
    output_validity_rate=None,
    email_sent_at=None,
    delivery_status=None,
    resend_message_id=None,
):
    """Insert a pipeline_runs record.

    secs — wall-clock duration in seconds (float, e.g. 12.34)

    Optional keyword args:
      tokens_in            — LLM prompt tokens consumed by this agent
      tokens_out           — LLM completion tokens produced by this agent
      output_validity_rate — fraction of Claude responses that met schema (0.0–1.0)
      email_sent_at        — ISO UTC timestamp when Resend call was made
      delivery_status      — "sent" | "failed" | "dry_run"
      resend_message_id    — message ID returned by Resend API
    """
    conn = _connect()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO pipeline_runs
                (run_at, phase, status, listings_in, listings_out, errors,
                 duration_secs, completed_at,
                 tokens_in, tokens_out, output_validity_rate,
                 email_sent_at, delivery_status, resend_message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                phase,
                status,
                listings_in,
                listings_out,
                json.dumps(errors) if errors else json.dumps([]),
                secs,
                now,
                tokens_in,
                tokens_out,
                output_validity_rate,
                email_sent_at,
                delivery_status,
                resend_message_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
