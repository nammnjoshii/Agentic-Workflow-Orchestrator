"""
Portal-specific compiled regex patterns for RFP section extraction.
Used by extraction_utils.extract_rfp_content() to boost section recall on known portal formats.

Supported portals: MERX, CanadaBuys, BCBid, RFPMart.
Falls back to an empty list for unknown portals — never raises.
"""
import re

# ---------------------------------------------------------------------------
# Per-portal pattern sets
# ---------------------------------------------------------------------------

# MERX: numbered headings "1. Scope" or "Scope:" labels
_MERX = [
    re.compile(
        r"^\d+[\.\)]\s*(scope|background|objectives?|requirements?|"
        r"eligibility|evaluation|deliverables?|qualifications?)",
        re.I | re.M,
    ),
    re.compile(
        r"^(scope|background|objectives?|requirements?|eligibility|"
        r"evaluation|deliverables?|qualifications?)\s*:",
        re.I | re.M,
    ),
]

# CanadaBuys: all-caps section headers, possibly with trailing whitespace
_CANADA_BUYS = [
    re.compile(
        r"^(SCOPE|BACKGROUND|OBJECTIVES?|REQUIREMENTS?|ELIGIBILITY|"
        r"EVALUATION|DELIVERABLES?|QUALIFICATIONS?)\s*$",
        re.M,
    ),
    re.compile(r"^[A-Z][A-Z\s]{3,35}$", re.M),
]

# BCBid: dash-prefixed labels or "Section N:" style
_BCBID = [
    re.compile(
        r"^[-–]\s*(scope|background|objectives?|requirements?|"
        r"evaluation|deliverables?|qualifications?)",
        re.I | re.M,
    ),
    re.compile(
        r"Section\s+\d+[:\s]+(scope|background|requirements?|evaluation|deliverables?)",
        re.I,
    ),
]

# RFPMart: prose labels identifying key sections (HTML-stripped text)
_RFPMART = [
    re.compile(
        r"(scope of work|statement of work|project background|"
        r"evaluation criteria|mandatory requirements?|rated criteria)",
        re.I,
    ),
    re.compile(
        r"(key deliverables?|project objectives?|vendor requirements?|"
        r"technical requirements?|functional requirements?)",
        re.I,
    ),
]

_PROFILES: dict[str, list] = {
    "merx": _MERX,
    "canadabuys": _CANADA_BUYS,
    "bcbid": _BCBID,
    "rfpmart": _RFPMART,
}


def _normalise_source(source: str) -> str:
    """Lowercase and strip non-alpha chars for fuzzy portal matching."""
    return re.sub(r"[^a-z]", "", (source or "").lower())


def get_regex_profile(source: str) -> list:
    """Return compiled regex patterns for the given portal source name.

    Falls back to an empty list for unknown portals — never raises.
    """
    key = _normalise_source(source)
    for portal, patterns in _PROFILES.items():
        if portal in key:
            return patterns
    return []


def find_regex_hits(text: str, source: str) -> list[str]:
    """Return text spans (up to 600 chars each) that follow regex pattern matches.

    Used by extract_rfp_content() to inject portal-specific section anchors
    into the extraction candidate pool.
    """
    patterns = get_regex_profile(source)
    hits: list[str] = []
    for pattern in patterns:
        for m in pattern.finditer(text):
            span_start = m.start()
            span_end = min(len(text), m.end() + 600)
            hits.append(text[span_start:span_end])
    return hits
