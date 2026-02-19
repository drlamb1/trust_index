"""
EdgeFinder — Buy The Dip Scorer (Phase 4)

8-dimension scoring engine that evaluates whether a price drop represents
a genuine buying opportunity.

Phase 4 implementation:

DipScore dimensions (weighted composite → 0-100):
  0.25 × price_drop_magnitude     # How far has it fallen? (vs historical vol)
  0.20 × fundamental_score        # Filing health score (from filing_analyzer)
  0.15 × technical_setup          # RSI oversold + near support level
  0.15 × sentiment_context        # Why did it drop? (news-driven vs systematic)
  0.10 × insider_activity         # Form 4 cluster buys in last 7 days
  0.10 × institutional_support    # 13F adds in last quarter
  0.05 × sector_relative          # Sector down too? (systematic) or isolated?

Alert tiers:
  Green  (70-80): Moderate dip in quality name — worth watching
  Yellow (80-90): Strong dip with intact fundamentals
  Red    (90-100): Exceptional — deep dip, strong fundamentals, insiders buying
"""

# Phase 4 stub
raise ImportError("buy_the_dip.py is implemented in Phase 4. See README.md.")
