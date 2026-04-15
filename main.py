import logging
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

# Must load env vars BEFORE any agent imports — stakeholder_intelligence_specialist
# and others read API keys (SERPAPI_KEY, HUNTER_API_KEY, APOLLO_API_KEY) at module
# level, so dotenv must fire before those modules are imported.
load_dotenv()

from src.database import init_db, clear_all_data, clear_source_data, save_opportunity, save_contacts, log_pipeline_run, mark_sent
from src.opportunity_orchestrator import OpportunityOrchestrator
from src.agents.procurement_intelligence_specialist import ProcurementIntelligenceSpecialist, BCBidOnlyProcurementSpecialist
from src.agents.opportunity_qualification_specialist import OpportunityQualificationSpecialist
from src.agents.strategic_scoring_agent import StrategicScoringAgent
from src.agents.scoring_assurance_analyst import ScoringAssuranceAnalyst
from src.agents.stakeholder_intelligence_specialist import StakeholderIntelligenceSpecialist
from src.agents.stakeholder_relevance_agent import StakeholderRelevanceAgent
from src.agents.executive_outreach_strategist import ExecutiveOutreachStrategist
from src.agents.intelligence_delivery_agent import IntelligenceDeliveryAgent, _week_of
from src.config import CLIENT_NAME as _CLIENT_NAME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_BRIEFING_PATH = pathlib.Path(__file__).parent / "docs" / "client-briefing.md"


def load_client_context():
    """Read and log the client briefing at workflow start.

    Logs the company overview section and strategic intent so every run
    carries full client context. Never raises — missing file is a warning only.
    """
    try:
        text = _BRIEFING_PATH.read_text(encoding="utf-8")
        # Extract the first substantive section (Company Overview) for the log summary
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("---") and not ln.startswith("module:") and not ln.startswith("purpose:") and not ln.startswith("dependencies:") and not ln.startswith("last_updated:")]
        header = next((ln for ln in lines if ln.startswith("# ")), "Client Briefing")
        logger.info("[MAIN] client-context loaded: %s (%d chars) — %s", _BRIEFING_PATH.name, len(text), header.lstrip("# "))
    except FileNotFoundError:
        logger.warning("[MAIN] client-context file not found: %s", _BRIEFING_PATH)
    except Exception as exc:
        logger.warning("[MAIN] client-context load failed: %s", exc)


def _poll_resend_status(message_id, resend_key, attempts=4, interval_secs=15):
    """Poll Resend GET /emails/{id} until a terminal event or attempts exhausted.

    Terminal events: delivered, opened, clicked, bounced, complained.
    Prints each status line to stdout so GitHub Actions captures it.
    Never raises.
    """
    terminal = {"delivered", "opened", "clicked", "bounced", "complained"}
    url = f"https://api.resend.com/emails/{message_id}"
    headers = {"Authorization": f"Bearer {resend_key}"}

    for attempt in range(1, attempts + 1):
        time.sleep(interval_secs)
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                event = data.get("last_event", "unknown")
                created_at = data.get("created_at", "")
                print(
                    f"[DIGEST] Status check {attempt}/{attempts}: "
                    f"last_event={event.upper()} | message_id={message_id} | sent_at={created_at}"
                )
                if event in terminal:
                    return event
            else:
                print(
                    f"[DIGEST] Status check {attempt}/{attempts}: "
                    f"Resend returned {resp.status_code}"
                )
        except Exception as exc:
            print(f"[DIGEST] Status check {attempt}/{attempts}: request failed — {exc}")

    return None


def send_failure_alert(phase, error):
    """Send a failure notification email via Resend. Never raises."""
    resend_key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("DIGEST_SENDER", "")
    recipient = os.environ.get("DIGEST_RECIPIENT", "")

    if not all([resend_key, sender, recipient]):
        logger.warning("[MAIN] send_failure_alert: missing Resend config — alert not sent")
        return

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
                "subject": f"Workflow Orchestrator — Pipeline Failed: {phase}",
                "text": f"Failed at {phase}: {error}. Check GitHub Actions logs.",
            },
            timeout=15,
        )
        if 200 <= resp.status_code < 300:
            logger.info("[MAIN] failure alert sent for phase %s", phase)
        else:
            logger.warning(
                "[MAIN] failure alert returned %d for phase %s", resp.status_code, phase
            )
    except Exception as exc:
        logger.warning("[MAIN] failure alert failed to send: %s", exc)


