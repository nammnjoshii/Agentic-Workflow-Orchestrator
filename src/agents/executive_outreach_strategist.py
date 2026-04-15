import logging
import os
import re
import time

import anthropic

from src.config import CLIENT_NAME as _CLIENT_NAME, CLIENT_DESCRIPTION as _CLIENT_DESCRIPTION

logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 200


def _sanitise_rfp_title(title: str) -> str:
    """Strip content after '---' or after 'ignore' (case-insensitive)."""
    if "---" in title:
        title = title.split("---")[0]
    match = re.search(r"\bignore\b", title, re.IGNORECASE)
    if match:
        title = title[: match.start()]
    return title.strip()


def generate_outreach(
    contact_name: str,
    contact_title: str,
    rfp_title: str,
    exec_summary: str,
    suggested_angle: str,
    org: str = "",
    client=None,
    _usage_collector=None,
) -> str:
    """Generate a personalised 2-sentence email opening. Never raises."""
    fallback = (
        f"I noticed your team at {org} has an open procurement for {rfp_title} "
        f"and wanted to introduce {_CLIENT_NAME}'s relevant experience in this area."
    )

    if DRY_RUN:
        logger.info("[OUTREACH] fallback used for %s", contact_name)
        return fallback

    if not all([contact_name, contact_title, rfp_title, exec_summary, suggested_angle]):
        logger.info("[OUTREACH] fallback used for %s", contact_name)
        return fallback

    sanitised_title = _sanitise_rfp_title(rfp_title)

    prompt = (
        f"You are writing a personalised email opening for business development outreach "
        f"on behalf of {_CLIENT_NAME}, {_CLIENT_DESCRIPTION}.\n\n"
        "Write exactly 2 sentences that:\n"
        f'- Reference the specific RFP "{sanitised_title}" by name\n'
        f"- Connect directly to {contact_name}'s role as {contact_title}\n"
        "- Sound human, natural and specific — not templated or generic\n"
        f"- Show awareness of the opportunity context: {exec_summary}\n"
        f"- Reflect this suggested angle: {suggested_angle}\n\n"
        "Do NOT:\n"
        '- Use generic phrases like "I hope this finds you well" or "I am reaching out"\n'
        "- Mention any competitors\n"
        f"- Make unverifiable claims about {_CLIENT_NAME}\n"
        f"- Reference specific years of {_CLIENT_NAME}'s experience or history\n\n"
        "Write only the 2-sentence opening. No greeting, no subject line, no closing."
    )

    if client is None:
        client = anthropic.Anthropic()
    for attempt in range(3):
        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = getattr(response, "usage", None)
            if _usage_collector is not None and usage is not None:
                _usage_collector.append(usage)
            opening = response.content[0].text.strip()
            logger.info("[OUTREACH] generated for %s at %s", contact_name, org)
            return opening
        except anthropic.RateLimitError:
            wait = 2 ** attempt
            logger.warning("[OUTREACH] rate limited — waiting %ds (attempt %d)", wait, attempt + 1)
            time.sleep(wait)
        except Exception as exc:
            logger.warning("[OUTREACH] API failed for %s: %s — using fallback", contact_name, exc)
            break
    logger.info("[OUTREACH] fallback used for %s", contact_name)
    return fallback


class ExecutiveOutreachStrategist:
    def __init__(self):
        self._client = anthropic.Anthropic()

    def run(self, state):
        state.setdefault("ready", [])
        tokens_in = 0
        tokens_out = 0

        for opportunity in state.get("enriched", []):
            org = opportunity.get("org", "")
            rfp_title = opportunity.get("title", "")
            exec_summary = opportunity.get("exec_summary", "")
            suggested_angle = opportunity.get("suggested_angle", "")
            contacts = opportunity.get("contacts", [])

            for i, contact in enumerate(contacts):
                usage_collector = []
                opening = generate_outreach(
                    contact_name=contact.get("name", ""),
                    contact_title=contact.get("title", ""),
                    rfp_title=rfp_title,
                    exec_summary=exec_summary,
                    suggested_angle=suggested_angle,
                    org=org,
                    client=self._client,
                    _usage_collector=usage_collector,
                )
                for u in usage_collector:
                    tokens_in += getattr(u, "input_tokens", 0)
                    tokens_out += getattr(u, "output_tokens", 0)
                contact["outreach_opening"] = opening

            state["ready"].append(opportunity)

        state.setdefault("token_usage", {})[self.__class__.__name__] = {
            "input": tokens_in,
            "output": tokens_out,
        }
        return state

