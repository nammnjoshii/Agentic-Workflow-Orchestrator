# Client Briefing

> Loaded at orchestrator start. Provides pipeline operators with organizational context
> for scoring calibration and outreach tone. Update before each deployment.

## About the Client

**Name:** [Set via `CLIENT_NAME` env var]
**Description:** [Set via `CLIENT_DESCRIPTION` env var]
**Headquarters:** [Location]
**Sector:** [Industry / service type]

## Engagement Context

[Describe why this pipeline is running — what problem the client is solving, what market
they operate in, what differentiates their service offering from competitors in the same
procurement space.]

## Primary Service Capabilities

[List the client's core offerings. These map directly to the scoring rubric in
`docs/data/capability-profile.md`. Be specific — capability keywords extracted from
this section inform how the pre-filter and deep-score agents evaluate RFPs.]

## Target Procurement Profile

[Describe the ideal opportunity: geography, sector, contract value range, engagement
duration, delivery type (strategy-only vs. full implementation). These become the
scoring criteria the AI agents apply.]

## Disqualifiers

[List categories that should always be skipped regardless of keyword match. Examples:
civil engineering, hardware procurement, staffing-only engagements, medical devices.]

## Competitive Context (Optional)

[Describe the competitive landscape. Who else bids on the same contracts? What
differentiates this client? This context improves outreach opener quality.]

---

*Review and update this document before each pipeline deployment cycle.*