_COST_PER_INPUT = {           # USD per token
    "haiku":  0.0000008,      # claude-haiku-4-5  $0.80/M input
    "sonnet": 0.000003,       # claude-sonnet-4-6 $3.00/M input
}
_COST_PER_OUTPUT = {
    "haiku":  0.000004,       # $4.00/M output
    "sonnet": 0.000015,       # $15.00/M output
}
_AGENT_MODEL = {
    "OpportunityQualificationSpecialist": "haiku",
    "StrategicScoringAgent":              "sonnet",
    "ScoringAssuranceAnalyst":            "sonnet",
    "ExecutiveOutreachStrategist":        "sonnet",
}
_PIPELINE_AGENTS = [
    "ProcurementIntelligenceSpecialist",
    "OpportunityQualificationSpecialist",
    "StrategicScoringAgent",
    "ScoringAssuranceAnalyst",
    "StakeholderIntelligenceSpecialist",
    "StakeholderRelevanceAgent",
    "ExecutiveOutreachStrategist",
]


def _print_run_summary(state: dict) -> None:
    """Log a per-agent timing + token usage + cost table after each pipeline run."""
    timings = {row["agent"]: row["duration_secs"] for row in state.get("timings", [])}
    token_usage = state.get("token_usage", {})
    total_dur = total_in = total_out = total_cost = 0.0
    rows = []
    for agent in _PIPELINE_AGENTS:
        dur = timings.get(agent, 0.0)
        usage = token_usage.get(agent, {})
        t_in = usage.get("input", 0)
        t_out = usage.get("output", 0)
        model = _AGENT_MODEL.get(agent, "")
        cost = 0.0
        if model:
            cost = t_in * _COST_PER_INPUT[model] + t_out * _COST_PER_OUTPUT[model]
        total_dur += dur
        total_in += t_in
        total_out += t_out
        total_cost += cost
        rows.append((agent, dur, t_in, t_out, cost))

    sep = "-" * 82
    logger.info("=" * 82)
    logger.info("%-44s  %7s  %10s  %11s  %9s", "Agent", "Secs", "In Tokens", "Out Tokens", "Est. Cost")
    logger.info(sep)
    for name, dur, t_in, t_out, cost in rows:
        dur_s  = "%.1f" % dur if dur else "—"
        t_in_s = "{:,}".format(t_in) if t_in else "—"
        t_out_s = "{:,}".format(t_out) if t_out else "—"
        cost_s = "$%.4f" % cost if cost else "—"
        logger.info("%-44s  %7s  %10s  %11s  %9s", name[:44], dur_s, t_in_s, t_out_s, cost_s)
    logger.info(sep)
    logger.info(
        "%-44s  %7s  %10s  %11s  %9s", "TOTAL",
        "%.1f" % total_dur,
        "{:,}".format(int(total_in)),
        "{:,}".format(int(total_out)),
        "$%.4f" % total_cost,
    )
    logger.info("=" * 82)


def run_daily_scrape():
    try:
        load_client_context()
        load_dotenv()
        init_db()
        clear_all_data()  # fresh slate — each run is fully authoritative

        pipeline = OpportunityOrchestrator([
            ProcurementIntelligenceSpecialist(),
            OpportunityQualificationSpecialist(),
            StrategicScoringAgent(),
            ScoringAssuranceAnalyst(),
            StakeholderIntelligenceSpecialist(),
            StakeholderRelevanceAgent(),
            ExecutiveOutreachStrategist(),
        ])

        state = {
            "listings": [], "filtered": [], "skipped": [], "scored": [],
            "validated": [], "enriched": [], "ready": [],
            "errors": [], "timings": [], "token_usage": {},
        }
        state = pipeline.run(state)
        _print_run_summary(state)

        # Persist all validated opportunities; collect url → DB id mapping
        url_to_id = {}
        for item in state.get("validated", []):
            try:
                opp_id = save_opportunity(item, item)
                url_to_id[item["url"]] = opp_id
            except Exception as exc:
                logger.warning("[MAIN] save_opportunity failed for %s: %s", item.get("url"), exc)

        # Persist contacts for enriched opportunities (outreach_opening written by OutreachWriter)
        for item in state.get("ready", []):
            url = item.get("url", "")
            opp_id = url_to_id.get(url)
            contacts = item.get("contacts", [])
            if opp_id and contacts:
                try:
                    save_contacts(opp_id, contacts)
                except Exception as exc:
                    logger.warning("[MAIN] save_contacts failed for %s: %s", url, exc)

        n_scraped = len(state.get("listings", []))
        n_filtered = len(state.get("filtered", []))
        n_pursue_consider = sum(
            1 for o in state.get("validated", [])
            if o.get("recommendation") in ("PURSUE", "CONSIDER")
        )
        print(
            f"Run complete: {n_scraped} scraped, {n_filtered} filtered, "
            f"{n_pursue_consider} PURSUE/CONSIDER"
        )

        if state.get("errors"):
            logger.warning("[MAIN] pipeline completed with %d agent error(s)", len(state["errors"]))

    except Exception as e:
        logger.exception("[MAIN] run_daily_scrape failed: %s", e)
        send_failure_alert("SCRAPE", str(e))


