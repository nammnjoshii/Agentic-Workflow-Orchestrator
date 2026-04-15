---
module: agent/orchestrator
purpose: Define OpportunityOrchestrator class contract, state machine, agent interface, and failure behaviour
dependencies: src/opportunity_orchestrator.py, src/database.py
last_updated: 2026-02-28
---

## Purpose

`src/opportunity_orchestrator.py` owns all sequencing logic. It calls each agent in order, enforces per-agent timeouts, accumulates errors without halting, and returns a complete final state dict.

---

## Scope

- Covers `OpportunityOrchestrator` class and `run_with_timeout()` helper only.
- Excludes: individual agent logic, DB writes, email delivery.
- `main.py` instantiates and calls `OpportunityOrchestrator` — it contains no orchestration logic itself.

---

## Key Decisions

- **State is a plain dict passed by reference.** Each agent reads its designated input key and writes its output key. No agent deletes or overwrites keys set by a prior agent.
- **Stop signal:** Any agent may set `state['stop'] = True` to halt remaining agents (e.g., zero new listings found). The pipeline returns current state immediately.
- **Per-agent timeout:** `run_with_timeout(agent, state, seconds=30)` wraps every `agent.run()` call with `signal.alarm`. On `AgentTimeout`, state is returned unchanged and `state['errors']` is appended.
- **Non-fatal failures:** Exceptions inside an agent are caught at the pipeline level, logged, and execution continues with the next agent.

---

## Constraints

- `Pipeline.__init__` accepts only agent instances — never imports agent classes directly.
- `signal.SIGALRM` is Linux/macOS only. GitHub Actions (Ubuntu) is compatible. Windows local dev must use `DRY_RUN=true`.
- Log prefix for all orchestrator-level messages: `[ORCHESTRATOR]`.
- `state['errors']` and `state['timings']` are reserved keys — no agent may write to them.

---

## Interfaces / Dependencies

```python
class OpportunityOrchestrator:
    def __init__(self, agents: list[Any]) -> None
    def run(self, initial_state: dict) -> dict

def run_with_timeout(agent: Any, state: dict, seconds: int = 30) -> dict
```

**Orchestrator-owned state keys:**
- `state['errors']` — list of `{agent, error, timestamp}`
- `state['timings']` — list of `{agent, duration_ms}`

**Agent interface (all agents must implement):**
```python
def run(self, state: dict) -> dict
```

---

## Risks / Considerations

- **Signal safety:** `signal.alarm` is not thread-safe. Do not introduce `ThreadPoolExecutor` inside individual agent `run()` methods.
- **Mutable state aliasing:** Agents that append to a shared list rather than their designated key risk corrupting state for downstream agents.
- **Empty pipeline:** `Pipeline([]).run(state)` returns `initial_state` unchanged — valid, not an error condition.
- **Timeout tuning:** If a new source requires fetches exceeding 30 seconds, raise `AGENT_TIMEOUT_SECONDS` via env var rather than editing source code.
