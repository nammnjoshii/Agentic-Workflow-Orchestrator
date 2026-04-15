# Operating Model — Agentic Workflow Orchestrator

## Execution Cadence

| Job | Schedule | Action |
|---|---|---|
| Scrape + Score | Mon + Thu, 7 AM PT | Full 7-agent pipeline; uploads DB artifact |
| Digest Delivery | Mon, 8 AM PT | Downloads artifact; sends Intelligence Digest |

## Ownership Model

The system operates fully autonomously on schedule. Human review occurs at the
single downstream touchpoint: the weekly Intelligence Digest email. No manual
intervention is required between pipeline runs under normal operating conditions.

## Failure Handling

- Agent-level failures are logged to `state['errors']` and skipped
- No full pipeline interruption on single-agent failure
- Selective retry at the scoring validation stage (max 2 retries)
- Failed agent errors appear in the `pipeline_runs` observability table
- GitHub Actions workflow failures trigger email notification via Resend

## Observability

- Every agent phase writes a row to the `pipeline_runs` SQLite table
- Fields: agent name, start time, end time, items in, items out, status, errors
- The DB artifact is downloadable after each run for local inspection
- Run-level metrics are queryable with any SQLite client

## Human Intervention Points

Operators interact with the system at three configuration layers:

1. **Capability profile** (`docs/data/capability-profile.md`) — update when the
   organization's service offering changes
2. **Scoring threshold** (`FILTER_THRESHOLD` env var) — adjust recall/precision
   tradeoff based on volume and miss rate
3. **Outreach messaging** (via `CLIENT_NAME`/`CLIENT_DESCRIPTION`) — update when
   organizational context changes

## Scaling Considerations

The sequential pipeline scales vertically (faster machine = faster wall time). Horizontal
scaling would require partitioning the portal scraping stage and merging state before
the scoring stage — feasible but adds orchestration complexity not warranted for
current volume.

The SQLite artifact pattern is the primary concurrency constraint. For workloads
requiring real-time results or multi-operator access, replace the artifact pattern
with a hosted database and keep all other architecture unchanged.