def run_bcbid_scrape():
    """Entry point for the dedicated BCBid weekly workflow.

    Clears stale BCBid rows only (other portals' data preserved), scrapes BCBid
    via camoufox, runs the full 7-agent pipeline on BCBid listings, then persists.
    Called via: python main.py bcbid
    """
    try:
        load_client_context()
        load_dotenv()
        init_db()
        clear_source_data("BCBid")

        pipeline = OpportunityOrchestrator([
            BCBidOnlyProcurementSpecialist(),
            OpportunityQualificationSpecialist(),
            StrategicScoringAgent(),
            ScoringAssuranceAnalyst(),
            StakeholderIntelligenceSpecialist(),
            StakeholderRelevanceAgent(),
            ExecutiveOutreachStrategist(),
        ])

        state = {
            "listings": [], "filtered": [], "skipped": [], "scored": [],
            "validated": [], "enriched": [], "ready": [],
            "errors": [], "timings": [], "token_usage": {},
        }
        state = pipeline.run(state)
        _print_run_summary(state)

        url_to_id = {}
        for item in state.get("validated", []):
            try:
                opp_id = save_opportunity(item, item)
                url_to_id[item["url"]] = opp_id
            except Exception as exc:
                logger.warning("[MAIN] bcbid save_opportunity failed %s: %s", item.get("url"), exc)

        for item in state.get("ready", []):
            opp_id = url_to_id.get(item.get("url", ""))
            contacts = item.get("contacts", [])
            if opp_id and contacts:
                try:
                    save_contacts(opp_id, contacts)
                except Exception as exc:
                    logger.warning("[MAIN] bcbid save_contacts failed %s: %s", item.get("url"), exc)

        n_pursue = sum(
            1 for o in state.get("validated", [])
            if o.get("recommendation") in ("PURSUE", "CONSIDER")
        )
        print("BCBid run complete: %d scraped, %d filtered, %d PURSUE/CONSIDER"
              % (len(state.get("listings", [])), len(state.get("filtered", [])), n_pursue))

        if state.get("errors"):
            logger.warning("[MAIN] bcbid pipeline completed with %d error(s)", len(state["errors"]))

    except Exception as exc:
        logger.exception("[MAIN] run_bcbid_scrape failed: %s", exc)


