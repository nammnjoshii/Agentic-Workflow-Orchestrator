---
module: agent/intelligence_delivery_agent
purpose: Define IntelligenceDeliveryAgent HTML rules, delivery contract, priority badge, stats block, and failure behaviour
dependencies: src/agents/intelligence_delivery_agent.py, src/database.py, resend
last_updated: 2026-04-15
---

## Purpose

`IntelligenceDeliveryAgent` queries unsent PURSUE and CONSIDER opportunities from the DB, builds an inline-styled HTML email, sends via Resend, marks records as sent, and logs the run. It runs as a standalone pipeline every Monday at 8am PT.

---

## Scope

- Covers HTML construction, Resend delivery, `mark_sent()` call, and `log_pipeline_run()`.
- Excludes: outreach generation — `outreach_opening` strings arrive pre-populated on each contact dict. Contact discovery and RFP scoring are upstream.
- Operates entirely from DB — does not depend on `state['ready']` from the scrape pipeline.

---

## Key Decisions

- **All CSS must be inline.** No `<style>` tags — they are stripped by Gmail and Outlook. Every style attribute is set directly on the HTML element.
- **Sort by `(opportunity_priority_score DESC, relevance_score DESC)`.** PURSUE appears before CONSIDER due to `get_opportunities_for_digest()` filtering. Within each tier, highest composite priority score appears first.
- **Stats block is mandatory in every digest.** Placed in the footer. Provides pipeline health visibility to the sales team without requiring log access.
- **`mark_sent()` is called only after confirmed send.** If Resend returns non-2xx, records remain unsent and will appear in next Monday's digest.
- **`DRY_RUN=true`:** Build HTML but do not call Resend. Print first 500 chars of HTML to stdout.

---

## Constraints

- Max email width: 600px single column.
- Contact section background: `#F3E8FF`. Outreach opening: italic, `#EBF4FA` background.
- Subject line format: `{CLIENT_NAME} Digest — {n} opportunities | Week of {date}`.
- Log: `[DIGEST] sent {n} opportunities to {recipient}` on success.
- Never raise from `send_digest()` — return `True` on success, `False` on failure.
- **Priority badge** must appear inline next to the opportunity title. Colour rules (inline CSS only):
  - `opportunity_priority_score >= 80` → `#15803d` (deep green)
  - `60–79` → `#1d4ed8` (blue)
  - `40–59` → `#b45309` (amber)
  - `<40` → `#6b7280` (gray)

---

## Interfaces / Dependencies

**DB calls:**
- `get_opportunities_for_digest() -> list[dict]`
- `get_contacts_for_opportunity(id: int) -> list[dict]`
- `mark_sent(ids: list[int]) -> None`
- `log_pipeline_run(phase, status, in, out, errors, ms) -> None`

**Stats block fields (footer of every digest):**
```
{n} scraped → {m} filtered → {p} PURSUE · {q} CONSIDER · {r} SKIP
Contacts found: {x}   Outreach drafts: {x}   Est. cost this week: ~${y}
```

---

## Risks / Considerations

- **Empty digest:** If no unsent PURSUE or CONSIDER records exist, send a minimal email stating "No qualifying opportunities this week." Do not skip sending — a missing email is indistinguishable from a delivery failure.
- **Resend sender verification:** `DIGEST_SENDER` must be a verified sender domain in Resend or all sends will return 403. Verify at `resend.com/domains`.
- **HTML rendering variance:** Inline styles behave differently across email clients. Test in Litmus or Mail Tester before changing colour palette or layout structure.
- **DB artifact gap:** If the scrape artifact was not uploaded correctly (or expired after 7 days), `get_opportunities_for_digest()` returns 0 rows. The stats block exposes this — `0 scraped` is the signal.
