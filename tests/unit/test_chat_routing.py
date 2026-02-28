"""Tests for chat persona routing — prefix, keywords, defaults."""

from __future__ import annotations

import pytest

from chat.router import _check_keywords, _check_prefix, route_message


class TestPrefixRouting:
    def test_at_edge(self):
        persona, cleaned = _check_prefix("@edge hello there")
        assert persona == "edge"
        assert cleaned == "hello there"

    def test_slash_edge(self):
        persona, cleaned = _check_prefix("/edge what's up")
        assert persona == "edge"
        assert cleaned == "what's up"

    def test_at_analyst_still_works(self):
        persona, cleaned = _check_prefix("@analyst show me NVDA")
        assert persona == "analyst"
        assert cleaned == "show me NVDA"

    def test_at_thesis_lord(self):
        persona, _ = _check_prefix("@thesis_lord generate a thesis")
        assert persona == "thesis_lord"

    def test_no_prefix(self):
        persona, cleaned = _check_prefix("hello world")
        assert persona is None
        assert cleaned == "hello world"

    def test_case_insensitive(self):
        persona, _ = _check_prefix("@EDGE yo")
        assert persona == "edge"


class TestKeywordRouting:
    def test_no_keywords_for_edge(self):
        """Edge should NOT be triggered by keywords — it's the catch-all."""
        # General/ambiguous messages should NOT match any keyword pattern
        assert _check_keywords("what's happening?") is None
        assert _check_keywords("how are things?") is None
        assert _check_keywords("hello") is None
        assert _check_keywords("what should I look at today?") is None

    def test_specialist_keywords_still_work(self):
        assert _check_keywords("show me the vol surface") == "vol_slayer"
        assert _check_keywords("run a backtest") == "thesis_lord"
        assert _check_keywords("heston calibration") == "heston_cal"
        assert _check_keywords("post-mortem on thesis 5") == "post_mortem"
        assert _check_keywords("I wish the app could do X") == "pm"
        assert _check_keywords("what if we look at risk-reward") == "thesis"


class TestDefaultFallback:
    @pytest.mark.asyncio
    async def test_default_is_edge(self):
        """Without prefix, keywords, API key, or current persona — default to edge."""
        persona, text = await route_message("hey what's up", current_persona=None, api_key=None)
        assert persona == "edge"
        assert text == "hey what's up"

    @pytest.mark.asyncio
    async def test_current_persona_preserved(self):
        """If already talking to analyst, stay with analyst."""
        persona, _ = await route_message("tell me more", current_persona="analyst", api_key=None)
        assert persona == "analyst"

    @pytest.mark.asyncio
    async def test_prefix_overrides_current(self):
        """Explicit prefix beats current persona."""
        persona, cleaned = await route_message("@thesis what if NVDA drops 20%", current_persona="analyst", api_key=None)
        assert persona == "thesis"
        assert "what if NVDA drops 20%" in cleaned
