"""
EdgeFinder — SEC Filing Analyzer (Phase 2)

NLP pipeline for analyzing SEC filings using Claude Sonnet.

Phase 2 implementation will include:
  - iXBRL tag stripping with lxml
  - Section splitting (Risk Factors, MD&A, Financial Statements)
  - Red flag detection (regex-based, no AI needed)
  - Claude Sonnet summarization (with prompt caching)
  - Financial metric extraction (revenue, margins, FCF, debt)
  - Period-over-period diff analysis
  - Filing health score (0-100)

Claude API cost optimizations:
  - Prompt caching: cache_control on system prompt (~90% cost reduction)
  - Hash gating: only re-analyze if raw_text_hash changed
  - Use Haiku for initial screening, Sonnet for deep analysis
"""

# Phase 2 stub
raise ImportError("filing_analyzer.py is implemented in Phase 2. See README.md.")
