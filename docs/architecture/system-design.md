# System Design — Agentic Workflow Orchestrator

## Problem

Government procurement portals publish hundreds of RFPs per week across fragmented
sources with no unified API. Manual review is inconsistent, error-prone, and
time-consuming. An organization operating in the public sector needs to identify
3–5 high-fit opportunities per week from a raw signal-to-noise ratio of roughly 1:40.

## Solution

A sequential 7-execution-agent pipeline that transforms raw portal listings into
decision-ready outreach packages. Each agent implements a single transformation on a
shared state dict. Failures are isolated — the pipeline never hard-stops on a single
agent failure.

## Pipeline Architecture

| Stage | Agent | Input | Output |
|---|---|---|---|
| 1. Discovery | ProcurementIntelligenceSpecialist | — | listings[] |
| 2. Pre-filter | OpportunityQualificationSpecialist | listings[] | filtered[] |
| 3. Deep Score | StrategicScoringAgent | filtered[] | scored[] |
| 4. Validation | ScoringAssuranceAnalyst | scored[] | validated[] |
| 5. Contact Discovery | StakeholderIntelligenceSpecialist | validated[] | contacts[] |
| 6. Contact Validation | StakeholderRelevanceAgent | contacts[] | enriched[] |
| 7. Outreach Generation | ExecutiveOutreachStrategist | enriched[] | ready[] |
| Delivery | IntelligenceDeliveryAgent | ready[] | digest email |

## State Management

Single `ExecutionState` TypedDict threaded through all agents. Each agent receives
the full state and returns an updated state. No shared mutable state between agents.

## Failure Model

`signal.alarm(30)` per agent. Any unhandled exception is caught by the orchestrator,
logged to `state['errors']`, and skipped. The pipeline continues to the next agent.
The digest is sent with whatever scored correctly — no silent data loss.

## Observability

Every agent phase writes a row to the `pipeline_runs` SQLite table: agent name,
start time, end time, items in, items out, status. Full execution trace is queryable
from the DB artifact.

## Data Flow

```
[12 Procurement Portals]
        │
        ▼
ProcurementIntelligenceSpecialist (Playwright + BeautifulSoup4)
        │  listings[]
        ▼
OpportunityQualificationSpecialist (pre-filter LLM, 0–100 score)
        │  filtered[]
        ▼
StrategicScoringAgent (scoring LLM, 9 structured fields)
        │  scored[]
        ▼
ScoringAssuranceAnalyst (validation + retry, max 2)
        │  validated[]
        ▼
StakeholderIntelligenceSpecialist (SerpAPI + Hunter.io)
        │  contacts[]
        ▼
StakeholderRelevanceAgent (4-component weighted scoring)
        │  enriched[]
        ▼
ExecutiveOutreachStrategist (scoring LLM, 2-sentence opener)
        │  ready[]
        ▼
[SQLite DB]  →  IntelligenceDeliveryAgent  →  [Email Digest]
```

## Design Principles

- Fail-safe over fail-fast
- Config over hardcoding
- Sequential clarity over parallel complexity
- Cost-aware AI orchestration
