"""Add performance indexes for Phase 2 filing queries

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-19

Adds indexes on columns that appear in Phase 2 query hot-paths:
  - filings.is_parsed / is_analyzed   — pending-filing queue scans
  - insider_trades.transaction_date   — cluster buy detection window
  - institutional_holdings.institution_cik + period_date — change computation
  - filings.raw_text_hash             — hash-gate dedup lookup
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # filings — fast lookup of un-parsed and un-analyzed filings
    # ------------------------------------------------------------------
    # WHERE is_parsed IS FALSE  (fetch_filings_for_ticker dedup check)
    op.create_index(
        "ix_filings_is_parsed",
        "filings",
        ["is_parsed"],
        postgresql_where=sa.text("is_parsed IS FALSE"),
    )
    # WHERE is_analyzed IS FALSE  (analyze_pending_filings queue)
    op.create_index(
        "ix_filings_is_analyzed",
        "filings",
        ["is_analyzed"],
        postgresql_where=sa.text("is_analyzed IS FALSE"),
    )
    # Hash-gate lookup (skip re-download when hash is unchanged)
    op.create_index("ix_filings_raw_text_hash", "filings", ["raw_text_hash"])

    # ------------------------------------------------------------------
    # insider_trades — cluster buy detection window query
    # Queries: WHERE ticker_id = X AND trade_type = 'buy' AND
    #          transaction_date BETWEEN start AND end
    # ------------------------------------------------------------------
    op.create_index(
        "ix_insider_trades_ticker_txn_date",
        "insider_trades",
        ["ticker_id", "transaction_date"],
    )

    # ------------------------------------------------------------------
    # institutional_holdings — position change computation
    # Queries: WHERE ticker_id = X AND institution_cik = Y AND
    #          period_date < current_period ORDER BY period_date DESC
    # ------------------------------------------------------------------
    op.create_index(
        "ix_institutional_cik_period",
        "institutional_holdings",
        ["institution_cik", "period_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_institutional_cik_period", table_name="institutional_holdings")
    op.drop_index("ix_insider_trades_ticker_txn_date", table_name="insider_trades")
    op.drop_index("ix_filings_raw_text_hash", table_name="filings")
    op.drop_index("ix_filings_is_analyzed", table_name="filings")
    op.drop_index("ix_filings_is_parsed", table_name="filings")
