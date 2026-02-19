"""
EdgeFinder — SEC EDGAR Filing Downloader (Phase 2)

Fetches SEC filings from EDGAR using the structured submissions API
and the full-text document archive.

CRITICAL: SEC EDGAR enforces a 10 req/second rate limit.
Use the TokenBucket rate limiter for ALL requests to *.sec.gov.
Violation results in IP bans lasting hours.

Required User-Agent format (per SEC policy):
  "AppName/Version contact@email.com"
  Set via: EDGAR_USER_AGENT in .env

Phase 2 implementation will include:
  - TokenBucket rate limiter (10 req/s)
  - Exponential backoff on 429/503
  - Company submissions API (CIK lookup)
  - Filing index parser
  - iXBRL tag stripping
  - 10-K/10-Q section extraction (Item 1, 1A, 7, 7A, 8)
  - 8-K material event extraction
  - Incremental fetch (skip filings already in DB)
"""

# Phase 2 stub — implementation coming in Phase 2
raise ImportError("sec_edgar.py is implemented in Phase 2. See README.md.")
