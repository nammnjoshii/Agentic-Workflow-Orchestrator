# Testing Strategy — Agentic Workflow Orchestrator

## Overview

197 tests covering all execution agents, database operations, pipeline integration,
contact validation, and scoring logic. All tests use fixtures — no live API calls,
no database writes to production.

## Test Files

| File | Coverage |
|---|---|
| `tests/test_agents.py` | All 7 execution agents with DRY_RUN fixtures |
| `tests/test_database.py` | CRUD, deduplication, digest query, mark_sent |
| `tests/test_pipeline.py` | End-to-end orchestration, state threading, failure isolation |
| `tests/test_contact_critic.py` | Contact relevance scoring (4-component model) |
| `tests/test_extraction.py` | 8-step RFP content extraction |
| `tests/test_scoring_priority.py` | Priority score calculation (7 components) |
| `tests/test_contact_relevance.py` | Weighted contact seniority/domain scoring |

## Running Tests

```bash
PYTHONPATH=. DRY_RUN=true python3 -m pytest tests/ -v
```

## Calibration and Drift Detection

`tests/fixtures/calibration_set.json` — 10-case golden scoring set. The
`ScoringAssuranceAnalyst` validates deep-score output against this set on every run.

If scoring output falls outside the calibrated range, the agent logs a drift warning
to `state['errors']` and rescores up to 2 times before accepting the result.

This gives the system automatic regression detection without a separate monitoring layer.

## No Live API Calls

All tests use `DRY_RUN=true` mode. Agents return fixture data rather than calling
external APIs. This enforces zero cost for test runs and deterministic output for CI.

## Test Design Principles

- Test behavior, not implementation: tests assert on state keys and values, not on
  internal agent methods
- Failure isolation: each agent is tested independently with known input state
- Database tests use an in-memory SQLite instance via tmp_path fixture, not the production file
