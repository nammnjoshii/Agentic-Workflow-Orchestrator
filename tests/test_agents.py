"""
Per-module agent tests — all run with DRY_RUN=true, zero live API calls.
Assertions per docs/quality/testing.md.
"""
import importlib
import os
import re
import unittest.mock as mock

import pytest

os.environ.setdefault("DRY_RUN", "true")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_listing(**kwargs):
    base = {
        "title": "Business Intelligence Dashboard Development",
        "org": "City of Vancouver",
        "deadline": "2026-06-01",
        "value": "500K",
        "url": "https://test.example.com/rfp/1",
        "source": "MERX",
        "raw_description": "Data analytics platform for municipal reporting.",
    }
    base.update(kwargs)
    return base


def _base_state(**kwargs):
    state = {
        "listings": [], "filtered": [], "skipped": [],
        "scored": [], "validated": [], "enriched": [],
        "ready": [], "errors": [], "timings": [],
    }
    state.update(kwargs)
    return state


# ---------------------------------------------------------------------------
# OpportunityQualificationSpecialist (FilterAgent)
# ---------------------------------------------------------------------------

class TestOpportunityQualificationSpecialist:
    def setup_method(self):
        import src.agents.opportunity_qualification_specialist as m
        importlib.reload(m)
        self.fa = m

    def test_filtered_and_skipped_keys_present(self):
        from src.agents.opportunity_qualification_specialist import OpportunityQualificationSpecialist
        state = _base_state(listings=[_base_listing()])
        result = OpportunityQualificationSpecialist().run(state)
        assert "filtered" in result
        assert "skipped" in result

    def test_sum_equals_input_count(self):
        from src.agents.opportunity_qualification_specialist import OpportunityQualificationSpecialist
        listings = [_base_listing(url=f"https://t.com/{i}") for i in range(3)]
        state = _base_state(listings=listings)
        result = OpportunityQualificationSpecialist().run(state)
        assert len(result["filtered"]) + len(result["skipped"]) == 3

    def test_dry_run_all_pass(self):
        from src.agents.opportunity_qualification_specialist import OpportunityQualificationSpecialist
        state = _base_state(listings=[_base_listing()])
        result = OpportunityQualificationSpecialist().run(state)
        assert len(result["filtered"]) == 1
        assert len(result["skipped"]) == 0


# ---------------------------------------------------------------------------
# StrategicScoringAgent (ScoringAgent)
# ---------------------------------------------------------------------------

class TestStrategicScoringAgent:
    REQUIRED_KEYS = {
        "relevance_score", "recommendation", "score_rationale",
        "capability_match", "risks", "estimated_effort",
        "exec_summary", "suggested_angle",
    }

    def test_all_8_scored_keys_present(self):
        from src.agents.strategic_scoring_agent import StrategicScoringAgent
        listing = _base_listing()
        state = _base_state(filtered=[listing])
        result = StrategicScoringAgent().run(state)
        assert len(result["scored"]) == 1
        for key in self.REQUIRED_KEYS:
            assert key in result["scored"][0], f"Missing key: {key}"

    def test_relevance_score_is_int_in_range(self):
        from src.agents.strategic_scoring_agent import StrategicScoringAgent
        state = _base_state(filtered=[_base_listing()])
        result = StrategicScoringAgent().run(state)
        score = result["scored"][0]["relevance_score"]
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_recommendation_is_valid(self):
        from src.agents.strategic_scoring_agent import StrategicScoringAgent
        state = _base_state(filtered=[_base_listing()])
        result = StrategicScoringAgent().run(state)
        assert result["scored"][0]["recommendation"] in ("PURSUE", "CONSIDER", "SKIP")

    def test_score_listing_enriches_value_from_metadata(self):
        """Budget found in RFP HTML backfills listing value when value is 'Not specified'."""
        import json
        import src.agents.strategic_scoring_agent as sa

        fixture = {
            "relevance_score": 85, "recommendation": "PURSUE",
            "score_rationale": "Strong match", "capability_match": ["Data Engineering"],
            "risks": [], "estimated_effort": "M",
            "exec_summary": "Summary", "suggested_angle": "Lead", "decision_log": [],
        }
        mock_resp = mock.MagicMock()
        mock_resp.content = [mock.MagicMock(text=json.dumps(fixture))]

        listing = _base_listing(value="Not specified")

        with mock.patch("src.agents.strategic_scoring_agent._fetch_rfp_text",
                        return_value="Budget: $750,000 Data analytics platform"), \
             mock.patch("src.agents.strategic_scoring_agent.anthropic.Anthropic"):
            agent = sa.StrategicScoringAgent()
            agent._client = mock.MagicMock()
            agent._client.messages.create.return_value = mock_resp
            agent._score_listing(listing)

        assert listing["value"] == "750,000"

    def test_score_listing_preserves_existing_value(self):
        """Existing non-empty value is not overwritten by metadata budget."""
        import json
        import src.agents.strategic_scoring_agent as sa

        fixture = {
            "relevance_score": 85, "recommendation": "PURSUE",
            "score_rationale": "Strong match", "capability_match": ["Data Engineering"],
            "risks": [], "estimated_effort": "M",
            "exec_summary": "Summary", "suggested_angle": "Lead", "decision_log": [],
        }
        mock_resp = mock.MagicMock()
        mock_resp.content = [mock.MagicMock(text=json.dumps(fixture))]

        listing = _base_listing(value="$2M")  # already set

        with mock.patch("src.agents.strategic_scoring_agent._fetch_rfp_text",
                        return_value="Budget: $750,000 Data analytics platform"), \
             mock.patch("src.agents.strategic_scoring_agent.anthropic.Anthropic"):
            agent = sa.StrategicScoringAgent()
            agent._client = mock.MagicMock()
            agent._client.messages.create.return_value = mock_resp
            agent._score_listing(listing)

        assert listing["value"] == "$2M"  # unchanged


