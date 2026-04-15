# ADR-001: Sequential Agent Pipeline over Parallel/Async

**Date:** 2025-12
**Status:** Accepted

## Context

The pipeline runs 7 execution agents across scraping (Playwright), LLM calls, external
APIs (SerpAPI, Hunter.io), and email delivery. Each agent has unpredictable latency and
can fail independently.

## Decision

Agents run sequentially. Each agent receives the full `ExecutionState` from the previous
agent and returns an updated state.

## Rationale

1. **Timeout enforcement:** Python's `signal.alarm` cannot reliably interrupt Playwright
   C-extensions or blocking I/O inside async event loops. Sequential execution makes
   per-agent timeouts work correctly.
2. **Debugging clarity:** A sequential stack trace identifies which agent failed with
   zero ambiguity. Parallel failure traces require correlation logic.
3. **Cost control:** LLM agents run on filtered data from the previous stage. Parallel
   execution would risk sending unfiltered listings to the expensive deep-score model.
4. **State integrity:** No shared mutable state between concurrent agents. The dict
   contract is safe and auditable.

## Tradeoff

Total wall time is the sum of all agent execution times (~8–12 minutes for 40 raw
listings). Acceptable given the twice-weekly schedule and 30-second per-agent timeout.

## Rejected Alternative

`asyncio` pipeline. Rejected because `signal.alarm` is incompatible with event loops
and Playwright's Chromium extension does not yield to the event loop reliably under load.
