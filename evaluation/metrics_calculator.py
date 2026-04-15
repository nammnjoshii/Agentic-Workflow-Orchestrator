"""
metrics_calculator.py — Experiment Evaluation Metrics

Computes all 14+ evaluation metrics for experiment runs.
No anthropic client. No async. DRY_RUN compatible.
"""

import math
import re


# ---------------------------------------------------------------------------
# Known client capability taxonomy (from docs/data/capability-profile.md)
# Used for hallucination detection: any capability NOT in this set is suspect.
# ---------------------------------------------------------------------------
_CLIENT_CAPABILITY_TAXONOMY = {
    # Cloud data platforms
    "snowflake", "databricks", "azure synapse", "google bigquery", "redshift",
    "azure data factory", "azure data lake", "azure devops", "azure ml",
    "aws glue", "aws s3", "gcp", "google cloud",
    # BI and visualization
    "power bi", "tableau", "looker", "qlik", "quicksight",
    # ETL / data engineering
    "etl/elt pipelines", "etl", "elt", "dbt", "apache airflow", "airflow",
    "apache kafka", "kafka", "apache spark", "spark", "fivetran", "stitch",
    # Data governance / catalogues
    "data governance", "collibra", "alation", "apache atlas",
    "data catalogue", "data lineage", "metadata management",
    # Programming languages and ML
    "python", "r", "sql", "scala",
    "machine learning", "ml", "mlops", "azure ml", "scikit-learn",
    "pytorch", "tensorflow", "nlp",
    # Analytics and modelling
    "statistical modelling", "predictive modelling", "forecasting",
    "self-service analytics", "marketing analytics",
    # CRM / ERP integrations
    "sap", "sap integration", "salesforce", "salesforce crm", "oracle",
    "ms dynamics", "dynamics 365",
    # Specialised platforms
    "cdp", "segment", "mparticle", "hl7 fhir", "epic ehr",
    # Architecture patterns
    "data warehouse", "data mesh", "lakehouse", "data lake",
    "ci/cd", "devops", "kubernetes", "docker",
    # Cloud providers
    "aws", "azure", "gcp", "microsoft azure",
    # Broad IT consulting (partial match)
    "it consulting", "reporting modernization", "healthcare analytics",
    "data integration",
}

# Analytical terms expected in high-quality reasoning
_ANALYTICAL_TERMS = [
    "capability", "align", "match", "incumbent", "risk", "advantage",
    "differentiat", "competitive", "deliverable", "requirement", "scope",
    "compliance", "govern", "integration", "migration", "platform",
    "analytics", "data", "cloud", "enterprise",
]

# Differentiator phrases expected in strategic outputs
_DIFFERENTIATOR_PHRASES = [
    "snowflake", "track record", "proven", "experience",
    "crown", "public sector", "bc hydro", "reference", "deliverable",
    "certif", "speciali", "partner",
]


