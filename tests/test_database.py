"""Tests for src/database.py — all assertions per docs/quality/testing.md"""
import os
import pytest


# ---------------------------------------------------------------------------
# Fixture: isolated in-memory-style DB via temp file
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite file so tests are fully isolated."""
    db_file = str(tmp_path / "test.db")
    monkeypatch.setenv("DB_PATH", db_file)
    import importlib, src.database as db
    importlib.reload(db)
    db.init_db()
    yield db


# ---------------------------------------------------------------------------
# Fixtures data
# ---------------------------------------------------------------------------

LISTING = {
    "title": "T", "org": "O", "deadline": "2026-06-01",
    "value": "100K", "url": "https://test.com/1",
    "source": "MERX", "raw_description": "R",
}
SCORED = {
    "relevance_score": 85, "recommendation": "PURSUE",
    "score_rationale": "Good", "capability_match": ["Data Engineering"],
    "risks": [], "estimated_effort": "M",
    "exec_summary": "Summary", "suggested_angle": "Lead",
    "decision_log": [],
}


# ---------------------------------------------------------------------------
# save_opportunity
# ---------------------------------------------------------------------------

def test_save_opportunity_returns_int(isolated_db):
    result = isolated_db.save_opportunity(LISTING, SCORED)
    assert isinstance(result, int)


def test_save_opportunity_idempotent(isolated_db):
    id1 = isolated_db.save_opportunity(LISTING, SCORED)
    id2 = isolated_db.save_opportunity(LISTING, SCORED)
    assert id1 == id2


# ---------------------------------------------------------------------------
# is_duplicate
# ---------------------------------------------------------------------------

def test_is_duplicate_true_after_save(isolated_db):
    isolated_db.save_opportunity(LISTING, SCORED)
    assert isolated_db.is_duplicate("https://test.com/1") is True


def test_is_duplicate_false_for_unknown(isolated_db):
    assert isolated_db.is_duplicate("https://unknown.example.com") is False


# ---------------------------------------------------------------------------
# has_score
# ---------------------------------------------------------------------------

def test_has_score_true_after_save(isolated_db):
    isolated_db.save_opportunity(LISTING, SCORED)
    assert isolated_db.has_score("https://test.com/1") is True


def test_has_score_false_for_unknown(isolated_db):
    assert isolated_db.has_score("https://unknown.example.com") is False


# ---------------------------------------------------------------------------
# save_contacts / get_contacts_for_opportunity
# ---------------------------------------------------------------------------

def test_save_and_retrieve_contacts(isolated_db):
    opp_id = isolated_db.save_opportunity(LISTING, SCORED)
    contacts = [
        {"name": "Alice", "title": "Dir", "email": "a@b.com",
         "linkedin_url": None, "outreach_opening": "Hi", "source": "Hunter"},
    ]
    isolated_db.save_contacts(opp_id, contacts)
    retrieved = isolated_db.get_contacts_for_opportunity(opp_id)
    assert len(retrieved) == 1
    assert retrieved[0]["name"] == "Alice"
    assert retrieved[0]["outreach_opening"] == "Hi"


# ---------------------------------------------------------------------------
# get_opportunities_for_digest / mark_sent
# ---------------------------------------------------------------------------

def test_get_opportunities_for_digest_returns_unsent(isolated_db):
    isolated_db.save_opportunity(LISTING, SCORED)
    rows = isolated_db.get_opportunities_for_digest()
    assert len(rows) == 1
    assert rows[0]["recommendation"] == "PURSUE"


def test_mark_sent_removes_from_digest(isolated_db):
    opp_id = isolated_db.save_opportunity(LISTING, SCORED)
    isolated_db.mark_sent([opp_id])
    assert isolated_db.get_opportunities_for_digest() == []


def test_get_opportunities_excludes_skip(isolated_db):
    skip_listing = {**LISTING, "url": "https://test.com/skip"}
    isolated_db.save_opportunity(skip_listing, {**SCORED, "recommendation": "SKIP"})
    assert isolated_db.get_opportunities_for_digest() == []


def test_get_opportunities_sorted_by_score(isolated_db):
    isolated_db.save_opportunity({**LISTING, "url": "https://test.com/high"},
                                  {**SCORED, "relevance_score": 90})
    isolated_db.save_opportunity({**LISTING, "url": "https://test.com/low"},
                                  {**SCORED, "relevance_score": 60})
    rows = isolated_db.get_opportunities_for_digest()
    assert rows[0]["relevance_score"] >= rows[1]["relevance_score"]


# ---------------------------------------------------------------------------
# log_pipeline_run
# ---------------------------------------------------------------------------

def test_log_pipeline_run_does_not_raise(isolated_db):
    isolated_db.log_pipeline_run("SCRAPE", "success", 10, 5, [], 8.42)


# ---------------------------------------------------------------------------
# filter_new_urls
# ---------------------------------------------------------------------------

def test_filter_new_urls_excludes_existing(isolated_db):
    isolated_db.save_opportunity(LISTING, SCORED)
    result = isolated_db.filter_new_urls(["https://test.com/1", "https://new.example.com/99"])
    assert result == ["https://new.example.com/99"]


def test_filter_new_urls_empty_input(isolated_db):
    assert isolated_db.filter_new_urls([]) == []


def test_filter_new_urls_all_new(isolated_db):
    result = isolated_db.filter_new_urls(["https://a.com", "https://b.com"])
    assert result == ["https://a.com", "https://b.com"]


def test_filter_new_urls_preserves_order(isolated_db):
    isolated_db.save_opportunity({**LISTING, "url": "https://test.com/2"}, SCORED)
    urls = ["https://test.com/2", "https://z.com", "https://a.com"]
    result = isolated_db.filter_new_urls(urls)
    assert result == ["https://z.com", "https://a.com"]


# ---------------------------------------------------------------------------
# get_filter_result / save_filter_result
# ---------------------------------------------------------------------------

def test_get_filter_result_none_for_unknown(isolated_db):
    assert isolated_db.get_filter_result("https://unknown.example.com") is None


def test_save_and_get_filter_result(isolated_db):
    isolated_db.save_filter_result(LISTING["url"], LISTING, 42)
    assert isolated_db.get_filter_result(LISTING["url"]) == 42


def test_save_filter_result_does_not_overwrite_full_score(isolated_db):
    """Listings already Sonnet-scored must retain their full score after filter cache write."""
    isolated_db.save_opportunity(LISTING, SCORED)
    isolated_db.save_filter_result(LISTING["url"], LISTING, 42)
    assert isolated_db.has_score(LISTING["url"]) is True


def test_save_filter_result_backfills_on_existing_url(isolated_db):
    """If URL exists with no filter_score, backfill it."""
    isolated_db.save_opportunity(LISTING, {**SCORED, "relevance_score": None, "recommendation": None})
    isolated_db.save_filter_result(LISTING["url"], LISTING, 55)
    assert isolated_db.get_filter_result(LISTING["url"]) == 55


# ---------------------------------------------------------------------------
# filter_hash_duplicates
# ---------------------------------------------------------------------------

def test_filter_hash_duplicates_passes_new_listing(isolated_db):
    result = isolated_db.filter_hash_duplicates([LISTING])
    assert len(result) == 1
    assert "content_hash" in result[0]


def test_filter_hash_duplicates_attaches_hash(isolated_db):
    result = isolated_db.filter_hash_duplicates([LISTING])
    assert isinstance(result[0]["content_hash"], str)
    assert len(result[0]["content_hash"]) == 16


def test_filter_hash_duplicates_excludes_content_match(isolated_db):
    """Same title/org/deadline from a different URL should be deduped."""
    result = isolated_db.filter_hash_duplicates([LISTING])
    isolated_db.save_opportunity(result[0], SCORED)

    dup = {**LISTING, "url": "https://other-portal.com/999", "source": "OtherPortal"}
    result2 = isolated_db.filter_hash_duplicates([dup])
    assert len(result2) == 0


def test_filter_hash_duplicates_allows_different_content(isolated_db):
    result = isolated_db.filter_hash_duplicates([LISTING])
    isolated_db.save_opportunity(result[0], SCORED)

    different = {
        **LISTING,
        "url": "https://other-portal.com/888",
        "title": "Machine Learning Infrastructure Project",
        "org": "Province of Ontario",
    }
    result2 = isolated_db.filter_hash_duplicates([different])
    assert len(result2) == 1


def test_filter_hash_duplicates_collapses_within_batch(isolated_db):
    """Two listings in the same batch with identical content: only first survives."""
    dup1 = {**LISTING, "url": "https://portal-a.com/1", "source": "PortalA"}
    dup2 = {**LISTING, "url": "https://portal-b.com/2", "source": "PortalB"}
    result = isolated_db.filter_hash_duplicates([dup1, dup2])
    assert len(result) == 1
    assert result[0]["url"] == "https://portal-a.com/1"


def test_filter_hash_duplicates_empty_input(isolated_db):
    assert isolated_db.filter_hash_duplicates([]) == []


# ---------------------------------------------------------------------------
# log_pipeline_run — new delivery fields
# ---------------------------------------------------------------------------

def test_log_pipeline_run_basic(isolated_db):
    """log_pipeline_run inserts a row with correct phase, status, and duration_secs."""
    import sqlite3, os
    isolated_db.log_pipeline_run("OpportunityQualificationSpecialist", "ok", 10, 6, [], 12.3)
    db_path = os.environ["DB_PATH"]
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT phase, status, listings_in, listings_out, duration_secs FROM pipeline_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row[0] == "OpportunityQualificationSpecialist"
    assert row[1] == "ok"
    assert row[2] == 10
    assert row[3] == 6
    assert abs(row[4] - 12.3) < 0.001


def test_log_pipeline_run_tokens_and_validity(isolated_db):
    """tokens_in, tokens_out, and output_validity_rate persist correctly."""
    import sqlite3, os
    isolated_db.log_pipeline_run(
        "StrategicScoringAgent", "ok", 18, 18, [], 41.2,
        tokens_in=8500, tokens_out=1200, output_validity_rate=0.944,
    )
    db_path = os.environ["DB_PATH"]
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT tokens_in, tokens_out, output_validity_rate "
        "FROM pipeline_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row[0] == 8500
    assert row[1] == 1200
    assert abs(row[2] - 0.944) < 0.001


def test_log_pipeline_run_with_delivery_fields(isolated_db):
    """Digest delivery fields (email_sent_at, delivery_status, resend_message_id) persist correctly."""
    import sqlite3, os
    isolated_db.log_pipeline_run(
        "DIGEST", "ok", 5, 5, [], 4.1,
        email_sent_at="2026-03-07T15:00:00Z",
        delivery_status="sent",
        resend_message_id="msg_abc123",
    )
    db_path = os.environ["DB_PATH"]
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT delivery_status, resend_message_id, email_sent_at "
        "FROM pipeline_runs WHERE phase='DIGEST' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row[0] == "sent"
    assert row[1] == "msg_abc123"
    assert row[2] == "2026-03-07T15:00:00Z"


def test_log_pipeline_run_dry_run_status(isolated_db):
    """delivery_status='dry_run' is stored correctly for dry-run digest rows."""
    import sqlite3, os
    isolated_db.log_pipeline_run(
        "DIGEST", "dry_run", 3, 3, [], 0.8,
        delivery_status="dry_run",
    )
    db_path = os.environ["DB_PATH"]
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT delivery_status, resend_message_id FROM pipeline_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row[0] == "dry_run"
    assert row[1] is None


# ---------------------------------------------------------------------------
# clear_source_data
# ---------------------------------------------------------------------------

def test_clear_source_data_removes_only_target_source(isolated_db):
    """clear_source_data('BCBid') removes BCBid rows but keeps other sources."""
    import sqlite3, os
    isolated_db.save_opportunity({**LISTING, "url": "https://bcbid.test/1", "source": "BCBid"}, SCORED)
    isolated_db.save_opportunity({**LISTING, "url": "https://merx.test/1", "source": "MERX"}, SCORED)
    isolated_db.clear_source_data("BCBid")
    conn = sqlite3.connect(os.environ["DB_PATH"])
    rows = conn.execute("SELECT source FROM opportunities").fetchall()
    conn.close()
    assert all(r[0] != "BCBid" for r in rows)
    assert any(r[0] == "MERX" for r in rows)


def test_clear_source_data_removes_linked_contacts(isolated_db):
    """Contacts for deleted BCBid opportunities are also removed."""
    opp_id = isolated_db.save_opportunity(
        {**LISTING, "url": "https://bcbid.test/2", "source": "BCBid"}, SCORED
    )
    isolated_db.save_contacts(opp_id, [{
        "name": "Bob", "title": "Dir", "email": "b@c.com",
        "linkedin_url": None, "outreach_opening": "Hi",
        "source": "Hunter", "relevance_score": 75,
    }])
    isolated_db.clear_source_data("BCBid")
    assert isolated_db.get_contacts_for_opportunity(opp_id) == []


def test_clear_source_data_noop_on_missing_source(isolated_db):
    """clear_source_data with a source not in DB must not raise."""
    isolated_db.clear_source_data("NonExistentPortal")
