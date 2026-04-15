# Claude Code Skills — Version History

## Baseline (Before)

**Date:** Pre-March 2026
**Skills installed:** 1
**Domains covered:** 1

| Skill | Domain | Purpose |
|-------|--------|---------|
| playwright-cli | Browser automation | Web testing, scraping, screenshots |

**Gaps:**
- No code review or security audit capability
- No structured debugging methodology
- No CI/CD / GitHub Actions awareness
- No Python quality enforcement
- No prompt engineering for Claude agents
- No test strategy or coverage analysis
- No DB query optimization
- No spec extraction from undocumented code

---

## v.1 (Current — March 2026)

**Skills installed:** 10
**Domains covered:** 6

| Skill | Domain | Agent Use Case |
|-------|--------|------------------------|
| playwright-cli | Browser automation | Portal scraping tests |
| prompt-engineer | LLM prompting | Optimize prompts in all 4 Claude agents (filter, scoring, critic, outreach) |
| test-master | Testing | Coverage gap analysis; flaky test debugging; 120+ test suite maintenance |
| debugging-wizard | Debugging | 5-step hypothesis-driven root cause analysis for pipeline failures |
| code-reviewer | Code quality | 7-category structured review (correctness, security, N+1, naming, arch, tests, perf) |
| security-reviewer | Security | OWASP Top 10 + CVSS + secrets scanning (bandit, gitleaks, semgrep) |
| devops-engineer | DevOps | GitHub Actions workflows (`daily_scrape.yml`, `weekly_digest.yml`) |
| spec-miner | Documentation | Reverse-engineer specs for `extraction_utils.py`, `regex_profiles.py` |
| database-optimizer | Database | SQLite index design + slow query analysis for `database.py` |
| python-pro | Python quality | Type annotations, strict mypy, ruff/black enforcement |

### Delta from Baseline → v.1

| Metric | Baseline | v.1 | Delta |
|--------|---------|-----|-------|
| Skills installed | 1 | 10 | +9 |
| Domains covered | 1 | 6 | +5 |
| Claude agents with prompt coverage | 0/4 | 4/4 | +4 |
| OWASP vuln classes detectable | 0 | 10 | +10 |
| Undocumented files coverable (spec-miner) | 0 | 2 | +2 |
| GitHub Actions workflow awareness | No | Yes | ✓ |
| SQLite optimization guidance | No | Yes | ✓ |
| Python 3.11+ type safety enforcement | No | Yes | ✓ |
