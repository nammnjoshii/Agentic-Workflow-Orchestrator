# ADR-002: SQLite + GitHub Actions Artifact over Hosted Database

**Date:** 2025-12
**Status:** Accepted

## Context

The pipeline needs persistent storage for deduplication, digest state tracking, and
run observability. The system runs on GitHub Actions (ephemeral compute with no
persistent filesystem).

## Decision

SQLite database stored as a GitHub Actions artifact. Uploaded after each scrape run,
downloaded before each digest run.

## Rationale

1. **Zero infrastructure cost:** No hosted DB, no connection pooling, no VPC, no
   managed service.
2. **Portability:** The entire database is a single file. Trivially downloadable for
   local inspection or replay.
3. **Deduplication:** URL-unique constraint on the `opportunities` table handles dedup
   without application-level logic.
4. **Auditability:** The artifact is immutable per run. Any run's state is reproducible.

## Tradeoff

Concurrent writes are impossible. Acceptable given sequential execution. No cross-region
replication — if the artifact is lost, history is lost. Mitigated by retaining last 5
artifacts per workflow.

## Rejected Alternative

PostgreSQL (Supabase). Rejected: connection overhead, credential surface area, and
unnecessary cost and complexity for a twice-weekly batch job.
