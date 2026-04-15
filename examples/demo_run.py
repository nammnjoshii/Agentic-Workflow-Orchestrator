"""
demo_run.py — Agentic Workflow Orchestrator demo runner.

Runs the full 7-agent pipeline in DRY_RUN mode using fixture data.
No live API calls. No database writes.

Usage:
    PYTHONPATH=. DRY_RUN=true python examples/demo_run.py
"""
import os
import sys

if os.environ.get("DRY_RUN", "false").lower() != "true":
    print("This demo requires DRY_RUN=true to avoid live API calls.")
    print("Run with: PYTHONPATH=. DRY_RUN=true python examples/demo_run.py")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.opportunity_orchestrator import OpportunityOrchestrator

if __name__ == "__main__":
    print("\nAgentic Workflow Orchestrator — Demo Run")
    print("=" * 60)
    orchestrator = OpportunityOrchestrator()
    state = orchestrator.run()
    scored = state.get("scored", [])
    errors = state.get("errors", [])
    timings = state.get("timings", {})
    print(f"\nPipeline complete")
    print(f"  Scored opportunities: {len(scored)}")
    print(f"  Errors logged:        {len(errors)}")
    if timings:
        total = sum(timings.values())
        print(f"  Total wall time:      {total:.1f}s")
    print("=" * 60)
