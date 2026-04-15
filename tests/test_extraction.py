"""
Tests for extraction_utils.py and regex_profiles.py.

Verifies: non-empty extraction, portal regex firing, capability keyword retention,
token budget enforcement, and fallback activation.
"""
import os
import pytest

os.environ.setdefault("DRY_RUN", "true")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CAPABILITIES = ["Snowflake", "Power BI", "dbt", "Tableau", "Databricks", "Azure"]

_SAMPLE_TEXT = """\
Background

The City of Vancouver seeks a qualified vendor to deliver a modern data analytics platform.

Scope of Work

The selected vendor will be responsible for data engineering using dbt and Snowflake,
business intelligence dashboards in Power BI, and cloud infrastructure on Azure.
The engagement includes ETL pipeline design, data quality checks, and governance framework.

Evaluation Criteria

Proposals will be rated on technical capability, past experience with Snowflake and Power BI,
project management methodology, and cost. Mandatory requirement: ISO27001 certification.

Deliverables

1. Data platform architecture document
2. Deployed Snowflake warehouse with dbt transformations
3. Power BI dashboard suite
4. Data governance framework documentation

Qualifications

The vendor must demonstrate a minimum of three completed cloud data warehouse projects
using Snowflake or equivalent, with at least one public sector client.
"""

_SHORT_TEXT = "This is a very short document about procurement."


class TestSegmentParagraphs:
    def test_returns_list(self):
        from src.agents.extraction_utils import segment_paragraphs
        result = segment_paragraphs(_SAMPLE_TEXT)
        assert isinstance(result, list)

    def test_at_least_one_segment(self):
        from src.agents.extraction_utils import segment_paragraphs
        result = segment_paragraphs(_SAMPLE_TEXT)
        assert len(result) >= 1

    def test_empty_text_returns_empty(self):
        from src.agents.extraction_utils import segment_paragraphs
        assert segment_paragraphs("") == []


class TestScoreTitleSimilarity:
    def test_matching_title_returns_positive(self):
        from src.agents.extraction_utils import score_title_similarity
        para = "The data analytics platform will use Snowflake and Power BI for reporting."
        title = "Data Analytics Platform Procurement"
        score = score_title_similarity(para, title)
        assert score > 0.0

    def test_empty_title_returns_zero(self):
        from src.agents.extraction_utils import score_title_similarity
        assert score_title_similarity("some text", "") == 0.0

    def test_unrelated_text_returns_low_score(self):
        from src.agents.extraction_utils import score_title_similarity
        para = "Construction of a new municipal bridge over the river."
        title = "Data Analytics Platform"
        score = score_title_similarity(para, title)
        assert score < 0.3


class TestScoreCapabilityMatch:
    def test_keyword_present_returns_nonzero(self):
        from src.agents.extraction_utils import score_capability_match
        para = "We will use Snowflake and Power BI for the dashboard."
        result = score_capability_match(para, _CAPABILITIES)
        assert result >= 2

    def test_no_keywords_returns_zero(self):
        from src.agents.extraction_utils import score_capability_match
        para = "Civil engineering project for bridge construction."
        result = score_capability_match(para, _CAPABILITIES)
        assert result == 0

    def test_empty_capabilities_returns_zero(self):
        from src.agents.extraction_utils import score_capability_match
        assert score_capability_match("Snowflake dbt Azure", []) == 0


class TestMergeAndDedupe:
    def test_identical_strings_deduplicated(self):
        from src.agents.extraction_utils import merge_and_dedupe
        sections = ["foo bar baz qux alpha", "foo bar baz qux alpha"]
        result = merge_and_dedupe(sections)
        assert len(result) == 1

    def test_distinct_strings_both_kept(self):
        from src.agents.extraction_utils import merge_and_dedupe
        sections = [
            "Snowflake data warehouse analytics platform engineering",
            "Legal services civil engineering construction infrastructure hardware",
        ]
        result = merge_and_dedupe(sections)
        assert len(result) == 2

    def test_empty_input_returns_empty(self):
        from src.agents.extraction_utils import merge_and_dedupe
        assert merge_and_dedupe([]) == []


