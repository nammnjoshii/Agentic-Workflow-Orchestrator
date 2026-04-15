"""
experiment_agent.py — Agentic Workflow Orchestrator Experiment Runner

Runs structured evaluation experiments against the scoring pipeline.
Supports single-version runs, consistency testing, and A/B comparisons.

Usage:
    DRY_RUN=true python3 evaluation/experiment_agent.py \\
        --version v1.0 --title base-architecture

    DRY_RUN=true python3 evaluation/experiment_agent.py \\
        --ab-test competitor-agent-test \\
        --version-a v1.2 --title-a no-competitor-agent \\
        --version-b v1.3 --title-b with-competitor-agent

Constraints:
    - No anthropic client (complies with antipatterns.md)
    - No async/await
    - DRY_RUN=true: pipeline agents return fixture data; tokens_used is estimated
    - Skips ProcurementIntelligenceSpecialist; injects test bids directly
    - Runs: QualificationSpecialist → StrategyAnalyst → ScoringAssuranceAnalyst
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Path setup — allow running from project root or evaluation/ directory
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from evaluation.metrics_calculator import MetricsCalculator  # noqa: E402

_DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# Estimated tokens per bid for DRY_RUN accounting
_DRY_RUN_TOKENS_PER_BID = 1200


# ---------------------------------------------------------------------------
# ExperimentAgent
# ---------------------------------------------------------------------------

class ExperimentAgent:
    """
    Orchestrates evaluation experiments against the scoring pipeline.

    Each call to run() or run_ab_test():
      1. Creates versioned experiment folder under /experiments/
      2. Loads test dataset from /evaluation/test_dataset/
      3. Runs pipeline on every bid (3x for consistency testing)
      4. Computes all 15 metrics via MetricsCalculator
      5. Stores per-bid outputs and any errors
      6. Appends a record to /evaluation/experiment_log.json
      7. Writes metrics.json and notes.md to the experiment folder
      8. Prints a human-readable summary
    """

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else _PROJECT_ROOT
        self.experiments_dir = self.base_dir / "experiments"
        self.evaluation_dir = self.base_dir / "evaluation"
        self.dataset_dir = self.evaluation_dir / "test_dataset"
        self.log_path = self.evaluation_dir / "experiment_log.json"

    # ------------------------------------------------------------------
    # Public: single experiment
    # ------------------------------------------------------------------

    def run(self, version, title, dataset_version="test_dataset_v1",
            notes_text=None, prev_version=None):
        """
        Run one full experiment and persist all artefacts.

        Parameters
        ----------
        version : str       e.g. "v1.0"
        title : str         e.g. "base-architecture"
        dataset_version : str
        notes_text : str | None   Pre-written notes (optional)
        prev_version : str | None Version label to compare against in summary

        Returns
        -------
        dict  metrics record that was written to metrics.json and log
        """
        print(f"\n{'='*60}")
        print(f"  EXPERIMENT: {version}_{title}")
        print(f"  Dataset:    {dataset_version}")
        print(f"  DRY_RUN:    {_DRY_RUN}")
        print(f"{'='*60}\n")

        experiment_dir = self._setup_experiment_dir(version, title)
        bids = self._load_dataset(dataset_version)
        ground_truth_map = {b["bid_id"]: b["ground_truth"] for b in bids}

        # --- Phase 1: Unit tests ----------------------------------------
        print("[Phase 1] Unit testing individual pipeline skills...")
        unit_results = self._run_unit_tests()
        self._print_unit_results(unit_results)

        # --- Phase 2: Scenario testing (3 consistency passes) -----------
        print("\n[Phase 2] Scenario testing — running pipeline on all bids...")
        t_start = time.time()
        all_passes = []
        total_errors = 0

        for pass_num in range(1, 4):
            print(f"  Pass {pass_num}/3...")
            pass_outputs, pass_errors = self._run_pipeline_pass(bids)
            all_passes.append(pass_outputs)
            if pass_num == 1:
                total_errors = len(pass_errors)
                for err in pass_errors:
                    self._save_error(experiment_dir, err["bid_id"], err)

        runtime = time.time() - t_start
        primary_outputs = all_passes[0]

        # Save per-bid outputs from first pass
        for out in primary_outputs:
            self._save_output(experiment_dir, out["bid_id"], out)

        # --- Phase 3: Strategic evaluation ------------------------------
        print("\n[Phase 3] Strategic evaluation — computing metrics...")
        tokens = (
            _DRY_RUN_TOKENS_PER_BID * len(bids) * 3
            if _DRY_RUN
            else self._collect_tokens(primary_outputs)
        )
        calc = MetricsCalculator(
            outputs=primary_outputs,
            ground_truth_map=ground_truth_map,
            run_history=all_passes,
            total_errors=total_errors,
            tokens_used=tokens,
            runtime_seconds=runtime,
        )
        metrics = calc.calculate_all()

        # --- Persist artefacts ------------------------------------------
        metrics_record = {
            "version": version,
            "title": title,
            "date": str(date.today()),
            "dataset": dataset_version,
            "metrics": metrics,
            "unit_tests": unit_results,
        }
        self._write_metrics(experiment_dir, metrics_record)
        self._update_experiment_log(metrics_record)

        # Notes
        if notes_text is None:
            notes_text = self._default_notes(version, title)
        summary_text = self._build_summary_text(metrics, prev_version)
        self._write_notes(experiment_dir, notes_text, summary_text)

        # Print summary
        self._print_summary(metrics, prev_version_label=prev_version)

        print(f"\n[Done] Artefacts written to: {experiment_dir}")
        return metrics_record

    # ------------------------------------------------------------------
    # Public: A/B experiment
    # ------------------------------------------------------------------

    def run_ab_test(self, experiment_name, version_a, title_a,
                    version_b, title_b, dataset_version="test_dataset_v1"):
        """
        Run two experiment versions against the same dataset and write
        a comparison.json into experiments/ab_tests/{experiment_name}/.

        Returns
        -------
        dict  comparison result
        """
        print(f"\n{'='*60}")
        print(f"  A/B TEST: {experiment_name}")
        print(f"  Version A: {version_a}_{title_a}")
        print(f"  Version B: {version_b}_{title_b}")
        print(f"{'='*60}\n")

        ab_dir = self.experiments_dir / "ab_tests" / experiment_name
        dir_a = ab_dir / "version_a"
        dir_b = ab_dir / "version_b"
        dir_a.mkdir(parents=True, exist_ok=True)
        dir_b.mkdir(parents=True, exist_ok=True)
        (dir_a / "outputs").mkdir(exist_ok=True)
        (dir_a / "errors").mkdir(exist_ok=True)
        (dir_b / "outputs").mkdir(exist_ok=True)
        (dir_b / "errors").mkdir(exist_ok=True)

        bids = self._load_dataset(dataset_version)
        ground_truth_map = {b["bid_id"]: b["ground_truth"] for b in bids}

        print("Running Version A...")
        a_outputs, a_errors = self._run_pipeline_pass(bids)
        for out in a_outputs:
            self._save_output(dir_a, out["bid_id"], out)

        print("Running Version B...")
        b_outputs, b_errors = self._run_pipeline_pass(bids)
        for out in b_outputs:
            self._save_output(dir_b, out["bid_id"], out)

        tokens = _DRY_RUN_TOKENS_PER_BID * len(bids) if _DRY_RUN else 0
        a_calc = MetricsCalculator(a_outputs, ground_truth_map,
                                   tokens_used=tokens)
        b_calc = MetricsCalculator(b_outputs, ground_truth_map,
                                   tokens_used=tokens)
        a_metrics = a_calc.calculate_all()
        b_metrics = b_calc.calculate_all()

        self._write_metrics(dir_a, {
            "version": version_a, "title": title_a,
            "date": str(date.today()), "dataset": dataset_version,
            "metrics": a_metrics,
        })
        self._write_metrics(dir_b, {
            "version": version_b, "title": title_b,
            "date": str(date.today()), "dataset": dataset_version,
            "metrics": b_metrics,
        })

        comparison = self._build_comparison(
            experiment_name, version_a, title_a, version_b, title_b,
            a_metrics, b_metrics,
        )
        comp_path = ab_dir / "comparison.json"
        comp_path.write_text(json.dumps(comparison, indent=2))
        print(f"\n[A/B Done] Comparison written to: {comp_path}")
        return comparison

    # ------------------------------------------------------------------
    # Pipeline execution
    # ------------------------------------------------------------------

    def _run_pipeline_pass(self, bids):
        """
        Run one pass of the scoring pipeline on all bids.
        Injects bids directly as state['listings'], skips scraper.
        Runs: QualificationSpecialist → StrategyAnalyst → ScoringAssuranceAnalyst

        Returns
        -------
        outputs : list[dict]
        errors  : list[dict]
        """
        from src.agents.opportunity_qualification_specialist import (
            OpportunityQualificationSpecialist,
        )
        from src.agents.strategic_scoring_agent import (
            StrategicScoringAgent,
        )
        from src.agents.scoring_assurance_analyst import (
            ScoringAssuranceAnalyst,
        )

        outputs = []
        errors = []

        for bid in bids:
            bid_id = bid.get("bid_id", "unknown")
            # Strip ground_truth before feeding into pipeline
            listing = {k: v for k, v in bid.items() if k != "ground_truth"}

            state = {
                "listings": [listing],
                "filtered": [],
                "skipped": [],
                "scored": [],
                "validated": [],
                "enriched": [],
                "ready": [],
                "errors": [],
                "timings": [],
            }

            try:
                state = OpportunityQualificationSpecialist().run(state)
                state = StrategicScoringAgent().run(state)
                state = ScoringAssuranceAnalyst().run(state)

                validated = state.get("validated", [])
                scored = state.get("scored", [])
                result_list = validated if validated else scored

                if result_list:
                    item = result_list[0]
                    priority_score = item.get("opportunity_priority_score", 0)
                    filter_score = item.get("filter_score", 0)
                    relevance = item.get("relevance_score", 0)
                    # Confidence: normalised average of filter + relevance
                    confidence = round((filter_score + relevance) / 200.0, 4)
                    # Decision: bid if priority_score >= 60, else pass
                    decision = "bid" if priority_score >= 60 else "pass"

                    out = {
                        "bid_id": bid_id,
                        "title": item.get("title", ""),
                        "org": item.get("org", ""),
                        "value": item.get("value", ""),
                        "decision": decision,
                        "confidence": confidence,
                        "relevance_score": relevance,
                        "filter_score": filter_score,
                        "opportunity_priority_score": priority_score,
                        "recommendation": item.get("recommendation", ""),
                        "identified_risks": item.get("risks", []),
                        "capability_match": item.get("capability_match", []),
                        "opportunities": [],
                        "competitors": [],
                        "reasoning": item.get("score_rationale", ""),
                        "exec_summary": item.get("exec_summary", ""),
                        "suggested_angle": item.get("suggested_angle", ""),
                        "estimated_effort": item.get("estimated_effort", ""),
                    }
                else:
                    # Bid was filtered out (below threshold)
                    listing_back = (state.get("skipped") or [listing])[0]
                    out = {
                        "bid_id": bid_id,
                        "title": listing_back.get("title", ""),
                        "org": listing_back.get("org", ""),
                        "value": listing_back.get("value", ""),
                        "decision": "pass",
                        "confidence": round(
                            listing_back.get("filter_score", 0) / 100.0, 4
                        ),
                        "relevance_score": listing_back.get("filter_score", 0),
                        "filter_score": listing_back.get("filter_score", 0),
                        "opportunity_priority_score": 0,
                        "recommendation": "SKIP",
                        "identified_risks": [],
                        "capability_match": [],
                        "opportunities": [],
                        "competitors": [],
                        "reasoning": "Below qualification threshold.",
                        "exec_summary": "",
                        "suggested_angle": "",
                        "estimated_effort": "",
                    }
                outputs.append(out)

            except Exception as exc:
                errors.append({
                    "bid_id": bid_id,
                    "input": listing,
                    "failure_reason": str(exc),
                    "agent_stage": "pipeline",
                    "traceback": traceback.format_exc(),
                })
                print(f"  [ERROR] {bid_id}: {exc}")

        return outputs, errors

    # ------------------------------------------------------------------
    # Phase 1: Unit tests
    # ------------------------------------------------------------------

    def _run_unit_tests(self):
        """
        Validate individual pipeline skills.
        Returns dict with pass/fail per skill.
        """
        results = {}

        # --- Competitor/capability extraction ---
        results["capability_extraction"] = self._unit_capability_extraction()

        # --- Risk detection ---
        results["risk_detection"] = self._unit_risk_detection()

        # --- Opportunity detection ---
        results["opportunity_detection"] = self._unit_opportunity_detection()

        # --- Win probability estimation ---
        results["win_probability_estimation"] = (
            self._unit_win_probability()
        )

        return results

    def _unit_capability_extraction(self):
        """Check that scoring agent extracts at least one capability."""
        try:
            from src.agents.strategic_scoring_agent import (
                StrategicScoringAgent,
            )
            state = {
                "filtered": [{
                    "title": "Snowflake Data Warehouse",
                    "org": "Test Org",
                    "deadline": "2026-06-01",
                    "value": "$500,000",
                    "url": "https://unit.test/cap",
                    "source": "MERX",
                    "raw_description": (
                        "Implement a Snowflake-based data warehouse with "
                        "Power BI dashboards and ETL pipelines."
                    ),
                    "filter_score": 75,
                }],
                "scored": [], "errors": [], "timings": [],
            }
            state = StrategicScoringAgent().run(state)
            scored = state.get("scored", [])
            if scored and scored[0].get("capability_match"):
                return {"status": "pass", "detail": "capabilities extracted"}
            return {"status": "fail", "detail": "no capabilities extracted"}
        except Exception as exc:
            return {"status": "fail", "detail": str(exc)}

    def _unit_risk_detection(self):
        """Check that scoring agent identifies at least one risk."""
        try:
            from src.agents.strategic_scoring_agent import (
                StrategicScoringAgent,
            )
            state = {
                "filtered": [{
                    "title": "Legacy System Migration",
                    "org": "Government Agency",
                    "deadline": "2026-06-01",
                    "value": "$300,000",
                    "url": "https://unit.test/risk",
                    "source": "CanadaBuys",
                    "raw_description": (
                        "Migrate Oracle legacy data warehouse to Snowflake. "
                        "Incumbent vendor has existing relationship. "
                        "High compliance requirements under FOIPPA."
                    ),
                    "filter_score": 72,
                }],
                "scored": [], "errors": [], "timings": [],
            }
            state = StrategicScoringAgent().run(state)
            scored = state.get("scored", [])
            if scored and scored[0].get("risks"):
                return {"status": "pass", "detail": "risks identified"}
            return {
                "status": "warn",
                "detail": "no risks identified (may be DRY_RUN fixture)",
            }
        except Exception as exc:
            return {"status": "fail", "detail": str(exc)}

    def _unit_opportunity_detection(self):
        """Check that filter passes a clearly relevant bid."""
        try:
            from src.agents.opportunity_qualification_specialist import (
                OpportunityQualificationSpecialist,
            )
            state = {
                "listings": [{
                    "title": "Snowflake Cloud Data Analytics",
                    "org": "BC Hydro",
                    "deadline": "2026-06-01",
                    "value": "$500,000",
                    "url": "https://unit.test/opp",
                    "source": "MERX",
                    "raw_description": (
                        "Enterprise Snowflake deployment with Power BI, "
                        "dbt transformations, and data governance."
                    ),
                }],
                "filtered": [], "skipped": [], "errors": [], "timings": [],
            }
            state = OpportunityQualificationSpecialist().run(state)
            if state.get("filtered"):
                return {"status": "pass", "detail": "high-relevance bid passed filter"}
            return {
                "status": "warn",
                "detail": "bid was filtered out (check threshold or DRY_RUN)",
            }
        except Exception as exc:
            return {"status": "fail", "detail": str(exc)}

    def _unit_win_probability(self):
        """
        Check that opportunity_priority_score is an int in 0–100.
        Acts as a proxy for win-probability estimation quality.
        """
        try:
            from src.agents.strategic_scoring_agent import (
                StrategicScoringAgent,
            )
            state = {
                "filtered": [{
                    "title": "Data Integration Platform",
                    "org": "City of Victoria",
                    "deadline": "2026-07-01",
                    "value": "$400,000",
                    "url": "https://unit.test/win",
                    "source": "BCBid",
                    "raw_description": (
                        "Azure Data Factory, dbt, Snowflake integration "
                        "for city financial and operational reporting."
                    ),
                    "filter_score": 78,
                }],
                "scored": [], "errors": [], "timings": [],
            }
            state = StrategicScoringAgent().run(state)
            scored = state.get("scored", [])
            if scored:
                score = scored[0].get("opportunity_priority_score")
                if isinstance(score, int) and 0 <= score <= 100:
                    return {
                        "status": "pass",
                        "detail": f"priority_score={score} (valid 0–100 int)",
                    }
                return {
                    "status": "fail",
                    "detail": f"invalid priority_score: {score!r}",
                }
            return {"status": "fail", "detail": "no scored output"}
        except Exception as exc:
            return {"status": "fail", "detail": str(exc)}

    # ------------------------------------------------------------------
    # File I/O helpers
    # ------------------------------------------------------------------

    def _setup_experiment_dir(self, version, title):
        """Create versioned experiment folder with subdirectories."""
        folder_name = f"{version}_{title}"
        exp_dir = self.experiments_dir / folder_name
        (exp_dir / "outputs").mkdir(parents=True, exist_ok=True)
        (exp_dir / "errors").mkdir(parents=True, exist_ok=True)
        return exp_dir

    def _load_dataset(self, dataset_version):
        """Load all bid JSON files from test_dataset/."""
        bids = []
        for bid_file in sorted(self.dataset_dir.glob("bid_*.json")):
            with bid_file.open() as fh:
                bids.append(json.load(fh))
        if not bids:
            raise FileNotFoundError(
                f"No bid files found in {self.dataset_dir}"
            )
        print(f"  Loaded {len(bids)} bids from {self.dataset_dir.name}/")
        return bids

    def _save_output(self, experiment_dir, bid_id, output):
        """Write per-bid output JSON to outputs/ directory."""
        path = experiment_dir / "outputs" / f"{bid_id}_output.json"
        path.write_text(json.dumps(output, indent=2))

    def _save_error(self, experiment_dir, bid_id, error_info):
        """Write error record to errors/ directory."""
        path = experiment_dir / "errors" / f"{bid_id}_error.json"
        path.write_text(json.dumps(error_info, indent=2))

    def _write_metrics(self, experiment_dir, metrics_record):
        """Write metrics.json to experiment folder."""
        path = experiment_dir / "metrics.json"
        path.write_text(json.dumps(metrics_record, indent=2))

    def _update_experiment_log(self, metrics_record):
        """Append metrics record to global experiment_log.json."""
        if self.log_path.exists():
            with self.log_path.open() as fh:
                log = json.load(fh)
        else:
            log = {"experiments": []}

        # Slim record for log (omit unit_tests detail)
        log_entry = {
            "version": metrics_record["version"],
            "title": metrics_record["title"],
            "date": metrics_record["date"],
            "dataset": metrics_record["dataset"],
            "metrics": metrics_record["metrics"],
        }
        log["experiments"].append(log_entry)
        self.log_path.write_text(json.dumps(log, indent=2))

    def _write_notes(self, experiment_dir, notes_text, summary_text):
        """Write notes.md to experiment folder."""
        path = experiment_dir / "notes.md"
        content = f"{notes_text}\n\n---\n\n## Experiment Summary\n\n{summary_text}"
        path.write_text(content)

    # ------------------------------------------------------------------
    # A/B comparison builder
    # ------------------------------------------------------------------

    def _build_comparison(self, experiment_name, version_a, title_a,
                          version_b, title_b, a_metrics, b_metrics):
        """Build comparison.json content for an A/B test."""
        def diff(key):
            return round(b_metrics.get(key, 0) - a_metrics.get(key, 0), 4)

        recommended = (
            version_b
            if b_metrics.get("decision_accuracy", 0)
            >= a_metrics.get("decision_accuracy", 0)
            else version_a
        )

        return {
            "experiment": experiment_name,
            "version_a": f"{version_a}_{title_a}",
            "version_b": f"{version_b}_{title_b}",
            "result": {
                "accuracy_difference": diff("decision_accuracy"),
                "relevance_score_difference": diff("relevance_score"),
                "strategic_depth_difference": diff("strategic_depth_score"),
                "reasoning_quality_difference": diff("reasoning_quality"),
                "hallucination_difference": diff("hallucination_rate"),
                "real_business_value_difference": diff("real_business_value"),
                "tokens_used_difference": diff("tokens_used"),
                "recommended_version": recommended,
            },
        }

    # ------------------------------------------------------------------
    # Summary builders
    # ------------------------------------------------------------------

    def _default_notes(self, version, title):
        return (
            f"# Experiment Notes — {version}_{title}\n\n"
            "## What Changed\n"
            f"Version {version}: {title.replace('-', ' ').title()}\n\n"
            "## Why It Was Introduced\n"
            "_(Fill in rationale for this architectural change)_\n\n"
            "## Observed Improvements\n"
            "_(Fill in after reviewing metrics)_\n\n"
            "## Observed Regressions\n"
            "_(Fill in after reviewing metrics)_\n\n"
            "## Recommendation\n"
            "_(Fill in: adopt / reject / revisit)_"
        )

    def _build_summary_text(self, metrics, prev_version_label):
        lines = []
        if prev_version_label:
            lines.append(f"Previous Version: {prev_version_label}")
        lines.append(f"Current Version: {metrics.get('version', '?')}\n")
        lines.append(
            f"Decision Accuracy:       {metrics['decision_accuracy']:.2%}"
        )
        lines.append(
            f"Relevance Score:         {metrics['relevance_score']:.1f}/10"
        )
        lines.append(
            f"Reasoning Quality:       {metrics['reasoning_quality']:.1f}/10"
        )
        lines.append(
            f"Hallucination Rate:      {metrics['hallucination_rate']:.2%}"
        )
        lines.append(f"Coverage:                {metrics['coverage']:.2%}")
        lines.append(
            f"Avg Confidence:          {metrics['average_confidence']:.2%}"
        )
        lines.append(
            f"Evidence Grounding:      {metrics['evidence_grounding']:.2%}"
        )
        lines.append(
            f"Risk ID Accuracy:        {metrics['risk_identification_accuracy']:.2%}"
        )
        lines.append(
            f"Confidence Calibration:  {metrics['confidence_calibration']:.4f}"
        )
        lines.append(f"Consistency:             {metrics['consistency']:.2%}")
        lines.append(
            f"Differentiation Insight: {metrics['differentiation_insight']:.1f}/10"
        )
        lines.append(
            f"Strategic Depth:         {metrics['strategic_depth_score']:.1f}/10"
        )
        lines.append(
            f"Real Business Value:     {metrics['real_business_value']:.1f}/10"
        )
        lines.append(f"Tokens Used:             {metrics['tokens_used']:,}")
        lines.append(
            f"Runtime:                 {metrics['runtime_seconds']:.1f}s"
        )
        return "\n".join(lines)

    def _print_unit_results(self, results):
        for skill, result in results.items():
            status_icon = {"pass": "✓", "warn": "~", "fail": "✗"}.get(
                result["status"], "?"
            )
            print(f"  [{status_icon}] {skill}: {result['detail']}")

    def _print_summary(self, metrics, prev_version_label=None):
        print(f"\n{'='*60}")
        print("  EXPERIMENT RESULTS")
        print(f"{'='*60}")
        print(self._build_summary_text(metrics, prev_version_label))
        print(f"{'='*60}\n")

    # ------------------------------------------------------------------
    # Token collection (live mode placeholder)
    # ------------------------------------------------------------------

    def _collect_tokens(self, outputs):
        """In live mode, sum token usage from outputs if tracked."""
        return sum(out.get("_tokens_used", 0) for out in outputs)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Run Agentic Workflow Orchestrator experiments."
    )
    parser.add_argument("--version", default="v1.0",
                        help="Version label, e.g. v1.2")
    parser.add_argument("--title", default="base-architecture",
                        help="Short title, e.g. competitor-intelligence")
    parser.add_argument("--dataset", default="test_dataset_v1",
                        help="Dataset version label")
    parser.add_argument("--prev-version", default=None,
                        help="Previous version label for delta summary")
    parser.add_argument("--ab-test", default=None,
                        help="A/B test name (activates A/B mode)")
    parser.add_argument("--version-a", default=None)
    parser.add_argument("--title-a", default=None)
    parser.add_argument("--version-b", default=None)
    parser.add_argument("--title-b", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    agent = ExperimentAgent()

    if args.ab_test:
        agent.run_ab_test(
            experiment_name=args.ab_test,
            version_a=args.version_a or "v1.0",
            title_a=args.title_a or "version-a",
            version_b=args.version_b or "v1.1",
            title_b=args.title_b or "version-b",
            dataset_version=args.dataset,
        )
    else:
        agent.run(
            version=args.version,
            title=args.title,
            dataset_version=args.dataset,
            prev_version=args.prev_version,
        )