class MetricsCalculator:
    """
    Calculates all evaluation metrics for one experiment run.

    Parameters
    ----------
    outputs : list[dict]
        Per-bid output records (keys: bid_id, decision, confidence,
        relevance_score, opportunity_priority_score, identified_risks,
        capability_match, reasoning, score_rationale, org, value)
    ground_truth_map : dict[str, dict]
        Keyed by bid_id; values are ground_truth blocks from test dataset.
    run_history : list[list[dict]] | None
        For consistency testing: list of N output lists from repeat runs.
    total_errors : int
        Number of bids that failed entirely (caught exceptions).
    tokens_used : int
        Accumulated token count (from API calls or DRY_RUN estimate).
    runtime_seconds : float
        Wall-clock seconds for the full experiment run.
    """

    def __init__(self, outputs, ground_truth_map, run_history=None,
                 total_errors=0, tokens_used=0, runtime_seconds=0.0):
        self.outputs = outputs
        self.ground_truth_map = ground_truth_map
        self.run_history = run_history or []
        self.total_errors = total_errors
        self.tokens_used = tokens_used
        self.runtime_seconds = runtime_seconds
        self._total_bids = len(outputs) + total_errors

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_all(self):
        """Return full metrics dict with all 15 metrics."""
        return {
            "decision_accuracy": self.decision_accuracy(),
            "relevance_score": self.relevance_score(),
            "reasoning_quality": self.reasoning_quality(),
            "hallucination_rate": self.hallucination_rate(),
            "coverage": self.coverage(),
            "average_confidence": self.average_confidence(),
            "evidence_grounding": self.evidence_grounding(),
            "risk_identification_accuracy": self.risk_identification_accuracy(),
            "confidence_calibration": self.confidence_calibration(),
            "consistency": self.consistency(),
            "differentiation_insight": self.differentiation_insight(),
            "strategic_depth_score": self.strategic_depth_score(),
            "real_business_value": self.real_business_value(),
            "tokens_used": self.tokens_used,
            "runtime_seconds": round(self.runtime_seconds, 2),
        }

    # ------------------------------------------------------------------
    # Core Quality Metrics
    # ------------------------------------------------------------------

    def decision_accuracy(self):
        """% of bids where pipeline decision matches ground truth."""
        if not self.outputs:
            return 0.0
        correct = 0
        for out in self.outputs:
            bid_id = out.get("bid_id")
            gt = self.ground_truth_map.get(bid_id, {})
            expected = gt.get("decision", "")
            actual = out.get("decision", "")
            if actual == expected:
                correct += 1
        return round(correct / len(self.outputs), 4)

    def relevance_score(self):
        """Average opportunity_priority_score normalised to 0–10."""
        if not self.outputs:
            return 0.0
        scores = [out.get("opportunity_priority_score", 0) for out in self.outputs]
        return round(sum(scores) / len(scores) / 10.0, 2)

    def reasoning_quality(self):
        """
        Heuristic 0–10 score based on score_rationale quality.
        Criteria:
          - Length ≥ 80 chars → base 6.0
          - Each analytical term present → +0.2 (max +3.0)
          - Presence of org-specific references → +0.5
          - Presence of value/contract reference → +0.5
        """
        if not self.outputs:
            return 0.0
        scores = []
        for out in self.outputs:
            rationale = out.get("reasoning") or out.get("score_rationale", "")
            rationale_lower = rationale.lower()
            score = 0.0
            if len(rationale) >= 80:
                score += 6.0
            elif len(rationale) >= 40:
                score += 4.0
            elif len(rationale) > 0:
                score += 2.0
            term_bonus = sum(
                0.2 for term in _ANALYTICAL_TERMS
                if term in rationale_lower
            )
            score += min(term_bonus, 3.0)
            org = (out.get("org") or "").lower()
            if org and org in rationale_lower:
                score += 0.5
            for value_word in ["$", "million", "000", "contract", "value"]:
                if value_word in rationale_lower:
                    score += 0.25
                    break
            scores.append(min(score, 10.0))
        return round(sum(scores) / len(scores), 2)

    def hallucination_rate(self):
        """
        Fraction of capability_match items that are NOT in the known
        client taxonomy. A higher rate indicates hallucinated capabilities.
        """
        if not self.outputs:
            return 0.0
        total_caps = 0
        hallucinated = 0
        for out in self.outputs:
            caps = out.get("capability_match", [])
            for cap in caps:
                total_caps += 1
                cap_lower = cap.lower().strip()
                if not any(known in cap_lower or cap_lower in known
                           for known in _CLIENT_CAPABILITY_TAXONOMY):
                    hallucinated += 1
        if total_caps == 0:
            return 0.0
        return round(hallucinated / total_caps, 4)

    def coverage(self):
        """Fraction of total bids processed without complete failure."""
        if self._total_bids == 0:
            return 0.0
        return round(len(self.outputs) / self._total_bids, 4)

    def average_confidence(self):
        """Average confidence score across all outputs (0–1 scale)."""
        if not self.outputs:
            return 0.0
        confidences = [out.get("confidence", 0.0) for out in self.outputs]
        return round(sum(confidences) / len(confidences), 4)

    # ------------------------------------------------------------------
    # Evidence & Reliability Metrics
    # ------------------------------------------------------------------

    def evidence_grounding(self):
        """
        Fraction of outputs where score_rationale contains at least one
        concrete reference to org name, contract value, or specific
        capability named in the bid.
        """
        if not self.outputs:
            return 0.0
        grounded = 0
        for out in self.outputs:
            rationale = (out.get("reasoning") or out.get("score_rationale", "")).lower()
            org = (out.get("org") or "").lower()
            value = (out.get("value") or "").lower()
            caps = [c.lower() for c in out.get("capability_match", [])]
            if org and org in rationale:
                grounded += 1
                continue
            if value and any(part in rationale for part in value.split() if len(part) > 3):
                grounded += 1
                continue
            if any(cap in rationale for cap in caps if len(cap) > 4):
                grounded += 1
        return round(grounded / len(self.outputs), 4)

    def risk_identification_accuracy(self):
        """
        For bids with expected_risks, compute the fraction of expected
        risk keywords found in identified_risks. Averaged across bids
        that have ground truth risks.
        """
        scored_bids = []
        for out in self.outputs:
            bid_id = out.get("bid_id")
            gt = self.ground_truth_map.get(bid_id, {})
            expected_risks = gt.get("expected_risks", [])
            if not expected_risks:
                continue
            identified = " ".join(out.get("identified_risks", [])).lower()
            found = sum(
                1 for er in expected_risks
                if any(word in identified for word in er.lower().split()
                       if len(word) > 3)
            )
            scored_bids.append(found / len(expected_risks))
        if not scored_bids:
            return 0.0
        return round(sum(scored_bids) / len(scored_bids), 4)

    def confidence_calibration(self):
        """
        Pearson correlation between per-bid confidence and per-bid accuracy.
        A well-calibrated model has high confidence on correct decisions
        and low confidence on incorrect ones.
        Returns value in [−1, 1]; 1.0 is perfect calibration.
        """
        if len(self.outputs) < 3:
            return 0.0
        confidence_vals = []
        accuracy_vals = []
        for out in self.outputs:
            bid_id = out.get("bid_id")
            gt = self.ground_truth_map.get(bid_id, {})
            expected = gt.get("decision", "")
            actual = out.get("decision", "")
            confidence_vals.append(out.get("confidence", 0.5))
            accuracy_vals.append(1.0 if actual == expected else 0.0)
        return round(_pearson_correlation(confidence_vals, accuracy_vals), 4)

    def consistency(self):
        """
        Fraction of identical decisions across N repeat runs.
        Requires run_history (list of output lists).
        If only 1 run available, returns 1.0 (trivially consistent).
        """
        if len(self.run_history) < 2:
            return 1.0
        bid_ids = [out.get("bid_id") for out in self.run_history[0]]
        agreements = []
        for bid_id in bid_ids:
            decisions = set()
            for run_outputs in self.run_history:
                for out in run_outputs:
                    if out.get("bid_id") == bid_id:
                        decisions.add(out.get("decision"))
                        break
            agreements.append(1.0 if len(decisions) == 1 else 0.0)
        if not agreements:
            return 0.0
        return round(sum(agreements) / len(agreements), 4)

    # ------------------------------------------------------------------
    # Strategic Intelligence Metrics
    # ------------------------------------------------------------------

    def differentiation_insight(self):
        """
        Heuristic 1–10 score for quality of competitive differentiation.
        Based on: suggested_angle length, presence of the client's
        differentiator keywords, and specificity of positioning.
        """
        if not self.outputs:
            return 0.0
        scores = []
        for out in self.outputs:
            angle = (out.get("suggested_angle") or "").lower()
            score = 1.0
            if len(angle) >= 60:
                score += 3.0
            elif len(angle) >= 30:
                score += 1.5
            diff_hits = sum(
                1 for phrase in _DIFFERENTIATOR_PHRASES if phrase in angle
            )
            score += min(diff_hits * 1.2, 4.0)
            # Penalise generic angles
            if angle in ("", "not specified", "n/a"):
                score = 1.0
            scores.append(min(score, 10.0))
        return round(sum(scores) / len(scores), 2)

    def strategic_depth_score(self):
        """
        Heuristic 1–10 score for analytical depth.
        Components (weighted):
          - Number of capability_match items   40%
          - Number of identified_risks         30%
          - exec_summary length quality        30%
        Each component normalised to 0–10, then weighted.
        """
        if not self.outputs:
            return 0.0
        scores = []
        for out in self.outputs:
            caps = out.get("capability_match", [])
            risks = out.get("identified_risks", [])
            summary = out.get("exec_summary") or out.get("reasoning", "")
            # Capability depth: 0 caps=0, 3=5, 5=7, 7+=10
            cap_score = min(len(caps) * 1.5, 10.0)
            # Risk depth: 0=0, 1=3, 2=5, 3+=8
            risk_score = min(len(risks) * 2.5, 10.0)
            # Summary quality: length-based
            if len(summary) >= 200:
                summary_score = 9.0
            elif len(summary) >= 100:
                summary_score = 7.0
            elif len(summary) >= 50:
                summary_score = 5.0
            elif len(summary) > 0:
                summary_score = 3.0
            else:
                summary_score = 0.0
            depth = cap_score * 0.4 + risk_score * 0.3 + summary_score * 0.3
            scores.append(min(max(depth, 1.0), 10.0))
        return round(sum(scores) / len(scores), 2)

    def real_business_value(self):
        """
        1–10 composite score for business usefulness.
        Weighted combination:
          - decision_accuracy   40%  (normalised to 0–10)
          - strategic_depth     30%
          - relevance_score     30%  (already 0–10)
        """
        acc = self.decision_accuracy() * 10.0
        depth = self.strategic_depth_score()
        rel = self.relevance_score()
        value = acc * 0.4 + depth * 0.3 + rel * 0.3
        return round(min(max(value, 1.0), 10.0), 2)


# ---------------------------------------------------------------------------
# Utility: Pearson Correlation
# ---------------------------------------------------------------------------

def _pearson_correlation(x, y):
    """Compute Pearson r between two equal-length lists."""
    n = len(x)
    if n < 2:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    den_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)