def send_weekly_digest():
    load_client_context()
    load_dotenv()
    init_db()

    start = time.monotonic()
    advisor = IntelligenceDeliveryAgent()
    payload = advisor.run({})           # returns dict, no send side effects

    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    if not payload or not payload.get("html"):
        logger.info("[MAIN] digest: no unsent opportunities — sending empty digest notification")
        if not dry_run:
            week = _week_of()
            empty_subject = f"{_CLIENT_NAME} Intelligence Digest — 0 opportunities | Week of {week}"
            empty_html = (
                '<html><body style="margin:0;padding:20px;font-family:Arial,Helvetica,sans-serif;background:#f4f4f4;">'
                '<table width="600" cellpadding="0" cellspacing="0" border="0" '
                'style="max-width:600px;background:#ffffff;border-radius:6px;overflow:hidden;margin:0 auto;">'
                '<tr><td style="background:#1a1a2e;padding:24px 32px;">'
                f'<h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;">{_CLIENT_NAME} Intelligence Digest</h1>'
                '<p style="margin:6px 0 0;color:#a0aec0;font-size:14px;">Delivering prioritized, decision-ready opportunity briefings</p>'
                '</td></tr>'
                '<tr><td style="padding:32px;">'
                '<p style="color:#4a5568;font-size:15px;line-height:1.6;">'
                'No new opportunities have shown up in the procurement portals this week. '
                'The pipeline ran successfully &mdash; all scraped listings were below the relevance threshold '
                'or have already been included in a previous digest.'
                '</p>'
                '<p style="color:#718096;font-size:13px;margin-top:16px;">'
                'The next scrape runs Thursday. Check back Monday for fresh opportunities.'
                '</p>'
                '</td></tr>'
                '<tr><td style="padding:0 32px 24px;">'
                '<p style="margin:0;font-size:11px;color:#cbd5e0;">'
                f'{_CLIENT_NAME} Intelligence Digest'
                '</p></td></tr>'
                '</table></body></html>'
            )
            recipient = os.environ.get("DIGEST_RECIPIENT", "")
            resend_key = os.environ.get("RESEND_API_KEY", "")
            sent, message_id = advisor._send_via_resend(empty_subject, empty_html)
            if sent:
                print(f"[DIGEST] Empty digest sent to {recipient} — no new opportunities this week | message_id={message_id}")
            else:
                print("[DIGEST] ERROR: failed to send empty digest notification")
        return
    if dry_run:
        logger.info("[MAIN] DRY_RUN digest complete — %d opportunities", payload["n"])
        log_pipeline_run(
            "DIGEST", "dry_run", payload["n"], payload["n"], [],
            round(time.monotonic() - start, 3),
            delivery_status="dry_run",
        )
        return

    sent, message_id = advisor._send_via_resend(payload["subject"], payload["html"])
    sent_at = datetime.now(timezone.utc).isoformat()
    duration_secs = round(time.monotonic() - start, 3)

    if sent:
        mark_sent(payload["opportunity_ids"])
        recipient = os.environ.get("DIGEST_RECIPIENT", "")
        print(
            f"[DIGEST] Email sent successfully to {recipient} — "
            f"{payload['n']} opportunities | message_id={message_id}"
        )
        logger.info("[MAIN] digest sent — %d opps, message_id=%s", payload["n"], message_id)
        # Poll Resend for delivery/open/click confirmation
        resend_key = os.environ.get("RESEND_API_KEY", "")
        if resend_key and message_id:
            _poll_resend_status(message_id, resend_key)
        log_pipeline_run(
            "DIGEST", "ok", payload["n"], payload["n"], [],
            duration_secs,
            email_sent_at=sent_at,
            delivery_status="sent",
            resend_message_id=message_id,
        )
    else:
        print(f"[DIGEST] ERROR: email send FAILED after {duration_secs}s — check RESEND_API_KEY, DIGEST_SENDER, DIGEST_RECIPIENT secrets")
        logger.warning("[MAIN] digest send FAILED after %.3fs", duration_secs)
        log_pipeline_run(
            "DIGEST", "error", payload["n"], 0, ["resend_api_failed"],
            duration_secs,
            email_sent_at=sent_at,
            delivery_status="failed",
        )
        send_failure_alert("DIGEST", "Resend API call failed")


def send_digest_force():
    """Force-send digest for all PURSUE/CONSIDER listings, bypassing sent_in_digest.

    Excludes Capital Regional District (no contacts, caused pipeline hang).
    Uses combined score: 70% listing priority + 30% avg contact relevance.
    Listings without contacts get a −15 penalty. Top 3 contacts shown per listing.
    Does NOT mark sent_in_digest so regular digest is unaffected.
    """
    load_client_context()
    init_db()
    advisor = IntelligenceDeliveryAgent()
    result = advisor.force_run(skip_orgs=["Capital Regional District"])
    print(
        f"[DIGEST-FORCE] sent={result['sent']} | "
        f"opportunities={result['count']} | "
        f"msg_id={result['msg_id']}"
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "digest":
        send_weekly_digest()
    elif len(sys.argv) > 1 and sys.argv[1] == "digest_force":
        send_digest_force()
    elif len(sys.argv) > 1 and sys.argv[1] == "bcbid":
        run_bcbid_scrape()
    else:
        run_daily_scrape()