class TestEnforceTokenBudget:
    def test_short_text_unchanged(self):
        from src.agents.extraction_utils import enforce_token_budget
        text = "short text"
        assert enforce_token_budget(text, max_words=100) == text

    def test_long_text_truncated(self):
        from src.agents.extraction_utils import enforce_token_budget
        text = " ".join(f"word{i}" for i in range(500))
        result = enforce_token_budget(text, max_words=100)
        assert len(result.split()) == 100


class TestExtractRfpContent:
    def test_non_empty_extraction(self):
        from src.agents.extraction_utils import extract_rfp_content
        result = extract_rfp_content(_SAMPLE_TEXT, title="Data Analytics Platform")
        assert len(result.strip()) > 0

    def test_capability_keywords_retained(self):
        from src.agents.extraction_utils import extract_rfp_content
        result = extract_rfp_content(
            _SAMPLE_TEXT,
            title="Data Analytics Platform",
            capabilities=_CAPABILITIES,
        )
        # At least one capability keyword should appear in extracted content
        found = any(cap.lower() in result.lower() for cap in _CAPABILITIES)
        assert found, f"No capability keyword found in extraction: {result[:200]}"

    def test_token_cap_respected(self):
        from src.agents.extraction_utils import extract_rfp_content
        long_text = (_SAMPLE_TEXT + "\n\n") * 50  # ~200KB of text
        result = extract_rfp_content(long_text, title="Data Platform")
        word_count = len(result.split())
        assert word_count <= 2650, f"Token cap exceeded: {word_count} words"

    def test_fallback_fires_on_short_text(self):
        from src.agents.extraction_utils import extract_rfp_content
        result = extract_rfp_content(_SHORT_TEXT, title="Procurement")
        # Fallback returns first 2000 words of original — short text returned as-is
        assert len(result.strip()) > 0
        assert "procurement" in result.lower()

    def test_merx_regex_fires(self):
        from src.agents.regex_profiles import find_regex_hits
        merx_text = "1. Scope\nThis project covers data engineering and analytics.\n\n2. Deliverables\nA dashboard suite."
        hits = find_regex_hits(merx_text, "MERX")
        assert len(hits) > 0, "Expected MERX regex to fire on numbered section headers"

    def test_canadabuys_regex_fires(self):
        from src.agents.regex_profiles import find_regex_hits
        cb_text = "SCOPE\nThis project covers data engineering.\n\nEVALUATION\nProposals rated on capability."
        hits = find_regex_hits(cb_text, "CanadaBuys")
        assert len(hits) > 0, "Expected CanadaBuys regex to fire on ALL-CAPS headers"

    def test_unknown_portal_returns_empty_regex(self):
        from src.agents.regex_profiles import get_regex_profile
        patterns = get_regex_profile("UnknownPortal")
        assert patterns == []


# ---------------------------------------------------------------------------
# parse_rfp_metadata
# ---------------------------------------------------------------------------

class TestParseRfpMetadata:
    def test_extracts_budget(self):
        from src.agents.extraction_utils import parse_rfp_metadata
        html = "<p>Estimated Value: $2,500,000</p>"
        result = parse_rfp_metadata(html)
        assert "budget" in result
        assert "2,500,000" in result["budget"]

    def test_extracts_duration(self):
        from src.agents.extraction_utils import parse_rfp_metadata
        html = "<p>Contract Term: 24 months</p>"
        result = parse_rfp_metadata(html)
        assert "duration" in result
        assert "24" in result["duration"]

    def test_extracts_department(self):
        from src.agents.extraction_utils import parse_rfp_metadata
        html = "<p>Department: Ministry of Finance</p>"
        result = parse_rfp_metadata(html)
        assert "department" in result
        assert "Ministry" in result["department"]

    def test_extracts_closing_date_iso(self):
        from src.agents.extraction_utils import parse_rfp_metadata
        html = "<p>Closing Date: 2026-08-15</p>"
        result = parse_rfp_metadata(html)
        assert "closing_date" in result
        assert "2026-08-15" in result["closing_date"]

    def test_returns_empty_for_no_match(self):
        from src.agents.extraction_utils import parse_rfp_metadata
        result = parse_rfp_metadata("<p>General procurement notice with no structured fields.</p>")
        assert isinstance(result, dict)
        # Not all fields required — just must not raise

    def test_strips_html_tags(self):
        from src.agents.extraction_utils import parse_rfp_metadata
        html = "<div><strong>Budget:</strong> <span>$500,000</span></div>"
        result = parse_rfp_metadata(html)
        assert "budget" in result