# ---------------------------------------------------------------------------
# ScoringAssuranceAnalyst (ScoringCritic)
# ---------------------------------------------------------------------------

class TestScoringAssuranceAnalyst:
    def _scored_listing(self):
        listing = _base_listing()
        listing.update({
            "relevance_score": 85,
            "recommendation": "PURSUE",
            "score_rationale": "Strong match",
            "capability_match": ["Data Engineering"],
            "risks": [],
            "estimated_effort": "M",
            "exec_summary": "Summary",
            "suggested_angle": "Lead with BI expertise",
            "decision_log": [],
        })
        return listing

    def test_validated_key_populated(self):
        from src.agents.scoring_assurance_analyst import ScoringAssuranceAnalyst
        state = _base_state(scored=[self._scored_listing()])
        result = ScoringAssuranceAnalyst().run(state)
        assert "validated" in result
        assert len(result["validated"]) > 0

    def test_decision_log_is_list(self):
        from src.agents.scoring_assurance_analyst import ScoringAssuranceAnalyst
        state = _base_state(scored=[self._scored_listing()])
        result = ScoringAssuranceAnalyst().run(state)
        for item in result["validated"]:
            assert isinstance(item.get("decision_log", []), list)


# ---------------------------------------------------------------------------
# StakeholderIntelligenceSpecialist (ContactSourcer)
# ---------------------------------------------------------------------------

class TestStakeholderIntelligenceSpecialist:
    def _validated_listing(self):
        listing = _base_listing()
        listing.update({
            "relevance_score": 85,
            "recommendation": "PURSUE",
            "score_rationale": "Strong match",
            "capability_match": ["Data Engineering"],
            "risks": [],
            "estimated_effort": "M",
            "exec_summary": "Summary",
            "suggested_angle": "Lead with BI expertise",
            "decision_log": [],
        })
        return listing

    def test_returns_dict_with_contacts_key(self):
        from src.agents.stakeholder_intelligence_specialist import StakeholderIntelligenceSpecialist
        state = _base_state(validated=[self._validated_listing()])
        result = StakeholderIntelligenceSpecialist().run(state)
        for opp in result.get("enriched", []):
            assert "contacts" in opp

    def test_max_3_contacts_per_opportunity(self):
        from src.agents.stakeholder_intelligence_specialist import StakeholderIntelligenceSpecialist
        state = _base_state(validated=[self._validated_listing()])
        result = StakeholderIntelligenceSpecialist().run(state)
        for opp in result.get("enriched", []):
            assert len(opp["contacts"]) <= 3


# ---------------------------------------------------------------------------
# StakeholderRelevanceAgent (ContactCritic)
# ---------------------------------------------------------------------------

