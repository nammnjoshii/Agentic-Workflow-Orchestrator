"""
Tests for the 4-component weighted ContactCritic relevance scoring model.

Verifies: relevance_score exists, descending order, max 3 contacts,
retry trigger when all below threshold, component weight correctness.
"""
import os
import unittest.mock as mock

import pytest

os.environ.setdefault("DRY_RUN", "true")

_URL = "https://test.example.com/rfp/contact/1"


def _item(**kwargs):
    base = {
        "title": "Data Analytics Platform RFP",
        "org": "City of Vancouver",
        "url": _URL,
        "exec_summary": "Cloud analytics and data management platform for municipal reporting.",
        "suggested_angle": "Lead with data analytics expertise and cloud delivery track record.",
    }
    base.update(kwargs)
    return base


def _contact(**kwargs):
    c = {
        "name": "Jane Smith",
        "title": "Director of Data Analytics",
        "email": "jane@example.com",
        "linkedin_url": "https://linkedin.com/in/jane",
        "source": "Hunter",
    }
    c.update(kwargs)
    return c


def _run(contacts, dry_run=False, validated=None):
    """Run ContactCritic with controlled DRY_RUN flag."""
    validated = validated or [_item()]
    state = {
        "validated": validated,
        "contacts": {
            _URL: {
                "contacts": list(contacts),
                "website": None,
                "domain": "example.com",
            }
        },
        "enriched": [],
        "errors": [],
    }
    with mock.patch("src.agents.stakeholder_relevance_agent.DRY_RUN", dry_run):
        import src.agents.stakeholder_relevance_agent as m
        return m.StakeholderRelevanceAgent().run(state)


class TestContactScoringComponents:
    def test_seniority_director_scores_high(self):
        from src.agents.stakeholder_relevance_agent import _seniority_score
        words = {"director", "data", "analytics"}
        assert _seniority_score(words) == 100

    def test_seniority_manager_scores_mid(self):
        from src.agents.stakeholder_relevance_agent import _seniority_score
        words = {"manager", "procurement"}
        assert _seniority_score(words) == 37

    def test_seniority_no_match_scores_zero(self):
        from src.agents.stakeholder_relevance_agent import _seniority_score
        words = {"intern", "junior"}
        assert _seniority_score(words) == 0

    def test_domain_data_analytics_scores_high(self):
        from src.agents.stakeholder_relevance_agent import _domain_score
        words = {"data", "analytics"}
        assert _domain_score(words) == 100

    def test_domain_technology_scores_mid(self):
        from src.agents.stakeholder_relevance_agent import _domain_score
        words = {"technology", "director"}
        assert _domain_score(words) == 75

    def test_domain_no_match_scores_zero(self):
        from src.agents.stakeholder_relevance_agent import _domain_score
        words = {"civil", "engineer"}
        assert _domain_score(words) == 0

    def test_activity_signals_email_only(self):
        from src.agents.stakeholder_relevance_agent import _activity_signals_score
        c = {"email": "x@y.com", "linkedin_url": None}
        score = _activity_signals_score(c)
        assert score == 67

    def test_activity_signals_linkedin_only(self):
        from src.agents.stakeholder_relevance_agent import _activity_signals_score
        c = {"email": None, "linkedin_url": "https://linkedin.com/in/x"}
        score = _activity_signals_score(c)
        assert score == 33

    def test_activity_signals_both(self):
        from src.agents.stakeholder_relevance_agent import _activity_signals_score
        c = {"email": "x@y.com", "linkedin_url": "https://linkedin.com/in/x"}
        score = _activity_signals_score(c)
        assert score == 100

    def test_activity_signals_none(self):
        from src.agents.stakeholder_relevance_agent import _activity_signals_score
        c = {"email": None, "linkedin_url": None}
        score = _activity_signals_score(c)
        assert score == 0

    def test_activity_signals_linkedin_company_url(self):
        from src.agents.stakeholder_relevance_agent import _activity_signals_score
        c = {"email": None, "linkedin_url": "https://linkedin.com/company/bchydro"}
        score = _activity_signals_score(c)
        assert score == 0, f"Company LinkedIn URL should not score, got {score}"

    def test_activity_signals_email_domain_match(self):
        from src.agents.stakeholder_relevance_agent import _activity_signals_score
        c = {"email": "jane@bchydro.com", "linkedin_url": None}
        score = _activity_signals_score(c, org_domain="bchydro.com")
        assert score == 67, f"Org-domain email should score 67 (domain bonus moved to affiliation), got {score}"

    def test_activity_signals_email_domain_no_match(self):
        from src.agents.stakeholder_relevance_agent import _activity_signals_score
        c = {"email": "jane@gmail.com", "linkedin_url": None}
        score = _activity_signals_score(c, org_domain="bchydro.com")
        assert score == 67, f"Non-org email should score 67, got {score}"

    def test_org_proximity_context_match(self):
        from src.agents.stakeholder_relevance_agent import _org_proximity_score
        # 3 meaningful overlaps → 100
        words = {"data", "analytics", "cloud"}
        score = _org_proximity_score(
            words,
            suggested_angle="Lead with data analytics expertise.",
            exec_summary="Cloud platform for reporting.",
        )
        assert score == 100

    def test_org_proximity_no_context_match(self):
        from src.agents.stakeholder_relevance_agent import _org_proximity_score
        words = {"civil", "bridge"}
        score = _org_proximity_score(
            words,
            suggested_angle="Lead with data expertise.",
            exec_summary="Analytics platform for reporting.",
        )
        assert score == 0

    def test_org_proximity_stop_words_ignored(self):
        from src.agents.stakeholder_relevance_agent import _org_proximity_score
        # Title "Director of Finance" → meaningful words = {director, finance}
        # Context is pure stop words → 0 meaningful overlap
        words = {"director", "finance"}
        score = _org_proximity_score(
            words,
            suggested_angle="of the and for",
            exec_summary="is and the a",
        )
        assert score == 0, f"Stop-word-only context should give 0, got {score}"

    def test_org_proximity_graded_single_overlap(self):
        from src.agents.stakeholder_relevance_agent import _org_proximity_score
        # 1 meaningful overlap → 40
        words = {"finance", "director"}
        score = _org_proximity_score(
            words,
            suggested_angle="finance budget review",
            exec_summary="procurement and operations",
        )
        assert score == 40, f"Expected 40 for 1 overlap, got {score}"

    def test_org_proximity_graded_double_overlap(self):
        from src.agents.stakeholder_relevance_agent import _org_proximity_score
        # 2 meaningful overlaps → 70
        words = {"data", "governance"}
        score = _org_proximity_score(
            words,
            suggested_angle="data governance framework",
            exec_summary="compliance reporting",
        )
        assert score == 70, f"Expected 70 for 2 overlaps, got {score}"


