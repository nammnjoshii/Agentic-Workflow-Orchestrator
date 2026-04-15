                    ┌────────────────────────────────────────┐
                    │        MON/THU ORCHESTRATOR            │
                    │  (OpportunityOrchestrator / main.py)   │
                    └────────────────────────────────────────┘
                                      │
                                      ▼
 ┌────────────────────────┐     Pass state dict     ┌────────────────────────┐
 │  PROCUREMENT           │────────────────────────►│  OPPORTUNITY           │
 │  INTELLIGENCE          │                         │  QUALIFICATION         │
 │  SPECIALIST            │◄────────────────────────│  SPECIALIST            │
 │ Visits portals, adds   │                         │ Haiku pre‑filtering    │
 │ raw listings           │      scraped stats       │ + caching             │
 └────────────────────────┘                          └───────────────────────┘
                                      │
                                      ▼
 ┌────────────────────────┐     Extract text, score,    ┌────────────────────────┐
 │  OPPORTUNITY           │────────────────────────────►│  SCORING               │
 │  STRATEGY              │                             │  ASSURANCE             │
 │  ANALYST               │◄────────────────────────────│  ANALYST               │
 │ Sonnet scoring +       │                             │ 2‑loop correction,     │
 │ extraction + caching   │       validated output       │ calibration drift check │
 └────────────────────────┘                              └────────────────────────┘
                                      │
                                      ▼
 ┌────────────────────────┐    Enrich with real data     ┌────────────────────────┐
 │  STAKEHOLDER           │────────────────────────────►│  STAKEHOLDER           │
 │  INTELLIGENCE          │                             │  VALIDATION            │
 │  SPECIALIST            │◄────────────────────────────│  ANALYST               │
 │ Org website, LinkedIn, │                             │ Weighted relevance     │
 │ Hunter.io, SerpAPI     │       top contacts           │ scoring + retries      │
 └────────────────────────┘                              └────────────────────────┘
                                      │
                                      ▼
 ┌────────────────────────┐     Personalized outreach     ┌────────────────────────┐
 │  EXECUTIVE             │──────────────────────────────►│  OPPORTUNITY           │
 │  OUTREACH              │                              │  INTELLIGENCE          │
 │  STRATEGIST            │◄──────────────────────────────│  ADVISOR               │
 │ Sonnet writes unique   │                              │ Build HTML email +      │
 │ 2‑sentence intros      │           ready items         │ Resend delivery         │
 └────────────────────────┘                               └────────────────────────┘
                                      │
                                      ▼
                           ┌──────────────────────────────┐
                           │        SQLite DATABASE        │
                           │ opportunities, contacts, logs │
                           └──────────────────────────────┘

      ┌───────────────────────┐                  ┌────────────────────────┐
      │    GitHub Actions     │───────────────►  │    Scheduled Runs       │
      │ Mon+Thu scrape (7am)  │                  │ Weekly digest (8am Mon) │
      └───────────────────────┘                  └────────────────────────┘
