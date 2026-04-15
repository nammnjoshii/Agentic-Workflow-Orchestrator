"""
Tests for ContactCritic weighted scoring model.
All 5 required assertions per docs/quality/testing.md spec.
"""
import importlib
import os
import unittest.mock as mock

import pytest

_URL = "https://test.example.com/rfp/1"


def _item(**kwargs):
    base = {
        "title": "Data Analytics Platform",
        "org": "City of Vancouver",
        "url": _URL,
        "exec_summary": "Analytics and data management platform for municipal reporting.",
        "suggested_angle": "Lead with data analytics expertise.",
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


class TestContactCriticScoring:
    def test_relevance_score_field_on_each_contact(self):
        """Every contact in enriched output must have a relevance_score field."""
        result = _run([_contact()])
        contacts_out = [c for opp in result["enriched"] for c in opp.get("contacts", [])]
        assert contacts_out, "Expected at least one contact in enriched output"
        for c in contacts_out:
            assert "relevance_score" in c, f"Missing relevance_score on contact: {c}"

    def test_contacts_sorted_descending(self):
        """Contacts must be ordered highest-to-lowest relevance_score."""
        contacts = [
            # Low scorer: Coordinator of Procurement, no signals
            _contact(
                name="Low Scorer",
                title="Coordinator of Procurement",
                email=None,
                linkedin_url=None,
            ),
            # High scorer: Director of Data Analytics, all signals
            _contact(
                name="High Scorer",
                title="Director of Data Analytics",
                email="high@example.com",
                linkedin_url="https://linkedin.com/in/high",
            ),
        ]
        result = _run(contacts)
        scores = [c["relevance_score"] for opp in result["enriched"] for c in opp.get("contacts", [])]
        assert len(scores) >= 2
        assert scores == sorted(scores, reverse=True), f"Contacts not sorted descending: {scores}"

    def test_top_3_contacts_only_retained(self):
        """Only top 1–3 contacts are kept after scoring."""
        contacts = [
            _contact(name=f"Contact {i}", email=f"c{i}@example.com", linkedin_url=None)
            for i in range(5)
        ]
        result = _run(contacts)
        for opp in result["enriched"]:
            count = len(opp.get("contacts", []))
            assert count <= 3, f"Expected at most 3 contacts, got {count}"

    def test_retry_triggered_when_all_below_threshold(self):
        """enrich_opportunity is called when all contacts score below 30."""
        # "Administrative Intern" — no seniority, no domain, no signals → score 0
        low_contacts = [_contact(
            title="Administrative Intern",
            email=None,
            linkedin_url=None,
        )]
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

    def test_dry_run_assigns_fixed_relevance_score(self):
        """In DRY_RUN mode, all contacts receive relevance_score=80 without scoring logic."""
        contacts = [
            _contact(title="Administrative Intern", email=None, linkedin_url=None),
            _contact(name="Bob Jones", title="Director of Data Analytics"),
        ]
        result = _run(contacts, dry_run=True)
        contacts_out = [c for opp in result["enriched"] for c in opp.get("contacts", [])]
        assert contacts_out, "Expected contacts in enriched output under DRY_RUN"
        for c in contacts_out:
            assert c.get("relevance_score") == 80, (
                f"Expected relevance_score=80 (DRY_RUN), got {c.get('relevance_score')}"
            )
