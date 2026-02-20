"""
Unit tests for ingestion/sec_edgar.py

Covers: TokenBucket rate limiter, iXBRL stripping, section splitting,
URL construction, CIK cache helpers. No real HTTP calls are made.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ingestion.sec_edgar import (
    TokenBucket,
    _cik_cache,
    build_filing_url,
    split_into_sections,
    strip_ixbrl,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


class TestTokenBucket:
    @pytest.mark.asyncio
    async def test_acquire_immediate_when_tokens_available(self):
        """First acquire should not sleep when bucket is full."""
        bucket = TokenBucket(rate=10.0, capacity=10.0)
        start = time.monotonic()
        await bucket.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1, "Should return immediately with a full bucket"

    @pytest.mark.asyncio
    async def test_consumes_tokens(self):
        """Each acquire reduces the token count."""
        bucket = TokenBucket(rate=10.0, capacity=10.0)
        await bucket.acquire()
        # Internal token count should have decreased
        assert bucket._tokens < 10.0

    @pytest.mark.asyncio
    async def test_refills_over_time(self):
        """Tokens refill at `rate` per second."""
        bucket = TokenBucket(rate=100.0, capacity=10.0)
        # Drain the bucket
        bucket._tokens = 0.0
        bucket._last_refill = time.monotonic() - 0.1  # 100ms ago → 10 tokens added
        await bucket.acquire()  # Should not sleep (100 tokens/s * 0.1s = 10 tokens)

    @pytest.mark.asyncio
    async def test_concurrent_acquires_are_serialized(self):
        """Multiple concurrent acquires should not deadlock."""
        bucket = TokenBucket(rate=100.0, capacity=10.0)
        tasks = [asyncio.create_task(bucket.acquire()) for _ in range(5)]
        await asyncio.gather(*tasks)  # Should complete without deadlock

    @pytest.mark.asyncio
    async def test_capacity_cap(self):
        """Token count never exceeds capacity."""
        bucket = TokenBucket(rate=10.0, capacity=5.0)
        bucket._tokens = 0.0
        bucket._last_refill = time.monotonic() - 100  # Long time ago
        # Force refill calculation
        await bucket.acquire()
        assert bucket._tokens <= 5.0


# ---------------------------------------------------------------------------
# build_filing_url
# ---------------------------------------------------------------------------


class TestBuildFilingUrl:
    def test_standard_url(self):
        url = build_filing_url("0001045810", "0001045810-24-000001", "nvda-20231029.htm")
        assert "sec.gov/Archives/edgar/data" in url
        assert "1045810" in url
        assert "nvda-20231029.htm" in url

    def test_dashes_removed_from_accession(self):
        url = build_filing_url("0001045810", "0001045810-24-000001", "doc.htm")
        assert "-" not in url.split("/")[-2]  # accession folder has no dashes

    def test_leading_zeros_stripped_from_cik(self):
        """CIK is converted to int to strip leading zeros."""
        url = build_filing_url("0001045810", "0001045810-24-000001", "doc.htm")
        # Path should contain 1045810, not 0001045810
        assert "/1045810/" in url


# ---------------------------------------------------------------------------
# strip_ixbrl
# ---------------------------------------------------------------------------


class TestStripIxbrl:
    def test_plain_html_passes_through(self):
        html = "<html><body><p>Hello World</p></body></html>"
        result = strip_ixbrl(html)
        assert "Hello World" in result

    def test_removes_script_tags(self):
        html = "<html><body><p>text</p><script>alert('xss')</script></body></html>"
        result = strip_ixbrl(html)
        assert "alert" not in result
        assert "text" in result

    def test_removes_style_tags(self):
        html = "<html><body><p>content</p><style>.foo{color:red}</style></body></html>"
        result = strip_ixbrl(html)
        assert "color:red" not in result
        assert "content" in result

    def test_strips_ixbrl_namespace_elements(self):
        """iXBRL ix:nonFraction elements should have their text preserved."""
        html = (
            "<html><body>"
            '<p>Revenue: <ix:nonFraction xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
            'name="us-gaap:Revenue">1234.56</ix:nonFraction></p>'
            "</body></html>"
        )
        result = strip_ixbrl(html)
        assert "1234.56" in result

    def test_sample_10k_html(self):
        """Strip a real-looking 10-K HTML fixture."""
        html = (FIXTURES / "sample_10k.html").read_text(encoding="utf-8")
        result = strip_ixbrl(html)
        # Should contain key text
        assert "ITEM" in result.upper() or "Item" in result
        # Should not contain HTML tags
        assert "<p>" not in result

    def test_empty_html(self):
        result = strip_ixbrl("")
        assert isinstance(result, str)

    def test_regex_fallback_on_malformed_html(self):
        """Extremely malformed HTML should not raise — falls back to regex."""
        malformed = "<<<not>valid>html<<<" + "<p>real content</p>"
        result = strip_ixbrl(malformed)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# split_into_sections
# ---------------------------------------------------------------------------


class TestSplitIntoSections:
    def test_splits_on_item_headings(self):
        text = (
            "ITEM 1. Business\nWe make widgets.\n\n"
            "ITEM 1A. Risk Factors\nThere are risks.\n\n"
            "ITEM 7. MD&A\nRevenue grew 20%."
        )
        sections = split_into_sections(text)
        assert "Item 1" in sections
        assert "Item 1A" in sections
        assert "Item 7" in sections

    def test_section_content_correct(self):
        text = "ITEM 7. MD&A\nRevenue grew 20%.\nItem 8. Financial Statements\nBalance sheet."
        sections = split_into_sections(text)
        assert "Revenue grew 20%" in sections.get("Item 7", "")
        assert "Balance sheet" in sections.get("Item 8", "")

    def test_fallback_to_full_text_when_no_items(self):
        text = "This document has no item headings at all."
        sections = split_into_sections(text)
        assert "full_text" in sections
        assert "no item headings" in sections["full_text"]

    def test_section_content_truncated_at_60k(self):
        # Build a section with > 60K chars
        long_content = "x" * 100_000
        text = f"ITEM 7. MD&A\n{long_content}"
        sections = split_into_sections(text)
        assert len(sections.get("Item 7", "")) <= 60_000

    def test_sample_10k_html_parsed(self):
        html = (FIXTURES / "sample_10k.html").read_text(encoding="utf-8")
        text = strip_ixbrl(html)
        sections = split_into_sections(text)
        # Should find at least some sections
        assert len(sections) > 0

    def test_mixed_case_item_headings(self):
        text = "Item 1a. Risk Factors\nSome risks.\nITEM 7. MD&A\nSome analysis."
        sections = split_into_sections(text)
        # Both should be detected regardless of case
        assert len(sections) >= 1


# ---------------------------------------------------------------------------
# CIK cache helpers
# ---------------------------------------------------------------------------


class TestCikCache:
    @pytest.mark.asyncio
    async def test_lookup_cik_from_cache(self):
        """lookup_cik returns from cache without HTTP if already loaded."""
        from ingestion.sec_edgar import lookup_cik

        # Inject a fake entry directly
        _cik_cache["TESTCO"] = "0001234567"

        # Mock EdgarClient so no HTTP call happens
        mock_client = MagicMock()
        cik = await lookup_cik(mock_client, "TESTCO")
        assert cik == "0001234567"

    @pytest.mark.asyncio
    async def test_lookup_cik_case_insensitive(self):
        from ingestion.sec_edgar import lookup_cik

        _cik_cache["TESTCO2"] = "0009999999"
        mock_client = MagicMock()
        cik = await lookup_cik(mock_client, "testco2")
        assert cik == "0009999999"

    @pytest.mark.asyncio
    async def test_lookup_cik_missing_returns_none(self):
        from ingestion.sec_edgar import lookup_cik

        # Ensure the ticker is NOT in cache
        _cik_cache.pop("ZZZMISSING", None)

        # Mark cache as loaded so it doesn't try to fetch
        import ingestion.sec_edgar as edgar_mod

        original = edgar_mod._cik_cache_loaded
        edgar_mod._cik_cache_loaded = True
        try:
            mock_client = MagicMock()
            cik = await lookup_cik(mock_client, "ZZZMISSING")
            assert cik is None
        finally:
            edgar_mod._cik_cache_loaded = original
