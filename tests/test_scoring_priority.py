"""
Tests for the weighted opportunity_priority_score field.

Verifies: field exists on scored output, is int 0–100, ScoringCritic accepts it,
and digest sorting by priority is correct.
"""
import os
import unittest.mock as mock

import pytest

os.environ.setdefault("DRY_RUN", "true")

_URL = "https://test.example.com/rfp/priority/1"


def _base_listing(**kwargs):
    base = {
        "title": "Data Analytics Platform RFP",
        "org": "City of Vancouver",
        "deadline": "2026-08-01",
        "value": "500K",
        "url": _URL,
        "source": "MERX",
        "raw_description": "Cloud data analytics platform for municipal reporting.",
    }
    base.update(kwargs)
    return base


def _base_scored(**kwargs):
    base = {
        "relevance_score": 82,
        "recommendation": "PURSUE",
        "score_rationale": "Strong match on primary capabilities.",
        "capability_match": ["Snowflake", "Power BI", "dbt"],
        "risks": [],
        "estimated_effort": "M",
        "exec_summary": "Modern data analytics platform procurement.",
        "suggested_angle": "Lead with Snowflake delivery track record.",
        "decision_log": [],
    }
    base.update(kwargs)
    return base


class TestPriorityScoreHelpers:
    def test_rfp_type_score_rfp(self):
        from src.agents.strategic_scoring_agent import _rfp_type_score
        assert _rfp_type_score("Data Analytics Platform RFP", "MERX") == 100

    def test_rfp_type_score_rfq(self):
        from src.agents.strategic_scoring_agent import _rfp_type_score
        assert _rfp_type_score("Data Services RFQ", "") == 70

    def test_rfp_type_score_rfi(self):
        from src.agents.strategic_scoring_agent import _rfp_type_score
        assert _rfp_type_score("Market Research RFI", "") == 50

    def test_rfp_type_score_unknown(self):
        from src.agents.strategic_scoring_agent import _rfp_type_score
        assert _rfp_type_score("Generic Procurement Notice", "") == 30

    def test_value_score_large(self):
        from src.agents.strategic_scoring_agent import _value_score
        assert _value_score("2M") == 100

    def test_value_score_medium(self):
        from src.agents.strategic_scoring_agent import _value_score
        assert _value_score("500K") == 80

    def test_value_score_small(self):
        from src.agents.strategic_scoring_agent import _value_score
        assert _value_score("50K") == 20

    def test_value_score_unknown(self):
        from src.agents.strategic_scoring_agent import _value_score
        assert _value_score("") == 50

    def test_time_left_score_far(self):
        from src.agents.strategic_scoring_agent import _time_left_score
        assert _time_left_score("2030-01-01") == 100

    def test_time_left_score_unknown(self):
        from src.agents.strategic_scoring_agent import _time_left_score
        assert _time_left_score("") == 50

    def test_capability_quality_score_zero(self):
        from src.agents.strategic_scoring_agent import _capability_quality_score
        assert _capability_quality_score([]) == 0

    def test_capability_quality_score_primary_heavy(self):
        from src.agents.strategic_scoring_agent import _capability_quality_score
        assert _capability_quality_score(["Snowflake", "Databricks", "Power BI"]) >= 85

    def test_capability_quality_score_generic_only(self):
        from src.agents.strategic_scoring_agent import _capability_quality_score
        assert _capability_quality_score(["RFP", "evaluation criteria"]) == 30

    def test_capability_quality_score_one_primary(self):
        from src.agents.strategic_scoring_agent import _capability_quality_score
        assert _capability_quality_score(["Snowflake"]) == 60

    def test_capability_quality_score_elt_domain(self):
        from src.agents.strategic_scoring_agent import _capability_quality_score
        assert _capability_quality_score(["ELT pipelines", "DAG orchestration", "semantic modeling"]) >= 85

    def test_capability_quality_score_contract_language(self):
        from src.agents.strategic_scoring_agent import _capability_quality_score
        assert _capability_quality_score(["data migration", "cloud modernization", "data mesh"]) >= 85

    def test_capability_quality_score_nosql_databases(self):
        from src.agents.strategic_scoring_agent import _capability_quality_score
        assert _capability_quality_score(["MongoDB", "Redis", "Elasticsearch"]) >= 85

    def test_capability_quality_score_legacy_etl_tools(self):
        from src.agents.strategic_scoring_agent import _capability_quality_score
        assert _capability_quality_score(["Talend", "SSIS", "Informatica"]) >= 85

    def test_risk_profile_score_no_risks(self):
        from src.agents.strategic_scoring_agent import _risk_profile_score
        assert _risk_profile_score([]) == 100

    def test_risk_profile_score_many_risks(self):
        from src.agents.strategic_scoring_agent import _risk_profile_score
        assert _risk_profile_score(["r1", "r2", "r3"]) == 20

    def test_risk_profile_score_hard_disqualifier(self):
        from src.agents.strategic_scoring_agent import _risk_profile_score
        assert _risk_profile_score(["civil engineering scope identified"]) == 20

    def test_risk_profile_score_one_soft_risk(self):
        from src.agents.strategic_scoring_agent import _risk_profile_score
        assert _risk_profile_score(["incumbent vendor relationship"]) == 70

    def test_description_richness_full_metadata(self):
        from src.agents.strategic_scoring_agent import _description_richness_score
        listing = {
            "title": "Data Analytics RFP",
            "org": "BC Hydro",
            "value": "500K",
            "deadline": "2026-06-01",
            "raw_description": "x" * 300,
        }
        assert _description_richness_score(listing) == 100

    def test_description_richness_sparse_metadata(self):
        from src.agents.strategic_scoring_agent import _description_richness_score
        listing = {"title": "RFP Notice"}
        assert _description_richness_score(listing) == 10

    def test_description_richness_partial(self):
        from src.agents.strategic_scoring_agent import _description_richness_score
        listing = {
            "title": "Data Platform RFP",
            "org": "City of Calgary",
            "value": "not specified",
        }
        assert _description_richness_score(listing) == 40


