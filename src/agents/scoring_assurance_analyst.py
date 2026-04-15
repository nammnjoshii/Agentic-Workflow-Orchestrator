import json
import logging
import os
import re

import anthropic

logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
_MODEL = "claude-sonnet-4-6"
_MAX_RETRIES = 2

_CALIBRATION_PATH = os.environ.get(
    "CALIBRATION_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "calibration_set.json"),
)

_RESCORE_PROMPT = """\
The previous scoring response failed validation. Re-score this RFP and return valid JSON.

Validation failures:
{failures}

Original listing:
Title: {title}
Organisation: {org}
Description: {description}

Return a JSON object with exactly these 9 keys:
{{
  "relevance_score":  integer 0-100,
  "recommendation":   "PURSUE" | "CONSIDER" | "SKIP",
  "score_rationale":  string (2 sentences max),
  "capability_match": [list of matched capability items],
  "risks":            [list of disqualifying or limiting factors],
  "estimated_effort": "S" | "M" | "L" | "XL",
  "exec_summary":     string (3 sentences max),
  "suggested_angle":  string (1 sentence),
  "decision_log":     []
}}

Score bands: 75-100 = PURSUE, 50-74 = CONSIDER, 0-49 = SKIP.
Reply with valid JSON only — no markdown fences."""

_DISQUALIFIERS = [
    "civil engineering", "construction", "physical infrastructure",
    "hardware procurement", "physical asset management",
    "medical devices", "clinical healthcare",
    "legal services", "court administration",
    "staffing-only",
]


def _load_golden_set() -> list:
    path = os.path.normpath(_CALIBRATION_PATH)
    if not os.path.exists(path):
        logger.warning("[WARN] calibration file not found — skipping")
        return []
    with open(path) as f:
        return json.load(f)


def _validate(scored: dict) -> list:
    """Return list of failure messages; empty list means valid."""
    failures = []

    score = scored.get("relevance_score")
    if not isinstance(score, int) or not (0 <= score <= 100):
        failures.append(f"relevance_score must be integer 0-100, got {score!r}")
        return failures  # remaining checks need a valid score

    rec = scored.get("recommendation")
    if score >= 75 and rec != "PURSUE":
        failures.append(f"score {score} requires PURSUE, got {rec!r}")
    elif 50 <= score < 75 and rec != "CONSIDER":
        failures.append(f"score {score} requires CONSIDER, got {rec!r}")
    elif score < 50 and rec != "SKIP":
        failures.append(f"score {score} requires SKIP, got {rec!r}")

    if score >= 60 and not scored.get("capability_match"):
        failures.append("capability_match must not be empty when score >= 60")

    if score > 30:
        check_text = " ".join([
            scored.get("score_rationale", ""),
            scored.get("exec_summary", ""),
            " ".join(scored.get("risks", [])),
        ]).lower()
        for dq in _DISQUALIFIERS:
            if dq in check_text:
                failures.append(f"disqualifier '{dq}' present but score > 30")
                break

    # Validate opportunity_priority_score
    priority = scored.get("opportunity_priority_score")
    if priority is not None and (not isinstance(priority, int) or not (0 <= priority <= 100)):
        failures.append(
            f"opportunity_priority_score must be int 0-100, got {priority!r}"
        )

    return failures


def _calibration_check(scored: dict, golden_set: list):
    """Return a warning string if score deviates >15 pts from closest golden match, else None."""
    keywords = set()
    for field in ("score_rationale", "exec_summary", "suggested_angle"):
        keywords.update(scored.get(field, "").lower().split())
    keywords.update(w.lower() for w in scored.get("capability_match", []))

    matches = [
        g for g in golden_set
        if g.get("active")
        and len(set(w.lower() for w in g["domain_keywords"]) & keywords) >= 1
    ]
    if not matches:
        return None

    closest = min(matches, key=lambda g: abs(g["expected_score"] - scored["relevance_score"]))
    delta = abs(closest["expected_score"] - scored["relevance_score"])
    if delta > 15:
        return f"score {scored['relevance_score']} deviates {delta}pt from golden-{closest['id']}"
    return None


def _rescore(client, listing: dict, failures: list) -> dict:
    context_parts = [
        f"Value: {listing.get('value', 'not specified')}",
        f"Deadline: {listing.get('deadline', 'unknown')}",
        f"Capability matches from prior score: {listing.get('capability_match', [])}",
        f"Risks from prior score: {listing.get('risks', [])}",
        f"Prior rationale: {listing.get('score_rationale', '')}",
        f"Description: {(listing.get('raw_description') or '')[:1000]}",
    ]
    prompt = _RESCORE_PROMPT.format(
        failures="\n".join(f"- {f}" for f in failures),
        title=listing.get("title", ""),
        org=listing.get("org", ""),
        description="\n".join(context_parts),
    )
    message = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = getattr(message, "usage", None)
    raw = message.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw).strip()
    return json.loads(raw), usage


class ScoringAssuranceAnalyst:
    def __init__(self):
        self._client = anthropic.Anthropic()
        self._golden_set = _load_golden_set()

    def run(self, state: dict) -> dict:
        state.setdefault("validated", [])
        tokens_in = 0
        tokens_out = 0

        for item in state.get("scored", []):
            # DRY_RUN — pass everything through without validation
            if DRY_RUN:
                state["validated"].append(item)
                logger.info("[CRITIC-SCORE] accepted (DRY_RUN) %s", item.get("title", ""))
                continue

            scored = {k: item[k] for k in (
                "relevance_score", "recommendation", "score_rationale",
                "capability_match", "risks", "estimated_effort",
                "exec_summary", "suggested_angle", "decision_log",
                "opportunity_priority_score",
            ) if k in item}

            loops = 0
            failures = _validate(scored)

            while failures and loops < _MAX_RETRIES:
                logger.info(
                    "[CRITIC-SCORE] retrying %s (loop %d): %s",
                    item.get("title", ""), loops + 1, "; ".join(failures),
                )
                try:
                    rescored, usage = _rescore(self._client, item, failures)
                    if usage:
                        tokens_in += getattr(usage, "input_tokens", 0)
                        tokens_out += getattr(usage, "output_tokens", 0)
                    scored.update(rescored)
                    # Re-compute priority score after rescore
                    if "opportunity_priority_score" not in rescored:
                        from src.agents.strategic_scoring_agent import compute_priority_score
                        scored["opportunity_priority_score"] = compute_priority_score(item, scored)
                    failures = _validate(scored)
                    loops += 1
                except Exception as exc:
                    logger.warning("[CRITIC-SCORE] rescore failed: %s", exc)
                    break

            if failures:
                logger.warning(
                    "[CRITIC-SCORE] flagged %s after %d loops: %s",
                    item.get("title", ""), loops, "; ".join(failures),
                )
                scored.setdefault("decision_log", [])
                scored["decision_log"].append({"warn": "critic_capped"})
            else:
                logger.info("[CRITIC-SCORE] accepted %s", item.get("title", ""))

            # Calibration check — runs after schema/band validation only
            calib_warn = _calibration_check(scored, self._golden_set)
            if calib_warn:
                scored.setdefault("decision_log", [])
                scored["decision_log"].append({"warn": "calibration_delta", "delta": calib_warn})
                logger.warning("[CRITIC-SCORE] calibration warning: %s", calib_warn)

            state["validated"].append({**item, **scored})

        state.setdefault("token_usage", {})[self.__class__.__name__] = {
            "input": tokens_in,
            "output": tokens_out,
        }
        return state

