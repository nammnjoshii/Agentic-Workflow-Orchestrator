"""
demo.py — Rich terminal demo runner for the Agentic Workflow Orchestrator.

Forces DRY_RUN=true so no real API calls are made.  Run this script directly,
then capture it with asciinema for a client-ready recording.

Usage:
    python demo.py            # full 7-agent pipeline
    python demo.py digest     # digest-only demo

Recording:
    brew install asciinema
    asciinema rec workflow-demo.cast -- python demo.py
    asciinema play workflow-demo.cast
    asciinema upload workflow-demo.cast   # optional: share via link
"""

import logging
import os
import sys
import time

# Force DRY_RUN before any module that reads env vars is imported
os.environ["DRY_RUN"] = "true"

from dotenv import load_dotenv  # noqa: E402 — must come after DRY_RUN is set

from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.rule import Rule  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402

load_dotenv()

from src.database import init_db  # noqa: E402
from src.opportunity_orchestrator import (  # noqa: E402
    OpportunityOrchestrator,
    _AGENT_IO,
    _log_agent,
    run_with_timeout,
    AGENT_TIMEOUT_SECONDS,
)
from src.agents.procurement_intelligence_specialist import ProcurementIntelligenceSpecialist  # noqa: E402
from src.agents.opportunity_qualification_specialist import OpportunityQualificationSpecialist  # noqa: E402
from src.agents.strategic_scoring_agent import StrategicScoringAgent  # noqa: E402
from src.agents.scoring_assurance_analyst import ScoringAssuranceAnalyst  # noqa: E402
from src.agents.stakeholder_intelligence_specialist import StakeholderIntelligenceSpecialist  # noqa: E402
from src.agents.stakeholder_relevance_agent import StakeholderRelevanceAgent  # noqa: E402
from src.agents.executive_outreach_strategist import ExecutiveOutreachStrategist  # noqa: E402
from src.agents.intelligence_delivery_agent import IntelligenceDeliveryAgent  # noqa: E402

# ---------------------------------------------------------------------------
# Rich console (force_terminal ensures colour even when piped to asciinema)
# ---------------------------------------------------------------------------
console = Console(force_terminal=True, highlight=False)

# ---------------------------------------------------------------------------
# Short display names for each agent class
# ---------------------------------------------------------------------------
_SHORT_NAMES = {
    "ProcurementIntelligenceSpecialist":  "Procurement Scraper",
    "OpportunityQualificationSpecialist": "Qualification Filter",
    "StrategicScoringAgent":         "Strategy Scorer",
    "ScoringAssuranceAnalyst":            "Score Validator",
    "StakeholderIntelligenceSpecialist":  "Contact Discovery",
    "StakeholderRelevanceAgent":       "Contact Validator",
    "ExecutiveOutreachStrategist":        "Outreach Writer",
}

# ---------------------------------------------------------------------------
# Log handler: routes [PREFIX] log messages to the rich console with colour
# ---------------------------------------------------------------------------
_PREFIX_STYLES = {
    "[SCRAPER]":        "cyan",
    "[FILTER]":         "yellow",
    "[SCORER]":         "magenta",
    "[CRITIC-SCORE]":   "bright_magenta",
    "[CONTACTS]":       "blue",
    "[CRITIC-CONTACT]": "bright_blue",
    "[OUTREACH]":       "green",
    "[DIGEST]":         "bright_green",
    "[PIPELINE]":       "bright_yellow",
    "[MAIN]":           "white",
}


class _DemoLogHandler(logging.Handler):
    """Captures pipeline log messages and prints them with rich colours."""

    def emit(self, record):
        try:
            msg = self.format(record)
            for prefix, style in _PREFIX_STYLES.items():
                if prefix in msg:
                    console.print(f"    [{style}]{msg}[/{style}]")
                    return
            console.print(f"    [dim]{msg}[/dim]")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Demo orchestrator: wraps each agent with a spinner + completion line
