"""
Rescore rows that have recommendation=NULL (upsert bug survivors) and rows
that scored 0/SKIP with filter_score>=60 (false negatives from auth-wall portals).

Usage:
    python scripts/rescore_null_rows.py [--dry-run] [--limit N]

Requirements:
    ANTHROPIC_API_KEY must be set (real API calls are made).
    Run from the project root so that src/ imports resolve.

What it does:
  1. Resets the 17 BidsCanada false-negative rows (relevance_score=0,
     recommendation='SKIP', filter_score>=60) back to NULL so they get
     re-evaluated with the improved raw_description fallback.
  2. Collects all rows where recommendation IS NULL AND filter_score >= 60
     (19 lost-score rows + the reset rows from step 1).
  3. Passes each through StrategicScoringAgent._score_listing() which
     now falls back to raw_description when the URL returns sparse content.
  4. Saves results via save_opportunity().
"""
import argparse
import json
import logging
import os
import sys

# Ensure project root is on the path when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.database import _connect, save_opportunity
from src.agents.strategic_scoring_agent import StrategicScoringAgent, compute_priority_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_RESCORE_QUERY = """
    SELECT id, title, org, deadline, value, url, source, raw_description,
           filter_score, content_hash
    FROM opportunities
    WHERE recommendation IS NULL
      AND relevance_score IS NULL
      AND filter_score >= 60
    ORDER BY filter_score DESC
"""

_FALSE_NEG_QUERY = """
    SELECT id, title, org, deadline, value, url, source, raw_description,
           filter_score, content_hash
    FROM opportunities
    WHERE relevance_score = 0
      AND recommendation = 'SKIP'
      AND filter_score >= 60
    ORDER BY filter_score DESC
"""

_RESET_SQL = """
    UPDATE opportunities
       SET relevance_score = NULL,
           recommendation  = NULL,
           score_rationale = NULL,
           capability_match = NULL,
           risks = NULL,
           estimated_effort = NULL,
           exec_summary = NULL,
           suggested_angle = NULL,
           decision_log = NULL,
           opportunity_priority_score = NULL
     WHERE relevance_score = 0
       AND recommendation = 'SKIP'
       AND filter_score >= 60
"""


def _row_to_listing(row):
    return {
        "id":              row[0],
        "title":           row[1] or "",
        "org":             row[2] or "",
        "deadline":        row[3],
        "value":           row[4],
        "url":             row[5],
        "source":          row[6] or "",
        "raw_description": row[7],
        "filter_score":    row[8],
        "content_hash":    row[9],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print candidates without making API calls")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max rows to rescore (0 = all)")
    args = parser.parse_args()

    conn = _connect()
    try:
        # Step 1: identify false negatives (score=0/SKIP but filter>=60)
        false_negs = conn.execute(_FALSE_NEG_QUERY).fetchall()
        logger.info("False-negative rows to reset: %d", len(false_negs))
        for row in false_negs:
            logger.info("  [FN] %s (filter=%s)", row[1][:80], row[8])

        if not args.dry_run and false_negs:
            conn.execute(_RESET_SQL)
            conn.commit()
            logger.info("Reset %d false-negative rows to NULL", len(false_negs))

        # Step 2: collect all rescoring candidates
        candidates = conn.execute(_RESCORE_QUERY).fetchall()
    finally:
        conn.close()

    logger.info("Rescore candidates (NULL + just-reset): %d", len(candidates))
    if args.limit:
        candidates = candidates[: args.limit]
        logger.info("Limiting to first %d rows", args.limit)

    if args.dry_run:
        logger.info("DRY-RUN — listing candidates only, no API calls")
        for row in candidates:
            logger.info("  [CANDIDATE] %s | source=%s | filter=%s", row[1][:80], row[6], row[8])
        return

    analyst = StrategicScoringAgent()
    ok = 0
    failed = 0

    for row in candidates:
        listing = _row_to_listing(row)
        title = listing["title"][:80]
        try:
            scored = analyst._score_listing(listing)
            row_id = save_opportunity(listing, scored)
            logger.info(
                "[RESCORE] %s → %s %s (priority=%s) id=%s",
                title,
                scored.get("relevance_score"),
                scored.get("recommendation"),
                scored.get("opportunity_priority_score"),
                row_id,
            )
            ok += 1
        except Exception as exc:
            logger.warning("[RESCORE] failed on %s: %s", title, exc)
            failed += 1

    logger.info("Done: %d rescored, %d failed", ok, failed)


if __name__ == "__main__":
    main()
