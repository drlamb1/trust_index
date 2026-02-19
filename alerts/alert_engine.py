"""
EdgeFinder — Alert Rule Engine (Phase 4)

Composable rule engine that fires alerts based on configurable conditions.
Rules are Python dataclasses — not hardcoded if/else chains.

Phase 4 implementation will include:
  - AlertRule dataclass (name, condition: Callable, severity, alert_type)
  - RuleContext (all signals for a ticker: rsi, dip_score, insider_buys, etc.)
  - Rule composition (AND, OR, NOT)
  - Deduplication (don't re-fire the same alert within N hours)
  - Rate limiting per ticker (max 3 alerts/day per type)
  - Integration with event_bus for SSE push

Example rule:
    DIP_WITH_INSIDER_BUY = AlertRule(
        name="dip_with_insider_buy",
        condition=lambda ctx: ctx.dip_score > 80 and ctx.insider_buys_7d > 0 and ctx.rsi < 30,
        severity="red",
        alert_type=AlertType.BUY_THE_DIP,
    )
"""

# Phase 4 stub
raise ImportError("alert_engine.py is implemented in Phase 4. See README.md.")