# ---------------------------------------------------------------------------
class _DemoOrchestrator(OpportunityOrchestrator):
    """Subclass that adds rich per-agent progress output."""

    def run(self, initial_state):  # noqa: C901
        state = initial_state
        state.setdefault("errors", [])
        state.setdefault("timings", [])

        total = len(self._agents)

        for idx, agent in enumerate(self._agents, 1):
            agent_name = type(agent).__name__
            display = _SHORT_NAMES.get(agent_name, agent_name)
            label = f"[bold cyan][{idx}/{total}][/bold cyan] [white]{display}[/white]"

            errors_before = len(state["errors"])
            start = time.monotonic()

            with console.status(f"{label}  [dim]running…[/dim]", spinner="dots"):
                try:
                    state = run_with_timeout(agent, state, seconds=AGENT_TIMEOUT_SECONDS)
                except Exception as exc:
                    duration = round(time.monotonic() - start, 3)
                    state["errors"].append({
                        "agent": agent_name,
                        "error": str(exc),
                    })
                    state["timings"].append({"agent": agent_name, "duration_secs": duration})
                    in_key, out_key = _AGENT_IO.get(agent_name, (None, None))
                    _log_agent(agent_name, state, in_key, out_key, duration,
                               state["errors"][errors_before:])
                    console.print(
                        f"  [red]✗[/red] {label}  "
                        f"[dim]{duration:.1f}s[/dim]  "
                        f"[red]ERROR: {exc}[/red]"
                    )
                    continue

            duration = round(time.monotonic() - start, 3)
            state["timings"].append({"agent": agent_name, "duration_secs": duration})

            in_key, out_key = _AGENT_IO.get(agent_name, (None, None))
            _log_agent(agent_name, state, in_key, out_key, duration,
                       state["errors"][errors_before:])

            new_errors = state["errors"][errors_before:]
            out_count = len(state.get(out_key, [])) if out_key else None

            if new_errors:
                console.print(
                    f"  [red]✗[/red] {label}  "
                    f"[dim]{duration:.1f}s[/dim]  "
                    f"[red]{len(new_errors)} error(s)[/red]"
                )
            else:
                count_str = f"  [bold]{out_count} →[/bold]" if out_count is not None else ""
                console.print(
                    f"  [green]✓[/green] {label}  "
                    f"[dim]{duration:.1f}s[/dim]{count_str}"
                )

            if state.get("stop"):
                break

        return state


# ---------------------------------------------------------------------------
# Demo entry points
# ---------------------------------------------------------------------------
def _print_header():
    console.print()
    console.print(Panel(
        Text.from_markup(
            "[bold white]Agentic Workflow Orchestrator[/bold white]\n"
            "[dim]Autonomous RFP scraping · scoring · contact discovery · digest[/dim]\n"
            "[yellow]DEMO MODE — DRY_RUN=true (no real API calls)[/yellow]"
        ),
        title="[bold cyan]Intelligence Agent[/bold cyan]",
        border_style="cyan",
        expand=False,
        padding=(1, 4),
    ))
    console.print()


def run_demo_scrape():
    _print_header()
    console.print(Rule("[cyan]Daily Scrape Pipeline[/cyan]"))
    console.print()

    init_db()

    pipeline = _DemoOrchestrator([
        ProcurementIntelligenceSpecialist(),
        OpportunityQualificationSpecialist(),
        StrategicScoringAgent(),
        ScoringAssuranceAnalyst(),
        StakeholderIntelligenceSpecialist(),
        StakeholderRelevanceAgent(),
        ExecutiveOutreachStrategist(),
    ])

    state = {
        "listings": [], "filtered": [], "skipped": [], "scored": [],
        "validated": [], "enriched": [], "ready": [], "errors": [], "timings": [],
    }
    state = pipeline.run(state)

    # --- Summary table ---
    console.print()
    console.print(Rule("[cyan]Results[/cyan]"))
    console.print()

    n_scraped  = len(state.get("listings", []))
    n_filtered = len(state.get("filtered", []))
    n_pursue   = sum(1 for o in state.get("validated", [])
                     if o.get("recommendation") == "PURSUE")
    n_consider = sum(1 for o in state.get("validated", [])
                     if o.get("recommendation") == "CONSIDER")
    n_contacts = sum(len(o.get("contacts", [])) for o in state.get("ready", []))
    n_errors   = len(state.get("errors", []))
    total_secs = sum(t.get("duration_secs", 0) for t in state.get("timings", []))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold white")

    table.add_row("Portals scraped",       str(len({
        o.get("portal", "unknown") for o in state.get("listings", [])
    })) or "—")
    table.add_row("Listings found",        str(n_scraped))
    table.add_row("Passed qualification",  str(n_filtered))
    table.add_row("PURSUE",                f"[green]{n_pursue}[/green]")
    table.add_row("CONSIDER",              f"[yellow]{n_consider}[/yellow]")
    table.add_row("Contacts enriched",     str(n_contacts))
    table.add_row("Pipeline errors",       f"[red]{n_errors}[/red]" if n_errors else "[green]0[/green]")
    table.add_row("Total wall time",       f"{total_secs:.1f}s")

    console.print(table)
    console.print()


def run_demo_digest():
    _print_header()
    console.print(Rule("[cyan]Weekly Digest[/cyan]"))
    console.print()

    init_db()

    with console.status("[bold cyan]Building HTML digest…[/bold cyan]", spinner="dots"):
        advisor = IntelligenceDeliveryAgent()
        payload = advisor.run({})

    if not payload or not payload.get("html"):
        console.print("  [yellow]No unsent opportunities in DB — nothing to send.[/yellow]")
        console.print("  [dim]Run the scrape pipeline first to populate the database.[/dim]")
    else:
        n = payload.get("n", 0)
        console.print(f"  [green]✓[/green] Digest built — [bold]{n}[/bold] opportunities  [dim](DRY_RUN — not sent)[/dim]")

    console.print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Install rich log handler; suppress default stderr handler to avoid
    # duplicate plain-text output alongside the rich-formatted lines.
    handler = _DemoLogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "digest":
        run_demo_digest()
    else:
        run_demo_scrape()
