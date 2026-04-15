# Examples

## demo_run.py

Runs the full pipeline in `DRY_RUN` mode using fixture data. No live API calls,
no database writes. Demonstrates the complete 7-agent execution flow.

**Prerequisites:** Python 3.11+, `pip install -r requirements.txt`, `.env` configured.

```bash
PYTHONPATH=. DRY_RUN=true python examples/demo_run.py
```

**Expected output:** 7 agent phases execute sequentially, scored opportunities
printed to terminal, execution summary with timing.

## Configuring for a New Organization

1. Set `CLIENT_NAME` and `CLIENT_DESCRIPTION` in `.env`
2. Update `docs/data/capability-profile.md` with the organization's capabilities
3. Update `docs/client-briefing.md` with the competitive context
4. Run `PYTHONPATH=. DRY_RUN=true python3 -m pytest tests/ -v` to validate calibration
5. Push to GitHub — the pipeline runs on schedule automatically
