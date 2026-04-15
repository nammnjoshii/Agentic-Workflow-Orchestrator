import html as _html_lib
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from src.config import CLIENT_NAME as _CLIENT_NAME
from src.database import (
    get_opportunities_for_digest,
    get_all_pursue_consider,
    get_contacts_for_opportunity,
    get_scrape_stats,
)

logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(text):
    """HTML-escape a value for safe inline insertion."""
    return _html_lib.escape(str(text or ""))


def _week_of(dt=None):
    """Return 'Mon DD, YYYY' for the Monday of the given (or current) week."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%b %d, %Y")


def _priority_badge_color(priority_score: int) -> str:
    """Return inline CSS background-color hex for the PRIORITY badge."""
    if priority_score >= 80:
        return "#15803d"  # deep green
    if priority_score >= 60:
        return "#1d4ed8"  # blue
    if priority_score >= 40:
        return "#b45309"  # amber
    return "#6b7280"      # gray


def _combined_score(opp, contacts):
    """Combined score: 70% listing priority + 30% avg contact relevance.

    Listings without contacts receive a −15 penalty so they sort below
    listings where stakeholders were found.
    """
    listing_score = int(opp.get("opportunity_priority_score") or 0)
    if contacts:
        avg_contact = sum(c.get("relevance_score") or 0 for c in contacts) / len(contacts)
        raw = listing_score * 0.70 + avg_contact * 0.30
    else:
        raw = listing_score * 0.70 - 15
    return int(round(min(100.0, max(0.0, raw))))


def _build_stats(opportunities, contacts_by_id, state):
    """Assemble footer stats from live pipeline state when available, DB otherwise.

    The scrape job passes a populated state; the digest job passes {}.
    When state has no live data, fall back to DB queries so the footer
    always shows real counts rather than zeros.
    """
    all_contacts = [c for cs in contacts_by_id.values() for c in cs]
    drafts = sum(1 for c in all_contacts if c.get("outreach_opening"))

    if state.get("listings") is not None and len(state["listings"]) > 0:
        # Live scrape run — use in-memory state
        pursue = sum(1 for o in opportunities if o.get("recommendation") == "PURSUE")
        consider = sum(1 for o in opportunities if o.get("recommendation") == "CONSIDER")
        skip = sum(1 for o in state.get("scored", []) if o.get("recommendation") == "SKIP")
        return {
            "scraped": len(state["listings"]),
            "filtered": len(state.get("filtered", [])),
            "pursue": pursue,
            "consider": consider,
            "skip": skip,
            "contacts": len(all_contacts),
            "drafts": drafts,
        }

    # Digest job — pull real counts from the DB
    db = get_scrape_stats()
    return {
        "scraped": db["scraped"],
        "filtered": db["filtered"],
        "pursue": db["pursue"],
        "consider": db["consider"],
        "skip": db["skip"],
        "contacts": len(all_contacts),
        "drafts": drafts,
    }


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def _opp_section(opp, contacts, override_score=None):
    """Return HTML string for a single opportunity card.

    Includes a colour-coded PRIORITY badge next to the title.
    override_score: if provided, used as the displayed score instead of
    opportunity_priority_score (used by force-send combined scoring).
    All CSS is inline — no <style> tags (stripped by Gmail / Outlook).
    """
    rec = opp.get("recommendation", "")
    priority_score = override_score if override_score is not None else int(opp.get("opportunity_priority_score") or 0)

    rec_label = rec.capitalize()  # "Pursue" / "Consider" / "Skip"
    rec_badge_bg = (
        "#172C51" if rec == "PURSUE"
        else "#2D73C4" if rec == "CONSIDER"
        else "#94a3b8"
    )
    priority_badge_bg = _priority_badge_color(priority_score)

    rows = []

    # Recommendation badge + title + score badge row
    rows.append(
        f'<tr><td style="padding:24px 32px 0;">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
        f'<td style="vertical-align:top;width:72px;">'
        f'<div style="background:{rec_badge_bg};border-radius:6px;padding:6px 10px;'
        f'text-align:center;color:#ffffff;font-size:13px;font-weight:700;white-space:nowrap;">'
        f'{rec_label}</div></td>'
        f'<td style="vertical-align:top;padding-left:12px;">'
        f'<h2 style="margin:0 0 4px;font-size:17px;color:#1a202c;line-height:1.3;">'
        f'{_esc(opp.get("title", ""))}'
        f'<span style="display:inline-block;background:{priority_badge_bg};border-radius:4px;'
        f'padding:2px 8px;font-size:11px;font-weight:700;color:#ffffff;'
        f'margin-left:10px;vertical-align:middle;">'
        f'Score {priority_score}</span>'
        f'</h2>'
        f'<p style="margin:0;font-size:13px;color:#718096;">'
        f'{_esc(opp.get("org", ""))}'
    )
    if opp.get("deadline"):
        rows.append(f' &nbsp;&middot;&nbsp; Deadline: {_esc(opp["deadline"])}')
    value = (opp.get("value") or "").strip()
    if value and value.lower() != "not specified":
        rows.append(f' &nbsp;&middot;&nbsp; Contract Value: {_esc(value)}')
    rows.append('</p></td></tr></table>')

    # exec_summary
    if opp.get("exec_summary"):
        rows.append(
            f'<p style="margin:12px 0 0;font-size:14px;color:#4a5568;line-height:1.6;">'
            f'{_esc(opp["exec_summary"])}</p>'
        )

    # RFP link
    if opp.get("url"):
        rows.append(
            f'<p style="margin:10px 0 0;">'
            f'<a href="{_esc(opp["url"])}" style="color:#4f46e5;font-size:13px;text-decoration:none;">'
            f'View RFP &rarr;</a></p>'
        )

    # Contacts block
    if contacts:
        rows.append(
            '<div style="background:#F3E8FF;border-radius:6px;padding:14px 16px;margin:14px 0 0;">'
            '<p style="margin:0 0 10px;font-size:12px;font-weight:700;color:#6b21a8;'
            'text-transform:uppercase;letter-spacing:0.05em;">Contacts</p>'
        )
        for c in contacts:
            rows.append('<div style="margin-bottom:12px;">')
            rows.append(
                f'<p style="margin:0;font-size:14px;font-weight:600;color:#1a202c;">'
                f'{_esc(c.get("name", ""))}</p>'
            )
            if c.get("title"):
                rows.append(
                    f'<p style="margin:2px 0 0;font-size:12px;color:#718096;">'
                    f'{_esc(c["title"])}</p>'
                )
            links = []
            if c.get("linkedin_url"):
                links.append(
                    f'<a href="{_esc(c["linkedin_url"])}" '
                    f'style="color:#4f46e5;font-size:12px;text-decoration:none;">LinkedIn</a>'
                )
            if c.get("email"):
                links.append(
                    f'<a href="mailto:{_esc(c["email"])}" '
                    f'style="color:#4f46e5;font-size:12px;text-decoration:none;">'
                    f'{_esc(c["email"])}</a>'
                )
            if links:
                rows.append(
                    f'<p style="margin:4px 0 0;">'
                    f'{" &nbsp;&middot;&nbsp; ".join(links)}</p>'
                )
            if c.get("outreach_opening"):
                rows.append(
                    f'<div style="background:#EBF4FA;border-radius:4px;padding:8px 10px;margin:6px 0 0;">'
                    f'<p style="margin:0;font-size:13px;color:#2c5282;font-style:italic;">'
                    f'{_esc(c["outreach_opening"])}</p>'
                    f'</div>'
                )
            rows.append('</div>')
        rows.append('</div>')

    rows.append('</td></tr>')
    rows.append(
        '<tr><td style="padding:0 32px;">'
        '<hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0 0;">'
        '</td></tr>'
    )
    return "".join(rows)


def build_html(opportunities, contacts_by_id, stats):
    """
    Build a fully inline-styled single-column HTML digest email.
    All CSS is inline — no <style> tags (stripped by Gmail / Outlook).

    Sorts by (opportunity_priority_score DESC, relevance_score DESC).
    Adds a colour-coded PRIORITY badge next to each opportunity title.
    """
    sorted_opps = sorted(
        opportunities,
        key=lambda o: (
            int(o.get("opportunity_priority_score") or 0),
            int(o.get("relevance_score") or 0),
        ),
        reverse=True,
    )

    parts = [
        '<html><body style="margin:0;padding:0;background:#f4f4f4;'
        'font-family:Arial,Helvetica,sans-serif;">',
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="background:#f4f4f4;"><tr>',
        '<td align="center" style="padding:20px 0;">',
        '<table width="600" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:600px;width:100%;background:#ffffff;'
        'border-radius:6px;overflow:hidden;">',

        # Header
        '<tr><td style="background:#1a1a2e;padding:24px 32px;">',
        f'<h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;">'
        f'{_CLIENT_NAME} Intelligence Digest</h1>',
        '<p style="margin:6px 0 0;color:#a0aec0;font-size:14px;">'
        'Delivering prioritized, decision-ready opportunity briefings</p>',
        '</td></tr>',
    ]

    if not sorted_opps:
        parts.append(
            '<tr><td style="padding:32px;">'
            '<p style="color:#4a5568;font-size:15px;">'
            'No qualifying opportunities this week. '
            'The pipeline ran successfully &mdash; no PURSUE or CONSIDER listings met the threshold.'
            '</p></td></tr>'
        )
    else:
        for opp in sorted_opps:
            parts.append(_opp_section(opp, contacts_by_id.get(opp["id"], [])))

    # Footer stats
    parts.append(
        '<tr><td style="padding:20px 32px 28px;">'
        '<p style="margin:0;font-size:12px;color:#a0aec0;line-height:1.9;">'
        f'{stats["scraped"]} scraped &rarr; {stats["filtered"]} filtered &rarr; '
        f'{stats["pursue"]} PURSUE &middot; {stats["consider"]} CONSIDER &middot; {stats["skip"]} SKIP'
        '<br>'
        f'Contacts found: {stats["contacts"]} &nbsp;&nbsp; '
        f'Outreach drafts: {stats["drafts"]}'
        '</p>'
        '<p style="margin:10px 0 0;font-size:11px;color:#cbd5e0;">'
        f'{_CLIENT_NAME} Intelligence Digest'
        '</p>'
        '</td></tr>'
    )

    parts += [
        '</table>',
        '</td></tr></table>',
        '</body></html>',
    ]
    return "".join(parts)


def build_force_html(opps):
    """Build HTML digest for a force-send run.

    Each opp dict must have 'combined_score' (int) and 'contacts' (list) keys.
    Contacts are sliced to top 3 by relevance_score before rendering.
    Sorted by combined_score DESC.
    """
    sorted_opps = sorted(opps, key=lambda o: o.get("combined_score", 0), reverse=True)

    total_contacts = sum(len(o.get("contacts", [])) for o in sorted_opps)
    drafts = sum(
        1 for o in sorted_opps
        for c in o.get("contacts", [])
        if c.get("outreach_opening")
    )

    parts = [
        '<html><body style="margin:0;padding:0;background:#f4f4f4;'
        'font-family:Arial,Helvetica,sans-serif;">',
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="background:#f4f4f4;"><tr>',
        '<td align="center" style="padding:20px 0;">',
        '<table width="600" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:600px;width:100%;background:#ffffff;'
        'border-radius:6px;overflow:hidden;">',
        '<tr><td style="background:#1a1a2e;padding:24px 32px;">',
        f'<h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;">'
        f'{_CLIENT_NAME} Intelligence Digest</h1>',
        '<p style="margin:6px 0 0;color:#a0aec0;font-size:14px;">'
        'Delivering prioritized, decision-ready opportunity briefings</p>',
        '</td></tr>',
    ]

    for opp in sorted_opps:
        top_contacts = sorted(
            opp.get("contacts", []),
            key=lambda c: c.get("relevance_score") or 0,
            reverse=True,
        )[:3]
        parts.append(_opp_section(opp, top_contacts, override_score=opp.get("combined_score")))

    pursue = sum(1 for o in sorted_opps if o.get("recommendation") == "PURSUE")
    consider = sum(1 for o in sorted_opps if o.get("recommendation") == "CONSIDER")

    parts.append(
        '<tr><td style="padding:20px 32px 28px;">'
        '<p style="margin:0;font-size:12px;color:#a0aec0;line-height:1.9;">'
        f'{len(sorted_opps)} opportunities &mdash; '
        f'{pursue} PURSUE &middot; {consider} CONSIDER'
        '<br>'
        f'Contacts found: {total_contacts} &nbsp;&nbsp; '
        f'Outreach drafts: {drafts}'
        '</p>'
        '<p style="margin:10px 0 0;font-size:11px;color:#cbd5e0;">'
        f'{_CLIENT_NAME} Intelligence Digest'
        '</p>'
        '</td></tr>'
    )
    parts += ['</table>', '</td></tr></table>', '</body></html>']
    return "".join(parts)


# ---------------------------------------------------------------------------
# Resend delivery
# ---------------------------------------------------------------------------

def _send_via_resend(subject, html_body):
    """POST to Resend API. Returns (True, message_id) on 2xx, (False, None) otherwise. Never raises."""
    resend_key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("DIGEST_SENDER", "")
    recipient = os.environ.get("DIGEST_RECIPIENT", "")
    if not resend_key:
        logger.warning("[DIGEST] RESEND_API_KEY not set — cannot send")
        return False, None
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": sender,
                "to": [recipient],
                "subject": subject,
                "html": html_body,
            },
            timeout=30,
        )
        if 200 <= resp.status_code < 300:
            message_id = resp.json().get("id")
            return True, message_id
        logger.warning(
            "[DIGEST] Resend returned %d: %s",
            resp.status_code,
            resp.text[:500],
        )
        return False, None
    except Exception as exc:
        logger.warning("[DIGEST] Resend request failed: %s", exc)
        return False, None


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class IntelligenceDeliveryAgent:
    def _send_via_resend(self, subject, html_body):
        """Instance wrapper so main.py can call advisor._send_via_resend(...)."""
        return _send_via_resend(subject, html_body)

    def force_run(self, skip_orgs=None):
        """Send digest for all PURSUE/CONSIDER opps regardless of sent_in_digest.

        Computes combined_score (70% listing priority + 30% avg contact relevance).
        Listings without contacts receive a −15 penalty.
        Only top 3 contacts by relevance_score are shown per listing.
        Does NOT mark sent_in_digest — force runs are one-off overrides.

        Returns dict: {sent, count, msg_id}
        """
        opps = get_all_pursue_consider(skip_orgs=skip_orgs or [])
        logger.info("[DIGEST-FORCE] %d opportunities loaded (skip_orgs=%s)", len(opps), skip_orgs)

        for opp in opps:
            contacts = get_contacts_for_opportunity(opp["id"])
            opp["contacts"] = contacts
            opp["combined_score"] = _combined_score(opp, contacts)

        if DRY_RUN:
            for opp in sorted(opps, key=lambda o: o["combined_score"], reverse=True):
                logger.info(
                    "[DIGEST-FORCE] %s | priority=%s combined=%d contacts=%d",
                    opp["org"], opp.get("opportunity_priority_score"), opp["combined_score"], len(opp["contacts"]),
                )

        html = build_force_html(opps)
        week = _week_of()
        subject = f"{_CLIENT_NAME} Intelligence — {len(opps)} opportunities | Week of {week}"

        if DRY_RUN:
            print(html[:500])
            logger.info("[DIGEST-FORCE] DRY_RUN — html built, %d opportunities (not sending)", len(opps))
            return {"sent": False, "count": len(opps), "msg_id": None}

        ok, msg_id = _send_via_resend(subject, html)
        logger.info("[DIGEST-FORCE] sent=%s msg_id=%s", ok, msg_id)
        return {"sent": ok, "count": len(opps), "msg_id": msg_id}

    def run(self, state):
        """Build digest HTML and return payload dict. Does NOT send or mark sent.

        Returns:
            dict with keys {html, subject, opportunity_ids, stats, n} on success.
            Empty dict {} if no opportunities or on error (falsy, safe to check with `if not payload`).
        """
        try:
            opportunities = get_opportunities_for_digest()
            if not opportunities:
                logger.info("[DIGEST] no unsent opportunities — skipping build")
                return {}

            contacts_by_id = {
                opp["id"]: get_contacts_for_opportunity(opp["id"])
                for opp in opportunities
            }
            stats = _build_stats(opportunities, contacts_by_id, state)
            html = build_html(opportunities, contacts_by_id, stats)
            n = len(opportunities)
            week = _week_of()
            subject = f"{_CLIENT_NAME} Intelligence Digest - {n} opportunities | Week of {week}"

            if DRY_RUN:
                print(html[:500])
                logger.info("[DIGEST] DRY_RUN — html built, %d opportunities (not sending)", n)

            return {
                "html": html,
                "subject": subject,
                "opportunity_ids": [opp["id"] for opp in opportunities],
                "stats": stats,
                "n": n,
            }

        except Exception as exc:
            logger.warning("[DIGEST] unexpected error building digest: %s", exc)
            return {}

