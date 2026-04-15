# Agentic Workflow Orchestrator — Documentation

Autonomous BD intelligence agent. Scrapes government procurement portals daily, scores RFPs against the client's capability profile, discovers contacts, and delivers a structured Monday digest via email. The client operates in Canada and USA.

---

## Folder Map

```
docs/
├── README.md                        ← Index and navigation (this file)
├── agent/
│   ├── overview.md                  ← Pipeline phases, scheduling, business function
│   ├── orchestrator.md              ← Pipeline class, state contract, timeout rules
│   ├── scraper.md                   ← Sources, scrape rules, listing schema
│   ├── filter.md                    ← FilterAgent: model choice, threshold, cache logic
│   ├── scorer.md                    ← ScoringAgent + Critic: prompts, schema, loops
│   ├── contact.md                   ← ContactSourcer + Critic: enrichment, validation
│   ├── outreach.md                  ← OutreachWriter: prompt spec, fallback behaviour
│   └── digest.md                    ← DigestAgent: HTML rules, delivery, stats block
├── data/
│   ├── schema.md                    ← All table definitions, types, constraints
│   └── capability-profile.md        ← CLIENT_PROFILE constant, scoring rubric
├── infrastructure/
│   ├── environment.md               ← Env vars, required vs optional, load order
│   ├── github-actions.md            ← Workflow files, cron schedule, artifact handling
│   └── cost.md                      ← Per-service cost model, free-tier limits, triggers
├── quality/
│   ├── utd-loop.md                  ← Understand-Do-Verify protocol, V1–V7 checklist
│   ├── testing.md                   ← Fixture files, per-module assertions, commands
│   └── calibration.md               ← Golden scoring set, critic baseline, drift check
└── operation/
    ├── runbook.md                   ← First-run setup, weekly checks, monthly tuning
    ├── antipatterns.md              ← Explicit do-not list with rationale
    └── changelog.md                 ← Dated entries, one line per change
```

---

## Navigation by Task

| Task | File |
|------|------|
| Understand system purpose | `agent/overview.md` |
| Build or modify an agent | `agent/{agent-name}.md` |
| Change scoring criteria | `data/capability-profile.md` |
| Add or rotate API key | `infrastructure/environment.md` |
| Fix broken scraper | `agent/scraper.md` |
| Debug failed pipeline run | `quality/utd-loop.md` |
| Check prohibited patterns | `operation/antipatterns.md` |
| Review service costs | `infrastructure/cost.md` |

---

## Conventions

- Every file is self-contained. No cross-file reading required to act on its content.
- `operation/antipatterns.md` overrides any conflicting instruction in other files.
- `data/capability-profile.md` is the sole source of truth for scoring criteria.
- Append one row to `operation/changelog.md` after every meaningful change.
