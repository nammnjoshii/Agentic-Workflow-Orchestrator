---
module: workflow/session-start
purpose: Define the startup protocol Claude Code follows at the beginning of every session
dependencies: workflow/handoff-template.md, workflow/build-sequence.md, docs/operation/changelog.md
last_updated: 2026-03-01
---

## Purpose

Eliminates the cold-start problem. Every Claude Code session begins identically: read this file, orient to current state, identify the next action, proceed. No human direction required to get started.

---

## Scope

- Covers the 5-step orientation protocol and the decision tree for what to do next.
- Excludes: build instructions (in `workflow/build-sequence.md`), operational monitoring (in `docs/operation/runbook.md`).
- This file is always the first file Claude Code reads. It is the entry point to the entire system.

---

## Key Decisions

- **Read before acting.** Claude Code must complete all 5 orientation steps before writing a single line of code.
- **Handoff file is the source of truth for session state.** If it says Step 7 is next, start at Step 7 — do not re-verify earlier steps unless a test fails.
- **One step per session is acceptable.** A session that builds one file, passes its test, and updates the changelog is a complete successful session.
- **Never assume context from prior sessions.** Claude Code has no memory. Every session is a fresh start — this protocol is the memory substitute.

---

## Constraints

- Do not skip Step O1 even if the handoff file looks complete. Files may have changed between sessions.
- If `workflow/handoff-template.md` does not exist yet: assume this is Session 1, start at build-sequence.md Step 1.
- If handoff-template.md exists but `next_step` is blank: read the changelog to determine what was last completed, then set next_step to the following step in build-sequence.md.
- Never start building until O5 is complete and the next action is confirmed.

---

## Interfaces / Dependencies

**Files read during orientation (in order):**
1. `workflow/handoff-template.md` — session state
2. `workflow/build-sequence.md` — build order and test commands
3. `docs/operation/changelog.md` — last 3 entries only
4. `docs/operation/antipatterns.md` — refresh prohibited patterns
5. The specific doc file for the next step (e.g. `docs/agent/filter.md`)

---

## Startup Protocol

Execute all 5 orientation steps before taking any action:

**O1 — Read handoff-template.md**
Find the `next_step` field. That is what you are building this session.
If the file does not exist: next_step = build-sequence.md Step 1.

**O2 — Verify prior step is actually done**
Run the test command for the step *before* next_step.
If it fails: fix that step first. Do not proceed to next_step with a broken dependency.
If it passes: continue to O3.

**O3 — Read the last 3 changelog entries**
Confirm what was completed in recent sessions. If the changelog shows next_step was already completed, advance next_step by one and update handoff-template.md.

**O4 — Refresh antipatterns**
Re-read `docs/operation/antipatterns.md`. These rules apply to every file you write regardless of what any other doc says.

**O5 — Read the doc file for next_step**
Find the doc reference in `workflow/build-sequence.md` for your next_step. Read that doc file completely before writing any code.

**Then act:**
- State out loud (in your response): "Session oriented. Next step: [step name]. Reading [doc file] now."
- Build the file following the doc exactly.
- Run the test command from build-sequence.md.
- If test passes: update `docs/operation/changelog.md`, update `workflow/handoff-template.md`.
- If test fails: attempt fix. If not fixed in 2 attempts: record blocker in handoff-template.md and stop.

---

## Decision Tree

```
Does workflow/handoff-template.md exist?
├── No  → Start at build-sequence.md Step 1
└── Yes → Read next_step field
          ├── Blank → Read changelog → infer next_step
          └── Set   → Run prior step's test
                      ├── Fails → Fix prior step first
                      └── Passes → Read doc → Build → Test → Update files
```

---

## Risks / Considerations

- **Stale handoff file:** If handoff-template.md was not updated at the end of the last session, next_step may be wrong. O2 (prior step verification) catches this — a passing test confirms the step is done.
- **Multiple sessions on same day:** If two Claude Code sessions run the same day, the second session must re-read handoff-template.md — the first session may have advanced next_step.
- **Orientation feels slow:** The 5 steps take ~2 minutes. They prevent 30 minutes of debugging wrong-step errors. Do not skip them.
