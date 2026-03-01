"""Tests for chat persona configuration — especially The Edger."""

from __future__ import annotations

from chat.personas import PERSONAS, PersonaConfig, get_persona


class TestEdgePersonaExists:
    def test_edge_in_registry(self):
        assert "edge" in PERSONAS

    def test_all_nine_personas_registered(self):
        expected = {"edge", "analyst", "thesis", "pm", "thesis_lord", "vol_slayer", "heston_cal", "deep_hedge", "post_mortem"}
        assert set(PERSONAS.keys()) == expected

    def test_edge_config_fields(self):
        edge = PERSONAS["edge"]
        assert isinstance(edge, PersonaConfig)
        assert edge.name == "edge"
        assert edge.display_name == "The Edger"
        assert edge.color == "#ff4f81"
        assert edge.icon == "E"
        assert edge.model == "claude-sonnet-4-6"
        assert len(edge.system_prompt) > 100

    def test_edge_is_first_in_dict(self):
        """Edge should be first persona in registry (default landing)."""
        assert list(PERSONAS.keys())[0] == "edge"


class TestEdgeToolAccess:
    def test_edge_has_cross_domain_tools(self):
        """Edge should have tools from multiple specialist domains."""
        tools = set(PERSONAS["edge"].tools)
        # Market intelligence
        assert "get_watchlist_movers" in tools
        assert "get_technical_signals" in tools
        assert "get_macro_indicators" in tools
        # Thesis overview
        assert "get_thesis_lifecycle" in tools
        assert "get_paper_portfolio" in tools
        # Vol surface
        assert "get_vol_surface" in tools
        # Memories
        assert "get_agent_memories" in tools
        # Learning layer
        assert "get_learning_nugget" in tools
        assert "record_lesson_taught" in tools

    def test_edge_no_mutating_tools(self):
        """Edge should NOT have tools that mutate state (propose, backtest, kill)."""
        tools = set(PERSONAS["edge"].tools)
        forbidden = {"propose_thesis", "trigger_backtest", "mutate_thesis", "retire_thesis", "calibrate_heston_now", "write_post_mortem"}
        assert tools.isdisjoint(forbidden), f"Edge has forbidden tools: {tools & forbidden}"

    def test_edge_has_suggest_handoff(self):
        assert "suggest_handoff" in PERSONAS["edge"].tools

    def test_edge_has_conversation_summaries(self):
        assert "get_conversation_summaries" in PERSONAS["edge"].tools


class TestThesisGeniusReflection:
    def test_thesis_has_reflection_tools(self):
        """Thesis Genius should have tools to reflect on thesis outcomes."""
        tools = set(PERSONAS["thesis"].tools)
        assert "get_thesis_lifecycle" in tools
        assert "get_performance_attribution" in tools
        assert "get_paper_portfolio" in tools
        assert "get_agent_memories" in tools

    def test_thesis_no_mutating_tools(self):
        """Thesis Genius should NOT have tools that mutate state."""
        tools = set(PERSONAS["thesis"].tools)
        forbidden = {"propose_thesis", "trigger_backtest", "mutate_thesis", "retire_thesis"}
        assert tools.isdisjoint(forbidden), f"Thesis has forbidden tools: {tools & forbidden}"


class TestFallback:
    def test_get_persona_returns_edge_for_unknown(self):
        persona = get_persona("nonexistent_persona")
        assert persona.name == "edge"

    def test_get_persona_returns_analyst_for_analyst(self):
        persona = get_persona("analyst")
        assert persona.name == "analyst"

    def test_get_persona_returns_edge_for_edge(self):
        persona = get_persona("edge")
        assert persona.name == "edge"
