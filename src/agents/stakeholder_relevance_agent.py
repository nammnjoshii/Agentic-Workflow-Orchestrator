import concurrent.futures
import logging
import os
import re

from src.agents.stakeholder_intelligence_specialist import enrich_opportunity

logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
_MAX_RETRIES = 2
_MIN_SCORE = 30
_MAX_CONTACTS = 3

# ---------------------------------------------------------------------------
# Stop words excluded from proximity comparison to prevent false matches
# ---------------------------------------------------------------------------
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "for", "in", "at", "by",
    "to", "with", "on", "is", "are", "be", "as", "it", "its",
}

# ---------------------------------------------------------------------------
# Seniority tiers — raw 0–100, first match wins (highest tier first)
# Weighted contribution: raw * 0.30
# ---------------------------------------------------------------------------
_SENIORITY_TIERS = [
    # Tier 1 — decision authority: C-suite, VP, Director, Deputy/Assistant Minister
    (100, {"chief", "vp", "vice", "president", "director", "minister"}),
    # Tier 2 — senior IC / practice lead / enterprise architect
    (62,  {"head", "senior", "lead", "enterprise", "architect"}),
    (37,  {"manager"}),
    (12,  {"advisor", "specialist", "coordinator"}),
]

# ---------------------------------------------------------------------------
# Domain tiers — raw 0–100, first match wins
# Weighted contribution: raw * 0.25
# ---------------------------------------------------------------------------
_DOMAIN_TIERS = [
    # Tier 1 — core data/analytics/AI scope
    (100, {
        "data", "analytics", "ai", "cloud", "machine", "learning", "intelligence",
        "engineering", "science", "governance", "platform", "decision",
    }),
    # Tier 2 — adjacent technology / strategy / digital scope
    (75,  {
        "technology", "it", "digital", "innovation", "transformation", "systems",
        "strategy", "services", "performance", "evaluation", "policy",
        "architecture", "architect", "information",
    }),
    # Tier 3 — operational/financial roles: relevant but not primary targets
    (25,  {"procurement", "finance", "financial", "operations", "business"}),
]


def _title_words(contact: dict) -> set[str]:
    """Return meaningful lowercase words in a contact's title (stop words excluded)."""
    return set(re.findall(r"\b\w+\b", (contact.get("title") or "").lower())) - _STOP_WORDS


def _seniority_score(words: set[str]) -> int:
    """Raw seniority score 0–100; first matching tier wins."""
    for score, terms in _SENIORITY_TIERS:
        if words & terms:
            return score
    return 0


def _domain_score(words: set[str]) -> int:
    """Raw domain alignment score 0–100; first matching tier wins."""
    for score, terms in _DOMAIN_TIERS:
        if words & terms:
            return score
    return 0


def _activity_signals_score(contact: dict, org_domain: str = "") -> int:
    """Raw activity signals score 0–100 based on LinkedIn and email presence.

    LinkedIn: only /in/ person profile URLs score (33 pts); /company/ pages do not.
    Email: 67 pts. Domain-match bonus removed — that signal lives in _org_affiliation_score.
    Both email + LinkedIn: 100 pts (capped).
    """
    score = 0
    li = contact.get("linkedin_url") or ""
    if li and "/in/" in li:
        score += 33
    email = contact.get("email") or ""
    if email:
        score += 67
    return min(100, score)


def _org_affiliation_score(contact: dict, org_domain: str = "") -> int:
    """Score 0–100 indicating confidence this contact currently works at the target org.

    email domain matches org domain → 100  (verified current employee)
    source == "website"             →  90  (found on org's own leadership page)
    source in ("hunter", "apollo")  →  75  (domain-searched — high confidence current)
    source == "linkedin"            →  50  (org-name search — may be former employee)
    unknown / no source             →  50  (neutral — we cannot tell)
    """
    email = contact.get("email") or ""
    if org_domain and email.endswith(f"@{org_domain}"):
        return 100
    source = (contact.get("source") or "").lower()
    if source == "website":
        return 90
    if source in ("hunter", "apollo"):
        return 75
    if source == "linkedin":
        return 50
    return 50  # neutral


def _org_proximity_score(words: set[str], suggested_angle: str, exec_summary: str) -> int:
    """Graded org proximity score 0–100 based on meaningful title word overlap with opportunity context.

    Stop words are excluded from both sides before comparison.
    Overlap count:  0 → 0,  1 → 40,  2 → 70,  3+ → 100.
    """
    context_text = f"{suggested_angle} {exec_summary}".lower()
    context_words = set(re.findall(r"\b\w+\b", context_text)) - _STOP_WORDS
    overlap = len(words & context_words)
    if overlap >= 3:
        return 100
    if overlap == 2:
        return 70
    if overlap == 1:
        return 40
    return 0