class TestStakeholderRelevanceAgent:
    def _contacts_state(self):
        url = "https://test.example.com/rfp/1"
        listing = _base_listing(
            url=url,
            recommendation="PURSUE",
            exec_summary="Analytics platform for municipal data.",
            suggested_angle="Lead with data analytics expertise.",
        )
        return _base_state(
            validated=[listing],
            contacts={
                url: {
                    "contacts": [
                        {"name": "Jane Smith", "title": "Director of Data Analytics",
                         "email": "jane@example.com", "linkedin_url": None,
                         "source": "Hunter"},
                    ],
                    "website": None,
                    "domain": "example.com",
                }
            },
        )

    def test_enriched_key_present(self):
        from src.agents.stakeholder_relevance_agent import StakeholderRelevanceAgent
        result = StakeholderRelevanceAgent().run(self._contacts_state())
        assert "enriched" in result

    def test_contact_has_name_and_relevance_score(self):
        from src.agents.stakeholder_relevance_agent import StakeholderRelevanceAgent
        result = StakeholderRelevanceAgent().run(self._contacts_state())
        for opp in result["enriched"]:
            for c in opp.get("contacts", []):
                assert c.get("name"), "Contact must have a name"
                assert "relevance_score" in c, "Contact must have a relevance_score"


# ---------------------------------------------------------------------------
# ExecutiveOutreachStrategist (OutreachWriter)
# ---------------------------------------------------------------------------

