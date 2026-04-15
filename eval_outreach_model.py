"""
eval_outreach_model.py — One-shot evaluation comparing Sonnet vs Haiku for
outreach opening generation.

Runs 3 representative RFP scenarios × 2 models. Measures:
  - Output quality (naturalness, specificity, instruction compliance)
  - Token usage (input + output)
  - Estimated cost (USD) at published pricing

Usage:
    python3 eval_outreach_model.py

Requires ANTHROPIC_API_KEY in environment. Do NOT run in tests.
"""
import os
import time
from dotenv import load_dotenv

load_dotenv()

import anthropic  # noqa: E402
from src.config import CLIENT_NAME as _CLIENT_NAME

_SONNET = "claude-sonnet-4-6"
_HAIKU  = "claude-haiku-4-5-20251001"

# Pricing per million tokens (USD) — as of 2026-03-04
_PRICING = {
    _SONNET: {"input": 3.00,  "output": 15.00},
    _HAIKU:  {"input": 0.25,  "output": 1.25},
}

_SCENARIOS = [
    {
        "contact_name": "Sarah Mitchell",
        "contact_title": "Director of Digital Transformation",
        "rfp_title": "Enterprise Data Governance and Analytics Platform",
        "exec_summary": (
            "SaskBuilds is procuring a data governance and analytics platform to unify "
            "enterprise data assets across provincial ministries, with a target go-live of Q1 2027."
        ),
        "suggested_angle": (
            f"Lead with {_CLIENT_NAME}'s track record implementing data governance frameworks for "
            "Canadian provincial governments."
        ),
        "org": "SaskBuilds and Procurement",
    },
    {
        "contact_name": "James Okafor",
        "contact_title": "VP of Data Engineering",
        "rfp_title": "Data Analytics Platform Modernisation",
        "exec_summary": (
            "BC Hydro is modernising its enterprise analytics platform using Snowflake and Power BI "
            "to support operational reporting and grid-management insights."
        ),
        "suggested_angle": (
            f"Position {_CLIENT_NAME} as a Snowflake partner with utility-sector delivery experience."
        ),
        "org": "BC Hydro",
    },
    {
        "contact_name": "Priya Nair",
        "contact_title": "Chief Information Officer",
        "rfp_title": "Business Intelligence Dashboard Development",
        "exec_summary": (
            "City of Vancouver is building BI dashboards for city operations reporting across "
            "20+ departments, targeting Tableau and Power BI as delivery tools."
        ),
        "suggested_angle": (
            f"Highlight {_CLIENT_NAME}'s municipal BI experience and rapid dashboard delivery capability."
        ),
        "org": "City of Vancouver",
    },
]

_PROMPT_TEMPLATE = """\
You are writing a personalised email opening for business development outreach \
on behalf of {client_name}, a Canadian data and analytics consultancy.

Write exactly 2 sentences that:
- Reference the specific RFP "{rfp_title}" by name
- Connect directly to {contact_name}'s role as {contact_title}
- Sound human, natural and specific — not templated or generic
- Show awareness of the opportunity context: {exec_summary}
- Reflect this suggested angle: {suggested_angle}

Do NOT:
- Use generic phrases like "I hope this finds you well" or "I am reaching out"
- Mention any competitors
- Make unverifiable claims about {client_name}

Write only the 2-sentence opening. No greeting, no subject line, no closing.\
"""

def _cost(model, in_tokens, out_tokens):
    p = _PRICING[model]
    return (in_tokens / 1_000_000) * p["input"] + (out_tokens / 1_000_000) * p["output"]


def run_scenario(client, model, scenario):
    prompt = _PROMPT_TEMPLATE.format(client_name=_CLIENT_NAME, **scenario)
    t0 = time.monotonic()
    resp = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.monotonic() - t0
    in_tok  = resp.usage.input_tokens
    out_tok = resp.usage.output_tokens
    text    = resp.content[0].text.strip()
    cost_usd = _cost(model, in_tok, out_tok)
    return {
        "text": text,
        "in_tok": in_tok,
        "out_tok": out_tok,
        "cost_usd": cost_usd,
        "latency_s": round(elapsed, 2),
    }


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    client = anthropic.Anthropic(api_key=api_key)

    print("=" * 72)
    print("OUTREACH MODEL EVALUATION — Sonnet vs Haiku")
    print("3 scenarios × 2 models = 6 API calls")
    print("=" * 72)

    totals = {_SONNET: {"in": 0, "out": 0, "cost": 0.0}, _HAIKU: {"in": 0, "out": 0, "cost": 0.0}}

    for i, scenario in enumerate(_SCENARIOS, 1):
        print(f"\n{'─' * 72}")
        print(f"SCENARIO {i}: {scenario['rfp_title']} — {scenario['contact_name']} ({scenario['contact_title']})")
        print(f"{'─' * 72}")

        for model, label in [(_SONNET, "SONNET (current)"), (_HAIKU, "HAIKU  (proposed)")]:
            r = run_scenario(client, model, scenario)
            totals[model]["in"]   += r["in_tok"]
            totals[model]["out"]  += r["out_tok"]
            totals[model]["cost"] += r["cost_usd"]

            print(f"\n  [{label}]  {r['latency_s']}s  |  {r['in_tok']} in / {r['out_tok']} out  |  ${r['cost_usd']:.5f}")
            print(f"  Output: {r['text']}")

    print(f"\n{'=' * 72}")
    print("AGGREGATE COST SUMMARY (3 scenarios)")
    print(f"{'=' * 72}")
    for model, label in [(_SONNET, "Sonnet (current) "), (_HAIKU, "Haiku  (proposed)")]:
        t = totals[model]
        print(f"  {label}  {t['in']} in / {t['out']} out  |  total cost ${t['cost']:.5f}")

    sonnet_cost = totals[_SONNET]["cost"]
    haiku_cost  = totals[_HAIKU]["cost"]
    if sonnet_cost > 0:
        savings_pct = (1 - haiku_cost / sonnet_cost) * 100
        print(f"\n  Cost reduction:  {savings_pct:.0f}%  (${sonnet_cost - haiku_cost:.5f} saved per 3 contacts)")
        # Scale to a realistic daily volume: assume 10 opportunities × 3 contacts
        daily_sonnet = sonnet_cost / 3 * 30
        daily_haiku  = haiku_cost  / 3 * 30
        print(f"  Projected daily (30 contacts): Sonnet ${daily_sonnet:.4f}  →  Haiku ${daily_haiku:.4f}")

    print()


if __name__ == "__main__":
    main()