def _score_contact(
    contact: dict,
    suggested_angle: str = "",
    exec_summary: str = "",
    org_domain: str = "",
) -> tuple[int, int, int, int, int, int]:
    """Compute 5-component weighted relevance score for a contact.

    Returns (seniority_raw, domain_raw, signals_raw, affiliation_raw, proximity_raw, final_score).

    Weighted composite (research-grounded: government/corporate bid intelligence):
        seniority_weight     25% — CIO/Director has formal mandate authority
        domain_weight        20% — data/analytics/IT domain alignment
        affiliation_weight   25% — is this person currently at the target org?
        signals_weight       10% — reachability (email + LinkedIn)
        proximity_weight     20% — title keywords match RFP context (bid-specific fit)
    Total: 0–100
    """
    words = _title_words(contact)

    s_raw = _seniority_score(words)
    d_raw = _domain_score(words)
    a_raw = _activity_signals_score(contact)
    aff_raw = _org_affiliation_score(contact, org_domain)
    p_raw = _org_proximity_score(words, suggested_angle, exec_summary)

    final = int(round(min(100.0,
        s_raw * 0.25
        + d_raw * 0.20
        + aff_raw * 0.25
        + a_raw * 0.10
        + p_raw * 0.20
    )))
    return s_raw, d_raw, a_raw, aff_raw, p_raw, final


class StakeholderRelevanceAgent:
    def run(self, state: dict) -> dict:
        state.setdefault("enriched", [])

        # URL → item lookup for org name and metadata
        items_by_url = {item["url"]: item for item in state.get("validated", [])}

        for url, enriched in state.get("contacts", {}).items():
            item = items_by_url.get(url, {})
            org = item.get("org", url)

            # DRY_RUN — assign fixed relevance_score=80, skip scoring and retries
            if DRY_RUN:
                contacts = list(enriched.get("contacts", []))
                for c in contacts:
                    c["relevance_score"] = 80
                logger.info(
                    "[CRITIC-CONTACT] %d contacts for %s — relevance_score=80 (DRY_RUN)",
                    len(contacts), org,
                )
                state["enriched"].append({**item, **enriched, "contacts": contacts})
                continue

            suggested_angle = item.get("suggested_angle", "")
            exec_summary = item.get("exec_summary", "")
            org_domain = enriched.get("domain") or ""
            contacts = list(enriched.get("contacts", []))
            loops = 0

            # Score, log per-contact, sort and slice initial contact set
            for c in contacts:
                s_raw, d_raw, a_raw, aff_raw, p_raw, final = _score_contact(
                    c, suggested_angle, exec_summary, org_domain
                )
                c["relevance_score"] = final
                logger.debug(
                    "[CONTACT-SCORE] %s | seniority=%d domain=%d affiliation=%d signals=%d proximity=%d final=%d",
                    c.get("name", "unknown"), s_raw, d_raw, aff_raw, a_raw, p_raw, final,
                )

            contacts.sort(key=lambda c: c["relevance_score"], reverse=True)
            contacts = contacts[:_MAX_CONTACTS]

            # Retry if all contacts score below threshold
            _retry_timeout = int(os.environ.get("CONTACT_ORG_TIMEOUT_SECONDS", 60))
            while (not contacts or contacts[0]["relevance_score"] < _MIN_SCORE) and loops < _MAX_RETRIES:
                loops += 1
                logger.info(
                    "[CRITIC-CONTACT] all contacts score <%d for %s (loop %d) — retrying enrichment",
                    _MIN_SCORE, org, loops,
                )
                # Use ThreadPoolExecutor + shutdown(wait=False) — same pattern as
                # StakeholderIntelligenceSpecialist — so IPv6 SYN_SENT hangs don't
                # block the pipeline indefinitely.
                _ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                _fut = _ex.submit(
                    enrich_opportunity,
                    org=org,
                    title=item.get("title", ""),
                    exec_summary=exec_summary,
                    suggested_angle=suggested_angle,
                    location=item.get("location", ""),
                )
                try:
                    retry_result = _fut.result(timeout=_retry_timeout)
                    _ex.shutdown(wait=False)
                except concurrent.futures.TimeoutError:
                    logger.warning(
                        "[CRITIC-CONTACT] retry for '%s' timed out after %ds — skipping retries",
                        org, _retry_timeout,
                    )
                    _ex.shutdown(wait=False)
                    break
                if retry_result:
                    enriched = {**enriched, **retry_result}
                org_domain = enriched.get("domain") or org_domain
                contacts = list(enriched.get("contacts", []))
                for c in contacts:
                    s_raw, d_raw, a_raw, aff_raw, p_raw, final = _score_contact(
                        c, suggested_angle, exec_summary, org_domain
                    )
                    c["relevance_score"] = final
                    logger.debug(
                        "[CONTACT-SCORE] %s | seniority=%d domain=%d affiliation=%d signals=%d proximity=%d final=%d",
                        c.get("name", "unknown"), s_raw, d_raw, aff_raw, a_raw, p_raw, final,
                    )
                contacts.sort(key=lambda c: c["relevance_score"], reverse=True)
                contacts = contacts[:_MAX_CONTACTS]

            if not contacts or contacts[0]["relevance_score"] < _MIN_SCORE:
                logger.warning("[CRITIC-CONTACT] [WARN] no valid contacts: %s", org)
            else:
                scores = [c["relevance_score"] for c in contacts]
                logger.info(
                    "[CRITIC-CONTACT] %d contacts for %s — scores: %s",
                    len(contacts), org, scores,
                )

            state["enriched"].append({
                **item,
                **enriched,
                "contacts": contacts,
            })

        return state