class TestWeightedFinalScore:
    def test_director_data_with_all_signals_scores_high(self):
        from src.agents.stakeholder_relevance_agent import _score_contact
        contact = {
            "title": "Director of Data Analytics",
            "email": "d@example.com",
            "linkedin_url": "https://linkedin.com/in/d",
        }
        _, _, _, _, _, final = _score_contact(
            contact,
            suggested_angle="Lead with data analytics expertise.",
            exec_summary="Cloud analytics platform for municipal reporting.",
        )
        assert final >= 80, f"Expected high final score, got {final}"

    def test_intern_no_signals_scores_low(self):
        from src.agents.stakeholder_relevance_agent import _score_contact
        contact = {
            "title": "Administrative Intern",
            "email": None,
            "linkedin_url": None,
        }
        _, _, _, _, _, final = _score_contact(
            contact,
            suggested_angle="Lead with data analytics expertise.",
            exec_summary="Cloud analytics platform for municipal reporting.",
        )
        assert final < 30, f"Expected low final score, got {final}"

    def test_score_is_capped_at_100(self):
        from src.agents.stakeholder_relevance_agent import _score_contact
        contact = {
            "title": "Chief Data Officer",
            "email": "cdo@example.com",
            "linkedin_url": "https://linkedin.com/in/cdo",
        }
        _, _, _, _, _, final = _score_contact(
            contact,
            suggested_angle="data analytics cloud platform",
            exec_summary="data analytics cloud platform data",
        )
        assert final <= 100