class TestComputePriorityScore:
    def test_returns_int(self):
        from src.agents.strategic_scoring_agent import compute_priority_score
        listing = _base_listing()
        scored = _base_scored()
        result = compute_priority_score(listing, scored)
        assert isinstance(result, int)

    def test_within_0_100(self):
        from src.agents.strategic_scoring_agent import compute_priority_score
        listing = _base_listing()
        scored = _base_scored()
        result = compute_priority_score(listing, scored)
        assert 0 <= result <= 100

    def test_high_score_listing_is_high(self):
        from src.agents.strategic_scoring_agent import compute_priority_score
        listing = _base_listing(value="2M", deadline="2030-01-01")
        scored = _base_scored(
            relevance_score=95,
            recommendation="PURSUE",
            capability_match=["Snowflake", "Power BI", "dbt", "Azure"],
            risks=[],
        )
        result = compute_priority_score(listing, scored)
        assert result >= 75, f"Expected high priority, got {result}"

    def test_low_score_listing_is_low(self):
        from src.agents.strategic_scoring_agent import compute_priority_score
        listing = _base_listing(value="10K", deadline="2020-01-01")
        scored = _base_scored(
            relevance_score=20,
            recommendation="SKIP",
            capability_match=[],
            risks=["risk1", "risk2", "risk3"],
        )
        result = compute_priority_score(listing, scored)
        assert result <= 40, f"Expected low priority, got {result}"


class TestStrategicScoringAgentPriorityField:
    def test_priority_score_present_in_scored(self):
        from src.agents.strategic_scoring_agent import StrategicScoringAgent
        state = {
            "filtered": [_base_listing()],
            "scored": [],
        }
        result = StrategicScoringAgent().run(state)
        assert len(result["scored"]) == 1
        assert "opportunity_priority_score" in result["scored"][0], (
            "opportunity_priority_score must be present in scored output"
        )

    def test_priority_score_is_int_in_range(self):
        from src.agents.strategic_scoring_agent import StrategicScoringAgent
        state = {
            "filtered": [_base_listing()],
            "scored": [],
        }
        result = StrategicScoringAgent().run(state)
        score = result["scored"][0]["opportunity_priority_score"]
        assert isinstance(score, int), f"Expected int, got {type(score)}"
        assert 0 <= score <= 100, f"Score out of range: {score}"


class TestScoringAssuranceAnalystPriorityValidation:
    def test_critic_accepts_valid_priority_score(self):
        from src.agents.scoring_assurance_analyst import ScoringAssuranceAnalyst
        item = {**_base_listing(), **_base_scored(), "opportunity_priority_score": 72}
        state = {"scored": [item], "validated": []}
        result = ScoringAssuranceAnalyst().run(state)
        assert len(result["validated"]) == 1

    def test_critic_validation_rejects_out_of_range(self):
        from src.agents.scoring_assurance_analyst import _validate
        scored = {**_base_scored(), "opportunity_priority_score": 150}
        failures = _validate(scored)
        assert any("opportunity_priority_score" in f for f in failures), (
            "Expected failure for out-of-range priority score"
        )


