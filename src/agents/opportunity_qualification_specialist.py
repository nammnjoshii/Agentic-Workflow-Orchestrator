import logging
import os
import time

import anthropic

from src.database import has_score, get_filter_result, save_filter_result, get_raw_listings
from src.config import CLIENT_NAME as _CLIENT_NAME, CLIENT_DESCRIPTION as _CLIENT_DESCRIPTION

logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
FILTER_THRESHOLD = int(os.environ.get("FILTER_THRESHOLD", 60))
_MODEL = "claude-haiku-4-5-20251001"

_PROMPT_TEMPLATE = """\
Rate how well this procurement opportunity matches """ + _CLIENT_DESCRIPTION + """.
Reply with a single integer from 0 to 100 only. No explanation.

Title: {title}
Organisation: {org}
Description: {description}"""


def _call_haiku(client, listing, _usage_collector=None):
    """Call Haiku and return an integer score 0-100. Raises on API failure."""
    prompt = _PROMPT_TEMPLATE.format(
        title=listing["title"],
        org=listing["org"],
        description=(listing.get("raw_description") or "")[:500],
    )
    message = client.messages.create(
        model=_MODEL,
        max_tokens=8,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = getattr(message, "usage", None)
    if _usage_collector is not None and usage is not None:
        _usage_collector.append(usage)
    raw = message.content[0].text.strip()
    return int(raw)


def _call_haiku_with_retry(client, listing, max_retries=3, _usage_collector=None):
    """Call Haiku with exponential backoff on rate-limit errors only."""
    for attempt in range(max_retries):
        try:
            return _call_haiku(client, listing, _usage_collector=_usage_collector)
        except anthropic.RateLimitError:
            wait = 2 ** attempt
            logger.warning("[FILTER] rate limited — waiting %ds (attempt %d)", wait, attempt + 1)
            time.sleep(wait)
    raise RuntimeError("[FILTER] Haiku call failed after max retries")


class OpportunityQualificationSpecialist:
    def __init__(self):
        self._client = anthropic.Anthropic()

    def run(self, state: dict) -> dict:
        state.setdefault("filtered", [])
        state.setdefault("skipped", [])

        listings = state.get("listings") or []
        if not listings:
            listings = get_raw_listings()
            if listings:
                logger.info(
                    "[FILTER] state['listings'] empty — loaded %d from raw_listings DB",
                    len(listings),
                )
                state["listings"] = listings
        passed = 0
        dropped = 0
        tokens_in = 0
        tokens_out = 0

        for listing in listings:
            url = listing["url"]

            # Cache hit — already deep-scored, pass straight through
            if has_score(url):
                state["filtered"].append(listing)
                passed += 1
                continue

            # DRY_RUN — no API calls
            if DRY_RUN:
                listing["filter_score"] = 75
                state["filtered"].append(listing)
                passed += 1
                continue

            # Filter cache hit — reuse persisted Haiku result from a previous run
            cached_score = get_filter_result(url)
            if cached_score is not None:
                listing["filter_score"] = cached_score
                if cached_score >= FILTER_THRESHOLD:
                    state["filtered"].append(listing)
                    passed += 1
                else:
                    state["skipped"].append({
                        **listing,
                        "skip_reason": "below filter threshold (cached)",
                        "filter_score": cached_score,
                    })
                    dropped += 1
                continue

            # Haiku filter call
            usage_collector = []
            try:
                score = _call_haiku_with_retry(self._client, listing,
                                               _usage_collector=usage_collector)
            except Exception as exc:
                logger.warning("[FILTER] API failure for %s: %s — defaulting to 50", url, exc)
                score = 50
            for u in usage_collector:
                tokens_in += getattr(u, "input_tokens", 0)
                tokens_out += getattr(u, "output_tokens", 0)

            listing["filter_score"] = score
            save_filter_result(url, listing, score)

            if score >= FILTER_THRESHOLD:
                state["filtered"].append(listing)
                passed += 1
            else:
                state["skipped"].append({
                    **listing,
                    "skip_reason": "below filter threshold",
                    "filter_score": score,
                })
                dropped += 1

        logger.info("[FILTER] %d passed, %d dropped", passed, dropped)
        state.setdefault("token_usage", {})[self.__class__.__name__] = {
            "input": tokens_in,
            "output": tokens_out,
        }
        return state