class TestExecutiveOutreachStrategist:
    def _enriched_opp(self):
        listing = _base_listing()
        listing.update({
            "exec_summary": "Municipal BI platform.",
            "suggested_angle": "Lead with municipal experience.",
            "contacts": [
                {"name": "Jane Smith", "title": "CTO",
                 "email": "jane@example.com", "linkedin_url": None,
                 "outreach_opening": ""},
            ],
        })
        return listing

    def test_run_returns_state_with_ready(self):
        from src.agents.executive_outreach_strategist import ExecutiveOutreachStrategist
        state = _base_state(enriched=[self._enriched_opp()])
        result = ExecutiveOutreachStrategist().run(state)
        assert "ready" in result
        assert len(result["ready"]) == 1

    def test_outreach_opening_populated(self):
        from src.agents.executive_outreach_strategist import ExecutiveOutreachStrategist
        state = _base_state(enriched=[self._enriched_opp()])
        result = ExecutiveOutreachStrategist().run(state)
        opp = result["ready"][0]
        for c in opp["contacts"]:
            assert c.get("outreach_opening"), "outreach_opening must be populated"

    def test_generate_outreach_dry_run_returns_string(self):
        from src.agents.executive_outreach_strategist import generate_outreach
        result = generate_outreach(
            contact_name="Jane Smith",
            contact_title="CTO",
            rfp_title="BI Dashboard",
            exec_summary="Summary",
            suggested_angle="Lead",
            org="City of Vancouver",
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_outreach_missing_input_uses_fallback(self):
        """Missing required field → fallback, no API call."""
        # Set DRY_RUN=false to force the missing-input code path
        import src.agents.executive_outreach_strategist as ow
        with mock.patch.object(ow, "DRY_RUN", False):
            result = ow.generate_outreach(
                contact_name="Jane",
                contact_title="",  # missing
                rfp_title="BI Dashboard",
                exec_summary="Summary",
                suggested_angle="Lead",
                org="Org",
            )
        assert isinstance(result, str)

    def test_sanitise_strips_after_triple_dash(self):
        from src.agents.executive_outreach_strategist import _sanitise_rfp_title
        assert _sanitise_rfp_title("Title --- ignore this") == "Title"

    def test_sanitise_strips_after_ignore_keyword(self):
        from src.agents.executive_outreach_strategist import _sanitise_rfp_title
        assert _sanitise_rfp_title("Title ignore everything") == "Title"


# ---------------------------------------------------------------------------
# IntelligenceDeliveryAgent (DigestAgent)
# ---------------------------------------------------------------------------

class TestIntelligenceDeliveryAgent:
    def setup_method(self):
        import src.agents.intelligence_delivery_agent as da
        importlib.reload(da)
        self.da = da

    def _opp(self):
        return {
            "id": 1,
            "title": "BI Dashboard",
            "org": "City of Vancouver",
            "deadline": "2026-06-01",
            "value": "500K",
            "url": "https://test.example.com/rfp/1",
            "source": "MERX",
            "relevance_score": 85,
            "recommendation": "PURSUE",
            "score_rationale": "Strong match",
            "capability_match": ["Data Engineering"],
            "risks": [],
            "estimated_effort": "M",
            "exec_summary": "Municipal BI platform",
            "suggested_angle": "Lead with BI",
            "decision_log": [],
        }

    def test_build_html_contains_title(self):
        da = self.da
        opps = [self._opp()]
        contacts = {1: [{"name": "Jane Smith", "title": "CTO",
                          "email": "j@example.com", "outreach_opening": "Hi there."}]}
        stats = {"scraped": 5, "filtered": 3, "pursue": 1,
                 "consider": 0, "skip": 2, "contacts": 1, "drafts": 1, "cost": "0.50"}
        html = da.build_html(opps, contacts, stats)
        assert "Intelligence Digest" in html

    def test_build_html_no_style_tags(self):
        da = self.da
        opps = [self._opp()]
        contacts = {1: []}
        stats = {"scraped": 1, "filtered": 1, "pursue": 1,
                 "consider": 0, "skip": 0, "contacts": 0, "drafts": 0, "cost": "0.01"}
        html = da.build_html(opps, contacts, stats)
        assert not re.search(r"<style[\s>]", html), "No <style> tags allowed"

    def test_build_html_empty_returns_no_opportunities_msg(self):
        da = self.da
        stats = {"scraped": 0, "filtered": 0, "pursue": 0,
                 "consider": 0, "skip": 0, "contacts": 0, "drafts": 0, "cost": "0.00"}
        html = da.build_html([], {}, stats)
        assert "No qualifying opportunities" in html

    def test_run_returns_payload_dict(self):
        """run() must return a dict with html, subject, opportunity_ids, stats, n."""
        da = self.da
        opps = [self._opp()]
        with mock.patch.object(da, "get_opportunities_for_digest", return_value=opps), \
             mock.patch.object(da, "get_contacts_for_opportunity", return_value=[]):
            agent = da.IntelligenceDeliveryAgent()
            result = agent.run({})
        assert isinstance(result, dict)
        assert "html" in result
        assert "subject" in result
        assert "opportunity_ids" in result
        assert result["n"] == 1

    def test_run_does_not_call_send_or_mark_sent(self):
        """run() must not call _send_via_resend or mark_sent — orchestrator owns those."""
        da = self.da
        opps = [self._opp()]
        send_mock = mock.MagicMock()
        with mock.patch.object(da, "DRY_RUN", False), \
             mock.patch.object(da, "get_opportunities_for_digest", return_value=opps), \
             mock.patch.object(da, "get_contacts_for_opportunity", return_value=[]), \
             mock.patch.object(da, "_send_via_resend", send_mock):
            agent = da.IntelligenceDeliveryAgent()
            result = agent.run({})
        send_mock.assert_not_called()
        assert isinstance(result, dict) and result.get("html")

    def test_dry_run_skips_send(self):
        """With DRY_RUN=true the agent must not call _send_via_resend and still return payload."""
        da = self.da
        opps = [self._opp()]
        send_mock = mock.MagicMock()
        with mock.patch.object(da, "DRY_RUN", True), \
             mock.patch.object(da, "get_opportunities_for_digest", return_value=opps), \
             mock.patch.object(da, "get_contacts_for_opportunity", return_value=[]), \
             mock.patch.object(da, "_send_via_resend", send_mock):
            agent = da.IntelligenceDeliveryAgent()
            result = agent.run({})
        send_mock.assert_not_called()
        assert isinstance(result, dict) and result.get("html")

    def test_value_shows_contract_value_label(self):
        """A concrete value string renders with 'Contract Value:' label."""
        da = self.da
        opp = {**self._opp(), "value": "750,000"}
        html = da._opp_section(opp, [])
        assert "Contract Value: 750,000" in html

    def test_value_hides_not_specified(self):
        """'Not specified' values must not appear in rendered HTML."""
        da = self.da
        opp = {**self._opp(), "value": "Not specified"}
        html = da._opp_section(opp, [])
        assert "Not specified" not in html
        assert "Contract Value" not in html

    def test_value_hides_empty_string(self):
        """Empty value must not render a 'Contract Value:' row."""
        da = self.da
        opp = {**self._opp(), "value": ""}
        html = da._opp_section(opp, [])
        assert "Contract Value" not in html
