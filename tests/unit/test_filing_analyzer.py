"""
Unit tests for analysis/filing_analyzer.py

Tests red flag detection, health score computation, section context building,
and the full analyze_filing pipeline. Claude API calls are always mocked.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.filing_analyzer import (
    RedFlag,
    _build_analysis_context,
    compute_health_score,
    detect_red_flags,
)
from core.models import Filing, FilingSection

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture_sections(filename: str) -> dict[str, str]:
    """
    Load a fixture HTML file, strip iXBRL, split into sections,
    and return sections dict.
    """
    from ingestion.sec_edgar import split_into_sections, strip_ixbrl

    html = (FIXTURES / filename).read_text(encoding="utf-8")
    text = strip_ixbrl(html)
    return split_into_sections(text)


# ---------------------------------------------------------------------------
# detect_red_flags
# ---------------------------------------------------------------------------


class TestDetectRedFlags:
    def test_clean_filing_has_no_flags(self):
        """A normal 10-K with no distress language should have zero red flags."""
        sections = _load_fixture_sections("sample_10k.html")
        flags = detect_red_flags(sections)
        assert flags == []

    def test_going_concern_fixture_detected(self):
        """The going-concern fixture should trigger the going_concern flag."""
        sections = _load_fixture_sections("sample_10k_going_concern.html")
        flags = detect_red_flags(sections)
        flag_names = {f.name for f in flags}
        assert "going_concern" in flag_names

    def test_material_weakness_detected(self):
        """material weakness in internal control → flag."""
        sections = {
            "item 9a": "We identified a material weakness in internal control over financial reporting."
        }
        flags = detect_red_flags(sections)
        assert any(f.name == "material_weakness" for f in flags)

    def test_auditor_change_detected(self):
        # Pattern: dismissed (our|the) (independent|registered) [public ]accounting
        sections = {"item 9": "We dismissed our registered public accounting firm Ernst & Young."}
        flags = detect_red_flags(sections)
        assert any(f.name == "auditor_change" for f in flags)

    def test_sec_investigation_detected(self):
        sections = {"item 3": "The SEC investigation into our accounting practices is ongoing."}
        flags = detect_red_flags(sections)
        assert any(f.name == "sec_investigation" for f in flags)

    def test_class_action_detected(self):
        sections = {"item 3": "A securities class action lawsuit was filed against the company."}
        flags = detect_red_flags(sections)
        assert any(f.name == "class_action" for f in flags)

    def test_restatement_detected(self):
        sections = {
            "item 8": "We have determined that a restatement of financial statements is necessary."
        }
        flags = detect_red_flags(sections)
        assert any(f.name == "restatement" for f in flags)

    def test_deduplication_across_sections(self):
        """Same flag found in multiple sections should only appear once."""
        sections = {
            "item 1a": "going concern doubt exists.",
            "item 8": "substantial doubt about its ability to continue as a going concern.",
        }
        flags = detect_red_flags(sections)
        going_concern_flags = [f for f in flags if f.name == "going_concern"]
        assert len(going_concern_flags) == 1

    def test_non_flag_sections_ignored(self):
        """Flags in non-signal sections (e.g. item 2) should not be detected."""
        sections = {"item 2": "going concern risk factors material weakness"}
        flags = detect_red_flags(sections)
        # item 2 is not in _FLAG_SECTIONS, so should not trigger
        assert flags == []

    def test_full_text_fallback_scanned(self):
        """full_text key is a valid section for scanning."""
        sections = {"full_text": "We have substantial doubt about its ability to continue."}
        flags = detect_red_flags(sections)
        assert any(f.name == "going_concern" for f in flags)

    def test_quote_trimmed_to_200_chars(self):
        """Quote in RedFlag should not exceed 200 characters."""
        sections = {"item 8": "going concern " + "x" * 300}
        flags = detect_red_flags(sections)
        for f in flags:
            assert len(f.quote) <= 200

    def test_returns_redflag_objects(self):
        sections = {"item 9a": "material weakness in internal control"}
        flags = detect_red_flags(sections)
        assert all(isinstance(f, RedFlag) for f in flags)
        assert all(f.severity in {"high", "medium", "low"} for f in flags)


# ---------------------------------------------------------------------------
# compute_health_score
# ---------------------------------------------------------------------------


class TestComputeHealthScore:
    def test_no_flags_returns_100(self):
        assert compute_health_score([]) == 100.0

    def test_single_high_flag(self):
        flags = [RedFlag("going_concern", "high", "...", "item 8")]
        score = compute_health_score(flags)
        assert score == 75.0  # 100 - 25

    def test_single_medium_flag(self):
        flags = [RedFlag("class_action", "medium", "...", "item 3")]
        score = compute_health_score(flags)
        assert score == 88.0  # 100 - 12

    def test_multiple_flags_accumulate(self):
        flags = [
            RedFlag("going_concern", "high", "...", "item 8"),
            RedFlag("material_weakness", "high", "...", "item 9a"),
            RedFlag("class_action", "medium", "...", "item 3"),
        ]
        score = compute_health_score(flags)
        # 100 - 25 - 25 - 12 = 38
        assert score == 38.0

    def test_score_floored_at_zero(self):
        """Multiple high-severity flags cannot push score below 0."""
        flags = [
            RedFlag(f"flag_{i}", "high", "...", "item 8")
            for i in range(10)  # 10 × 25 = 250 penalty → floor to 0
        ]
        score = compute_health_score(flags)
        assert score == 0.0

    def test_score_is_float(self):
        score = compute_health_score([])
        assert isinstance(score, float)


# ---------------------------------------------------------------------------
# _build_analysis_context
# ---------------------------------------------------------------------------


class TestBuildAnalysisContext:
    def test_prefers_item7_first(self):
        sections = {
            "Item 7": "MD&A content here.",
            "Item 1A": "Risk factors here.",
            "Item 8": "Financial statements.",
        }
        context = _build_analysis_context(sections)
        # Item 7 should appear before Item 1A
        assert context.index("MD&A") < context.index("Risk factors")

    def test_section_headers_included(self):
        sections = {"Item 7": "MD&A content."}
        context = _build_analysis_context(sections)
        assert "=== Item 7 ===" in context

    def test_fallback_to_full_text(self):
        sections = {"full_text": "Complete filing text."}
        context = _build_analysis_context(sections)
        assert "Complete filing text" in context

    def test_no_sections_returns_fallback_message(self):
        context = _build_analysis_context({})
        assert "No filing content available" in context

    def test_truncated_at_max_chars(self):
        long_content = "x" * 50_000
        sections = {"Item 7": long_content}
        context = _build_analysis_context(sections)
        assert len(context) <= 40_200  # 40K + header overhead


# ---------------------------------------------------------------------------
# analyze_filing (integration with mocked DB + optional Claude)
# ---------------------------------------------------------------------------


class TestAnalyzeFiling:
    @pytest.mark.asyncio
    async def test_skips_unparsed_filing(self, db_session: AsyncSession, sample_ticker):
        """Filing with is_parsed=False should be skipped."""
        from analysis.filing_analyzer import analyze_filing

        filing = Filing(
            ticker_id=sample_ticker.id,
            filing_type="10-K",
            period_of_report=date(2024, 12, 31),
            filed_date=date(2025, 1, 15),
            accession_number="0001-test-001",
            is_parsed=False,
            is_analyzed=False,
        )
        db_session.add(filing)
        await db_session.flush()

        result = await analyze_filing(db_session, filing)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_with_no_sections(self, db_session: AsyncSession, sample_ticker):
        """A parsed filing with no sections should return None."""
        from analysis.filing_analyzer import analyze_filing

        filing = Filing(
            ticker_id=sample_ticker.id,
            filing_type="10-K",
            period_of_report=date(2024, 12, 31),
            filed_date=date(2025, 1, 15),
            accession_number="0001-test-002",
            is_parsed=True,
            is_analyzed=False,
        )
        db_session.add(filing)
        await db_session.flush()

        result = await analyze_filing(db_session, filing)
        assert result is None

    @pytest.mark.asyncio
    async def test_stage1_only_no_api_key(self, db_session: AsyncSession, sample_ticker):
        """With no API key, only Stage 1 (regex) runs. Should return FilingAnalysis."""
        from analysis.filing_analyzer import analyze_filing
        from core.models import FilingAnalysis

        filing = Filing(
            ticker_id=sample_ticker.id,
            filing_type="10-K",
            period_of_report=date(2024, 12, 31),
            filed_date=date(2025, 1, 15),
            accession_number="0001-test-003",
            is_parsed=True,
            is_analyzed=False,
        )
        db_session.add(filing)
        await db_session.flush()

        section = FilingSection(
            filing_id=filing.id,
            section_name="item 8",
            content="The company has going concern issues.",
            word_count=8,
        )
        db_session.add(section)
        await db_session.flush()

        result = await analyze_filing(db_session, filing, anthropic_api_key=None)

        assert result is not None
        assert isinstance(result, FilingAnalysis)
        assert result.health_score < 100  # going concern flag should deduct points
        assert result.red_flags is not None
        assert any(f["name"] == "going_concern" for f in result.red_flags)

    @pytest.mark.asyncio
    async def test_stage2_with_mock_claude(self, db_session: AsyncSession, sample_ticker):
        """With a mock Claude response, Stage 2 should populate summary + metrics."""
        from analysis.filing_analyzer import analyze_filing

        claude_payload = {
            "summary": "Strong revenue growth with some margin pressure.",
            "bull_points": ["Revenue +22%", "Margin expansion"],
            "bear_points": ["High debt", "Competition"],
            "financial_metrics": {
                "revenue": 3200,
                "revenue_growth_pct": 22.0,
                "gross_margin_pct": 65.0,
                "operating_margin_pct": 18.0,
                "net_income": 580,
                "fcf": 420,
                "debt_to_equity": 0.4,
            },
            "health_assessment": "good",
        }

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(claude_payload))]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        filing = Filing(
            ticker_id=sample_ticker.id,
            filing_type="10-K",
            period_of_report=date(2024, 12, 31),
            filed_date=date(2025, 1, 15),
            accession_number="0001-test-004",
            is_parsed=True,
            is_analyzed=False,
        )
        db_session.add(filing)
        await db_session.flush()

        section = FilingSection(
            filing_id=filing.id,
            section_name="Item 7",
            content="Revenue increased 22% to $3.2 billion.",
            word_count=7,
        )
        db_session.add(section)
        await db_session.flush()

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            result = await analyze_filing(
                db_session, filing, anthropic_api_key="test-key"
            )  # pragma: allowlist secret

        assert result is not None
        assert result.summary == "Strong revenue growth with some margin pressure."
        assert result.bull_points == ["Revenue +22%", "Margin expansion"]
        assert result.model_used == "claude-sonnet-4-6"
        assert result.financial_metrics["revenue"] == 3200

    @pytest.mark.asyncio
    async def test_returns_existing_analysis_without_force(
        self, db_session: AsyncSession, sample_ticker
    ):
        """analyze_filing should skip re-analysis if analysis exists and force=False."""
        from analysis.filing_analyzer import analyze_filing
        from core.models import FilingAnalysis

        filing = Filing(
            ticker_id=sample_ticker.id,
            filing_type="10-K",
            period_of_report=date(2024, 12, 31),
            filed_date=date(2025, 1, 15),
            accession_number="0001-test-005",
            is_parsed=True,
            is_analyzed=True,
        )
        db_session.add(filing)
        await db_session.flush()

        existing = FilingAnalysis(
            filing_id=filing.id,
            health_score=85.0,
            red_flags=[],
        )
        db_session.add(existing)
        await db_session.flush()

        result = await analyze_filing(db_session, filing, force=False)
        assert result is not None
        assert result.health_score == 85.0
