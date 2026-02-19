"""
EdgeFinder — Insider Trades (SEC Form 4) Parser (Phase 2)

Fetches and parses Form 4 filings (Statement of Changes in Beneficial Ownership)
to track insider buying and selling activity.

Cluster buys (multiple insiders buying within 7 days) are a high-signal
bullish indicator — especially when the stock is down.

Phase 2 implementation will include:
  - Form 4 XML parser (SEC structured data format)
  - Insider classification (CEO, CFO, Director, >10% owner)
  - Cluster buy detection (3+ insiders within 7 days = BUY_THE_DIP signal)
  - Dollar value normalization (shares × price)
"""

# Phase 2 stub
raise ImportError("insider_trades.py is implemented in Phase 2. See README.md.")