class TestDigestSortByPriority:
    def _opp(self, priority, relevance, opp_id=1):
        return {
            "id": opp_id,
            "title": f"Opp {opp_id}",
            "org": "Test Org",
            "deadline": None,
            "value": None,
            "url": f"https://test.example.com/rfp/{opp_id}",
            "source": "MERX",
            "relevance_score": relevance,
            "recommendation": "PURSUE",
            "score_rationale": "Good match",
            "capability_match": [],
            "risks": [],
            "estimated_effort": "M",
            "exec_summary": "Summary",
            "suggested_angle": "Lead with data",
            "decision_log": [],
            "opportunity_priority_score": priority,
        }

    def test_sorted_by_priority_descending(self):
        from src.agents.intelligence_delivery_agent import build_html
        opps = [
            self._opp(priority=40, relevance=80, opp_id=1),
            self._opp(priority=85, relevance=70, opp_id=2),
            self._opp(priority=60, relevance=75, opp_id=3),
        ]
        stats = {
            "scraped": 3, "filtered": 3, "pursue": 3,
            "consider": 0, "skip": 0, "contacts": 0, "drafts": 0,
        }
        html = build_html(opps, {1: [], 2: [], 3: []}, stats)
        # Opp 2 (priority=85) should appear before Opp 1 (priority=40)
        pos_opp2 = html.find("Opp 2")
        pos_opp1 = html.find("Opp 1")
        assert pos_opp2 < pos_opp1, (
            f"Opp 2 (priority=85) should appear before Opp 1 (priority=40). "
            f"pos_opp2={pos_opp2}, pos_opp1={pos_opp1}"
        )

    def test_priority_badge_in_html(self):
        from src.agents.intelligence_delivery_agent import build_html
        opps = [self._opp(priority=75, relevance=80, opp_id=1)]
        stats = {
            "scraped": 1, "filtered": 1, "pursue": 1,
            "consider": 0, "skip": 0, "contacts": 0, "drafts": 0,
        }
        html = build_html(opps, {1: []}, stats)
        assert "Score 75" in html, "Priority badge must appear in HTML output"

    def test_priority_badge_deep_green_for_high_score(self):
        from src.agents.intelligence_delivery_agent import _priority_badge_color
        assert _priority_badge_color(85) == "#15803d"

    def test_priority_badge_blue_for_mid_score(self):
        from src.agents.intelligence_delivery_agent import _priority_badge_color
        assert _priority_badge_color(65) == "#1d4ed8"

    def test_priority_badge_amber_for_low_mid(self):
        from src.agents.intelligence_delivery_agent import _priority_badge_color
        assert _priority_badge_color(45) == "#b45309"

    def test_priority_badge_gray_for_low(self):
        from src.agents.intelligence_delivery_agent import _priority_badge_color
        assert _priority_badge_color(25) == "#6b7280"


class TestGeoAffinityScore:
    """v2: geographic affinity scoring — BC/WA/OR/CA = 100, other CA/US = 50, unknown = 30."""

    def test_bcbid_source_is_100(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({"source": "BCBid"}) == 100

    def test_bc_org_name_is_100(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({"org": "City of Vancouver", "source": "MERX"}) == 100

    def test_bc_hydro_org_is_100(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({"org": "BC Hydro", "source": "MERX"}) == 100

    def test_washington_state_org_is_100(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({"org": "Washington State DOT", "source": "RFPMart"}) == 100

    def test_seattle_in_title_is_100(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({"title": "City of Seattle Analytics Platform", "source": "RFPMart"}) == 100

    def test_oregon_in_description_is_100(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({
            "raw_description": "State of Oregon Health Analytics modernization.",
            "source": "RFPMart",
        }) == 100

    def test_california_in_description_is_100(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({
            "raw_description": "Department of California Health Analytics platform.",
            "source": "RFPMart",
        }) == 100

    def test_ontario_org_is_50(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({"org": "Ontario Government Services", "source": "MERX"}) == 50

    def test_federal_canada_is_50(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({"org": "Government of Canada", "source": "CanadaBuys"}) == 50

    def test_unknown_location_is_30(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({"org": "XYZ Corp", "source": "MERX"}) == 30

    def test_bc_location_field_is_100(self):
        """location field (stored by MERX/BidNet scrapers) is used for geo scoring."""
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({"org": "Ministry of Health", "location": "British Columbia", "source": "MERX"}) == 100

    def test_bidnet_bc_location_field_is_100(self):
        from src.agents.strategic_scoring_agent import _geo_affinity_score
        assert _geo_affinity_score({"org": "Government of British Columbia", "location": "British Columbia", "source": "BidNet"}) == 100

    def test_geo_boost_raises_priority_for_bcbid(self):
        """BCBid opportunities score higher than identical non-BC opportunities."""
        from src.agents.strategic_scoring_agent import compute_priority_score
        base_listing = {
            "title": "Data Platform RFP",
            "org": "Ministry of Finance",
            "deadline": "2030-01-01",
            "value": "500K",
            "url": "https://test.example.com/rfp/geo/1",
            "raw_description": "Cloud data analytics platform procurement.",
        }
        scored = {
            "relevance_score": 75,
            "recommendation": "PURSUE",
            "capability_match": ["Snowflake", "Power BI"],
            "risks": [],
        }
        bc_score = compute_priority_score({**base_listing, "source": "BCBid"}, scored)
        other_score = compute_priority_score({**base_listing, "source": "MERX", "org": "Ministry of Finance"}, scored)
        assert bc_score > other_score, (
            "BCBid (BC) opportunity should score higher than equivalent non-BC opportunity"
        )
