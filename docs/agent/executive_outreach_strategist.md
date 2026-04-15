---
module: agent/executive_outreach_strategist
purpose: Define ExecutiveOutreachStrategist prompt specification, output contract, and fallback behaviour
dependencies: src/agents/executive_outreach_strategist.py
last_updated: 2026-02-28
---

## Purpose

`ExecutiveOutreachStrategist` generates a personalised 2-sentence email opening per contact using the scoring LLM. Output is stored in the contact dict under `outreach_opening` and rendered in the digest. It does not send emails.

---

## Scope

- Covers prompt construction, Claude call, response parsing, and fallback string.
- Excludes: contact discovery — contacts arrive pre-populated in `state['enriched']` from `StakeholderIntelligenceSpecialist`. Email delivery — `OpportunityIntelligenceAdvisor` handles Resend delivery; `ExecutiveOutreachStrategist` only writes the opening string.
- Runs once per contact, not per opportunity. An opportunity with 3 contacts generates 3 separate calls.

---

## Key Decisions

- **Model: scoring LLM, `max_tokens=200`.** Opening must be ≤2 sentences. The pre-filter LLM produces generic output for this task — the scoring LLM measurably improves specificity.
- **Inputs are mandatory:** `contact_name`, `contact_title`, `rfp_title`, `exec_summary`, `suggested_angle` must all be non-empty before calling Claude. Missing any one → use fallback string without calling API.
- **Fallback string is fixed:** `"I noticed your team at {org} is running a procurement for {rfp_title} and wanted to introduce our relevant work in this area."` — interpolated from available fields.
- **`time.sleep(0.5)` between calls:** Prevents rate limiting when processing batches of 10+ contacts.

---

## Constraints

- Prompt must explicitly prohibit: generic phrases ("I hope this finds you well"), competitor mentions, unverifiable claims about the client.
- `max_tokens=200` is a hard limit — do not raise it. Longer openings are not used in the digest.
- `DRY_RUN=true`: return fallback string for all contacts without calling API.
- Log: `[OUTREACH] generated for {contact_name} at {org}` or `[OUTREACH] fallback used for {contact_name}`.
- Never raise from `generate_outreach()` — always return a string.

---

## Interfaces / Dependencies

**Function signature:**
```python
def generate_outreach(
    contact_name:    str,
    contact_title:   str,
    rfp_title:       str,
    exec_summary:    str,
    suggested_angle: str,
) -> str
```

**State mutation:**
- Reads: `state['enriched']` — list of opportunities with contact lists.
- Writes: appends `outreach_opening: str` to each contact dict in-place.
- Moves completed opportunities to `state['ready']`.

---

## Risks / Considerations

- **Opening quality degrades without `suggested_angle`:** If `OpportunityStrategyAnalyst` returns an empty `suggested_angle`, the outreach opening will be generic. Enforce non-empty `suggested_angle` in `ScoringAssuranceAnalyst` validation before this stage runs.
- **Repetition across contacts at same org:** If an org has 3 contacts, all 3 openings may be identical if inputs are similar. Accept this — do not add deduplication logic here.
- **Prompt injection via RFP title:** Sanitise `rfp_title` by stripping any content after a `---` or ` ignore ` substring before inserting into prompt.
