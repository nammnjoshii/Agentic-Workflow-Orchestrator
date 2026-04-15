import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone
from typing import Any, TypedDict

from src.database import log_pipeline_run, count_raw_listings


class ExecutionState(TypedDict, total=False):
    listings: list[dict[str, Any]]
    filtered: list[dict[str, Any]]
    scored: list[dict[str, Any]]
    validated: list[dict[str, Any]]
    contacts: list[dict[str, Any]]
    enriched: list[dict[str, Any]]
    ready: list[dict[str, Any]]
    errors: list[str]
    timings: dict[str, float]

logger = logging.getLogger(__name__)

AGENT_TIMEOUT_SECONDS = int(os.environ.get("AGENT_TIMEOUT_SECONDS", 30))

# Maps each agent class name to (input_state_key, output_state_key)
# Used to derive listings_in / listings_out for pipeline_runs logging.
_AGENT_IO = {
    "ProcurementIntelligenceSpecialist":  ("listings",  "listings"),
    "OpportunityQualificationSpecialist": ("listings",  "filtered"),
    "StrategicScoringAgent":              ("filtered",  "scored"),
    "ScoringAssuranceAnalyst":            ("scored",    "validated"),
    "StakeholderIntelligenceSpecialist":  ("validated", "contacts"),
    "StakeholderRelevanceAgent":          ("enriched",  "enriched"),
    "ExecutiveOutreachStrategist":        ("enriched",  "ready"),
}


def _log_agent(agent_name, state, in_key, out_key, duration_secs, errors):
    """Write one pipeline_runs row for a completed agent. Never raises."""
    try:
        listings_in  = len(state.get(in_key,  [])) if in_key  else 0
        listings_out = len(state.get(out_key, [])) if out_key else 0
        status = "error" if errors else "ok"
        usage = state.get("token_usage", {}).get(agent_name, {})
        log_pipeline_run(
            agent_name, status, listings_in, listings_out, errors, duration_secs,
            tokens_in=usage.get("input") or None,
            tokens_out=usage.get("output") or None,
        )
    except Exception as exc:
        logger.warning("[PIPELINE] log_pipeline_run failed for %s: %s", agent_name, exc)


class AgentTimeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise AgentTimeout()


def run_with_timeout(agent, state, seconds=30):
    """Run agent.run(state) with a signal.alarm timeout.

    v2: agents may declare a TIMEOUT_SECONDS class attribute to override the
    global AGENT_TIMEOUT_SECONDS (useful for scraping/enrichment agents that
    need more time without hanging the pipeline indefinitely).

    On timeout: appends to state['errors'], logs a [PIPELINE] warning,
    and returns state unchanged so the pipeline can continue.
    """
    agent_name = type(agent).__name__
    # Per-agent timeout overrides global default (v2 — scraping agents use longer timeouts)
    timeout = getattr(agent, 'TIMEOUT_SECONDS', seconds)
    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(timeout)
    try:
        result = agent.run(state)
    except AgentTimeout:
        logger.warning("[PIPELINE] %s timed out after %ds — skipping", agent_name, timeout)
        state["errors"].append({
            "agent": agent_name,
            "error": "Timeout after {}s".format(timeout),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return state
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
    return result


def _start_progress_reporter(state: dict, stage_holder: list, stop_event: threading.Event):
    """Daemon thread — logs pipeline status every 3 minutes automatically.

    stage_holder[0] = current agent name (updated by orchestrator loop)
    stage_holder[1] = pipeline start monotonic time
    Reads state dict in-place (same reference mutated by agents).
    """
    def _report():
        while not stop_event.wait(180):  # 180s = 3 min
            try:
                elapsed = time.monotonic() - stage_holder[1]
                enriched = state.get("enriched") or {}
                n_contacts = sum(
                    len(v.get("contacts", [])) if isinstance(v, dict) else 0
                    for v in enriched.values()
                ) if isinstance(enriched, dict) else 0
                raw_db = count_raw_listings()
                logger.info(
                    "[PROGRESS] %.0fm elapsed | stage: %s | "
                    "scraped=%d raw_db=%d filtered=%d scored=%d "
                    "validated=%d contacts=%d ready=%d errors=%d",
                    elapsed / 60,
                    stage_holder[0],
                    len(state.get("listings") or []),
                    raw_db,
                    len(state.get("filtered") or []),
                    len(state.get("scored") or []),
                    len(state.get("validated") or []),
                    n_contacts,
                    len(state.get("ready") or []),
                    len(state.get("errors") or []),
                )
            except Exception as _exc:
                logger.debug("[PROGRESS] reporter error: %s", _exc)

    t = threading.Thread(target=_report, daemon=True, name="progress-reporter")
    t.start()
    return t


class OpportunityOrchestrator:
    def __init__(self, agents: list) -> None:
        self._agents = agents

    def run(self, initial_state: dict) -> ExecutionState:
        state = initial_state
        state.setdefault("errors", [])
        state.setdefault("timings", [])
        state.setdefault("token_usage", {})

        stop_event = threading.Event()
        stage_holder = ["initialising", time.monotonic()]
        _start_progress_reporter(state, stage_holder, stop_event)

        for agent in self._agents:
            agent_name = type(agent).__name__
            stage_holder[0] = agent_name
            errors_before = len(state["errors"])
            start = time.monotonic()
            try:
                state = run_with_timeout(agent, state, seconds=AGENT_TIMEOUT_SECONDS)
            except Exception as exc:
                duration_secs = round(time.monotonic() - start, 3)
                logger.warning("[PIPELINE] %s raised %s: %s", agent_name, type(exc).__name__, exc)
                state["errors"].append({
                    "agent": agent_name,
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                state["timings"].append({"agent": agent_name, "duration_secs": duration_secs})
                in_key, out_key = _AGENT_IO.get(agent_name, (None, None))
                _log_agent(agent_name, state, in_key, out_key, duration_secs,
                           state["errors"][errors_before:])
                continue

            duration_secs = round(time.monotonic() - start, 3)
            state["timings"].append({"agent": agent_name, "duration_secs": duration_secs})
            in_key, out_key = _AGENT_IO.get(agent_name, (None, None))
            _log_agent(agent_name, state, in_key, out_key, duration_secs,
                       state["errors"][errors_before:])

            if state.get("stop"):
                logger.info("[PIPELINE] stop=True after %s — halting", agent_name)
                break

        stop_event.set()  # shut down progress reporter
        return state