class TestContactCriticIntegration:
    def test_relevance_score_field_present(self):
        result = _run([_contact()])
        contacts_out = [c for opp in result["enriched"] for c in opp.get("contacts", [])]
        assert contacts_out
        for c in contacts_out:
            assert "relevance_score" in c, f"Missing relevance_score: {c}"

    def test_contacts_sorted_descending(self):
        contacts = [
            _contact(name="Low", title="Administrative Intern", email=None, linkedin_url=None),
            _contact(name="High", title="Chief Data Officer",
                     email="high@example.com", linkedin_url="https://linkedin.com/in/high"),
        ]
        result = _run(contacts)
        scores = [c["relevance_score"] for opp in result["enriched"] for c in opp.get("contacts", [])]
        assert len(scores) >= 2
        assert scores == sorted(scores, reverse=True), f"Not sorted descending: {scores}"

    def test_max_3_contacts_retained(self):
        contacts = [
            _contact(name=f"Contact {i}", email=f"c{i}@example.com", linkedin_url=None)
            for i in range(6)
        ]
        result = _run(contacts)
        for opp in result["enriched"]:
            count = len(opp.get("contacts", []))
            assert count <= 3, f"Expected at most 3 contacts, got {count}"

    def test_retry_triggered_when_all_below_threshold(self):
        low_contacts = [_contact(title="Administrative Intern", email=None, linkedin_url=None)]
        better_contacts = [_contact(title="Director of Data Analytics")]

        with mock.patch(
            "src.agents.stakeholder_relevance_agent.enrich_opportunity",
            return_value={
                "contacts": better_contacts,
                "website": None,
                "domain": "example.com",
            },
        ) as mock_enrich:
            _run(low_contacts)
            assert mock_enrich.called, "Expected enrich_opportunity to be called on retry"

    def test_dry_run_assigns_fixed_score_80(self):
        contacts = [
            _contact(title="Administrative Intern", email=None, linkedin_url=None),
            _contact(name="Bob", title="Director of Data Analytics"),
        ]
        result = _run(contacts, dry_run=True)
        contacts_out = [c for opp in result["enriched"] for c in opp.get("contacts", [])]
        assert contacts_out
        for c in contacts_out:
            assert c.get("relevance_score") == 80, (
                f"Expected relevance_score=80 in DRY_RUN, got {c.get('relevance_score')}"
            )


class TestOrgAffiliationScore:
    def test_org_domain_email_match_is_100(self):
        from src.agents.stakeholder_relevance_agent import _org_affiliation_score
        c = {"email": "jane@bchydro.com", "source": "hunter"}
        assert _org_affiliation_score(c, org_domain="bchydro.com") == 100

    def test_hunter_source_is_75(self):
        from src.agents.stakeholder_relevance_agent import _org_affiliation_score
        c = {"email": "jane@gmail.com", "source": "hunter"}
        assert _org_affiliation_score(c, org_domain="bchydro.com") == 75

    def test_linkedin_source_is_50(self):
        from src.agents.stakeholder_relevance_agent import _org_affiliation_score
        c = {"email": None, "source": "linkedin"}
        assert _org_affiliation_score(c, org_domain="bchydro.com") == 50

    def test_unknown_source_is_50_neutral(self):
        from src.agents.stakeholder_relevance_agent import _org_affiliation_score
        c = {"email": None, "source": None}
        assert _org_affiliation_score(c, org_domain="bchydro.com") == 50

    def test_no_org_domain_falls_back_to_source(self):
        from src.agents.stakeholder_relevance_agent import _org_affiliation_score
        c = {"email": "jane@bchydro.com", "source": "hunter"}
        assert _org_affiliation_score(c, org_domain="") == 75

    def test_website_source_is_90(self):
        from src.agents.stakeholder_relevance_agent import _org_affiliation_score
        c = {"email": None, "source": "website"}
        assert _org_affiliation_score(c, org_domain="bchydro.com") == 90

    def test_apollo_source_is_75(self):
        from src.agents.stakeholder_relevance_agent import _org_affiliation_score
        c = {"email": None, "source": "apollo"}
        assert _org_affiliation_score(c, org_domain="bchydro.com") == 75


class TestExpandedTiers:
    def test_enterprise_architect_seniority_is_62(self):
        from src.agents.stakeholder_relevance_agent import _seniority_score
        words = {"enterprise", "architect"}
        assert _seniority_score(words) == 62

    def test_deputy_minister_seniority_is_100(self):
        from src.agents.stakeholder_relevance_agent import _seniority_score
        words = {"assistant", "deputy", "minister"}
        assert _seniority_score(words) == 100

    def test_decision_science_domain_is_100(self):
        from src.agents.stakeholder_relevance_agent import _domain_score
        words = {"decision", "science"}
        assert _domain_score(words) == 100

    def test_platform_engineering_domain_is_100(self):
        from src.agents.stakeholder_relevance_agent import _domain_score
        words = {"platform", "engineering"}
        assert _domain_score(words) == 100

    def test_cio_domain_is_75(self):
        from src.agents.stakeholder_relevance_agent import _domain_score
        # Chief Information Officer: domain "information" → tier 2 = 75
        words = {"information", "officer"}
        assert _domain_score(words) == 75

    def test_strategy_domain_is_75(self):
        from src.agents.stakeholder_relevance_agent import _domain_score
        words = {"director", "technology", "strategy"}
        assert _domain_score(words) == 75
