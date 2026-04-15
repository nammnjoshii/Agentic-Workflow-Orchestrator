"""
Integration tests for src/opportunity_orchestrator.py and main.py entry points.
All run with DRY_RUN=true, zero live API or DB calls.
"""
import importlib
import os
import unittest.mock as mock

import pytest

os.environ.setdefault("DRY_RUN", "true")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class TestPipeline:
    def test_run_passes_state_through_agents(self):
        from src.opportunity_orchestrator import OpportunityOrchestrator

        class DoubleAgent:
            def run(self, state):
                state["x"] = state.get("x", 0) + 1
                return state

        p = OpportunityOrchestrator([DoubleAgent(), DoubleAgent(), DoubleAgent()])
        result = p.run({"x": 0})
        assert result["x"] == 3

    def test_run_returns_state_dict(self):
        from src.opportunity_orchestrator import OpportunityOrchestrator

        class NoopAgent:
            def run(self, state):
                return state

        result = OpportunityOrchestrator([NoopAgent()]).run({"key": "value"})
        assert result["key"] == "value"

    def test_agent_exception_recorded_in_errors(self):
        from src.opportunity_orchestrator import OpportunityOrchestrator

        class BrokenAgent:
            def run(self, state):
                raise RuntimeError("boom")

        result = OpportunityOrchestrator([BrokenAgent()]).run({"errors": []})
        assert len(result.get("errors", [])) > 0


# ---------------------------------------------------------------------------
# main.run_daily_scrape (DRY_RUN=true, mocked DB)
# ---------------------------------------------------------------------------

class TestRunDailyScrape:
    def _mock_db(self, main_mod):
        patches = []
        for fn in ("init_db", "save_opportunity", "save_contacts"):
            p = mock.patch.object(main_mod, fn, return_value=1 if fn == "save_opportunity" else None)
            patches.append(p)
        return patches

    def test_run_daily_scrape_completes_without_exception(self, capsys):
        import main
        importlib.reload(main)
        patches = self._mock_db(main)
        for p in patches:
            p.start()
        try:
            main.run_daily_scrape()
        finally:
            for p in patches:
                p.stop()
        captured = capsys.readouterr()
        assert "Run complete" in captured.out

    def test_run_daily_scrape_state_has_all_keys(self):
        import main
        importlib.reload(main)

        captured_state = {}

        def fake_pipeline_run(self_ignored, state):
            # Instance method mock receives (self, state)
            state["listings"] = [{"url": "https://t.com/1", "title": "T",
                                   "org": "O", "source": "MERX"}]
            state["filtered"] = state["listings"]
            state["validated"] = []
            state["ready"] = []
            captured_state.update(state)
            return state

        with mock.patch.object(main, "init_db"), \
             mock.patch.object(main, "save_opportunity", return_value=1), \
             mock.patch.object(main, "save_contacts"):
            from src.opportunity_orchestrator import OpportunityOrchestrator
            with mock.patch.object(OpportunityOrchestrator, "run", fake_pipeline_run):
                main.run_daily_scrape()

        for key in ("listings", "filtered", "validated", "ready"):
            assert key in captured_state


# ---------------------------------------------------------------------------
# main.send_failure_alert
# ---------------------------------------------------------------------------

class TestSendFailureAlert:
    def test_no_raise_when_resend_fails(self):
        import main
        importlib.reload(main)
        with mock.patch.object(main.requests, "post", side_effect=Exception("network")), \
             mock.patch.dict(os.environ, {
                 "RESEND_API_KEY": "test-key",
                 "DIGEST_SENDER": "a@b.com",
                 "DIGEST_RECIPIENT": "c@d.com",
             }):
            main.send_failure_alert("SCRAPE", "some error")

    def test_silent_when_config_missing(self):
        import main
        importlib.reload(main)
        with mock.patch.dict(os.environ, {
            "RESEND_API_KEY": "",
            "DIGEST_SENDER": "",
            "DIGEST_RECIPIENT": "",
        }):
            main.send_failure_alert("SCRAPE", "error")


# ---------------------------------------------------------------------------
# main.send_weekly_digest
# ---------------------------------------------------------------------------

class TestSendWeeklyDigest:
    def test_calls_digest_agent_run(self):
        import main
        importlib.reload(main)
        # run() now returns a payload dict (empty = no opportunities)
        with mock.patch.object(main.IntelligenceDeliveryAgent, "run", return_value={}) as mock_run:
            main.send_weekly_digest()
        mock_run.assert_called_once()

    def test_no_send_when_no_opportunities(self):
        """send_weekly_digest must not call _send_via_resend when payload is empty."""
        import main
        import src.agents.intelligence_delivery_agent as oia
        importlib.reload(main)
        send_mock = mock.MagicMock()
        with mock.patch.object(main.IntelligenceDeliveryAgent, "run", return_value={}), \
             mock.patch.object(oia, "_send_via_resend", send_mock):
            main.send_weekly_digest()
        send_mock.assert_not_called()


# ---------------------------------------------------------------------------
# OpportunityOrchestrator — per-agent pipeline_runs logging
# ---------------------------------------------------------------------------

class TestOrchestratorLogging:
    def test_logs_one_row_per_agent(self):
        """Orchestrator calls log_pipeline_run once per agent after each completes."""
        from src.opportunity_orchestrator import OpportunityOrchestrator

        class NoopAgent:
            def run(self, state):
                return state

        with mock.patch("src.opportunity_orchestrator.log_pipeline_run") as mock_log:
            orch = OpportunityOrchestrator([NoopAgent(), NoopAgent(), NoopAgent()])
            orch.run({"errors": [], "timings": []})
        assert mock_log.call_count == 3

    def test_logs_error_status_on_agent_failure(self):
        """When an agent raises, the logged row has status='error'."""
        from src.opportunity_orchestrator import OpportunityOrchestrator

        class BoomAgent:
            def run(self, state):
                raise RuntimeError("boom")

        with mock.patch("src.opportunity_orchestrator.log_pipeline_run") as mock_log:
            orch = OpportunityOrchestrator([BoomAgent()])
            orch.run({"errors": [], "timings": []})
        assert mock_log.call_count == 1
        call_args = mock_log.call_args
        assert call_args[0][1] == "error"  # status positional arg


# ---------------------------------------------------------------------------
# run_bcbid_scrape
# ---------------------------------------------------------------------------

class TestRunBcbidScrape:
    def test_run_bcbid_scrape_completes(self, capsys):
        """run_bcbid_scrape() completes without error and prints summary line."""
        import main
        importlib.reload(main)
        with mock.patch.object(main, "init_db"), \
             mock.patch.object(main, "clear_source_data"), \
             mock.patch.object(main, "save_opportunity", return_value=1), \
             mock.patch.object(main, "save_contacts"):
            main.run_bcbid_scrape()
        captured = capsys.readouterr()
        assert "BCBid run complete" in captured.out
