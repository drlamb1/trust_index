"""Initial schema — all 15 EdgeFinder tables

Revision ID: 0001
Revises:
Create Date: 2026-02-18

Creates all tables with proper indexes, constraints, and PostgreSQL-specific
types (JSONB for flexible fields, INTEGER ARRAY for ticker_ids on news_articles).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # tickers
    # ------------------------------------------------------------------
    op.create_table(
        "tickers",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("market_cap", sa.Float(), nullable=True),
        sa.Column("cik", sa.String(20), nullable=True),
        sa.Column("in_sp500", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("in_custom", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("in_watchlist", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("watchlist_priority", sa.Integer(), nullable=True),
        sa.Column("watchlist_notes", sa.Text(), nullable=True),
        sa.Column("thesis_tags", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sp500_added_date", sa.Date(), nullable=True),
        sa.Column("sp500_removed_date", sa.Date(), nullable=True),
        sa.Column("first_seen", sa.Date(), nullable=True),
        sa.Column("last_price_fetch", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"),
    )
    op.create_index("ix_tickers_symbol", "tickers", ["symbol"])
    op.create_index("ix_tickers_cik", "tickers", ["cik"])

    # ------------------------------------------------------------------
    # price_bars
    # ------------------------------------------------------------------
    op.create_table(
        "price_bars",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("adj_close", sa.Float(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="yfinance"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker_id", "date", name="uq_price_bars_ticker_date"),
    )
    op.create_index("ix_price_bars_ticker_date", "price_bars", ["ticker_id", "date"])

    # ------------------------------------------------------------------
    # technical_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "technical_snapshots",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("sma_20", sa.Float(), nullable=True),
        sa.Column("sma_50", sa.Float(), nullable=True),
        sa.Column("sma_100", sa.Float(), nullable=True),
        sa.Column("sma_200", sa.Float(), nullable=True),
        sa.Column("ema_20", sa.Float(), nullable=True),
        sa.Column("ema_50", sa.Float(), nullable=True),
        sa.Column("rsi_14", sa.Float(), nullable=True),
        sa.Column("macd", sa.Float(), nullable=True),
        sa.Column("macd_signal", sa.Float(), nullable=True),
        sa.Column("macd_histogram", sa.Float(), nullable=True),
        sa.Column("bb_upper", sa.Float(), nullable=True),
        sa.Column("bb_middle", sa.Float(), nullable=True),
        sa.Column("bb_lower", sa.Float(), nullable=True),
        sa.Column("bb_bandwidth", sa.Float(), nullable=True),
        sa.Column("atr_14", sa.Float(), nullable=True),
        sa.Column("volume_ratio_20d", sa.Float(), nullable=True),
        sa.Column("rs_vs_spy_20d", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker_id", "date", name="uq_tech_ticker_date"),
    )
    op.create_index("ix_tech_ticker_date", "technical_snapshots", ["ticker_id", "date"])

    # ------------------------------------------------------------------
    # filings
    # ------------------------------------------------------------------
    op.create_table(
        "filings",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("filing_type", sa.String(20), nullable=False),
        sa.Column("period_of_report", sa.Date(), nullable=True),
        sa.Column("filed_date", sa.Date(), nullable=True),
        sa.Column("accession_number", sa.String(50), nullable=True),
        sa.Column("primary_document_url", sa.Text(), nullable=True),
        sa.Column("raw_text_hash", sa.String(64), nullable=True),
        sa.Column("is_parsed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_analyzed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accession_number"),
    )
    op.create_index("ix_filings_filed_date", "filings", ["filed_date"])
    op.create_index(
        "ix_filings_ticker_type_date", "filings", ["ticker_id", "filing_type", "filed_date"]
    )

    # ------------------------------------------------------------------
    # filing_sections
    # ------------------------------------------------------------------
    op.create_table(
        "filing_sections",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("filing_id", sa.Integer(), nullable=False),
        sa.Column("section_name", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sections_filing_name", "filing_sections", ["filing_id", "section_name"])

    # ------------------------------------------------------------------
    # filing_analyses
    # ------------------------------------------------------------------
    op.create_table(
        "filing_analyses",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("filing_id", sa.Integer(), nullable=False),
        sa.Column("health_score", sa.Float(), nullable=True),
        sa.Column("red_flags", postgresql.JSONB(), nullable=True),
        sa.Column("financial_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("bull_points", postgresql.JSONB(), nullable=True),
        sa.Column("bear_points", postgresql.JSONB(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_used", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("filing_id"),
    )

    # ------------------------------------------------------------------
    # financial_metrics
    # ------------------------------------------------------------------
    op.create_table(
        "financial_metrics",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("period_end_date", sa.Date(), nullable=True),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("value", sa.Numeric(20, 4), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker_id",
            "period",
            "metric_name",
            name="uq_financial_metrics_ticker_period_name",
        ),
    )
    op.create_index(
        "ix_financial_metrics_ticker_period", "financial_metrics", ["ticker_id", "period"]
    )

    # ------------------------------------------------------------------
    # news_articles
    # ------------------------------------------------------------------
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column(
            "ticker_ids",
            postgresql.ARRAY(sa.Integer()),
            nullable=True,
        ),
        sa.Column("source_tier", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("source_name", sa.String(100), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("raw_content_hash", sa.String(64), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("sentiment_scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sentiment_model", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_content_hash"),
    )
    op.create_index("ix_news_published_tier", "news_articles", ["published_at", "source_tier"])
    op.create_index("ix_news_content_hash", "news_articles", ["raw_content_hash"])

    # ------------------------------------------------------------------
    # insider_trades
    # ------------------------------------------------------------------
    op.create_table(
        "insider_trades",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("accession_number", sa.String(50), nullable=True),
        sa.Column("insider_name", sa.String(255), nullable=False),
        sa.Column("insider_title", sa.String(100), nullable=True),
        sa.Column("trade_type", sa.String(20), nullable=False),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("price_per_share", sa.Float(), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=True),
        sa.Column("shares_owned_after", sa.Float(), nullable=True),
        sa.Column("filed_date", sa.Date(), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accession_number"),
    )
    op.create_index("ix_insider_trades_ticker_date", "insider_trades", ["ticker_id", "filed_date"])

    # ------------------------------------------------------------------
    # institutional_holdings
    # ------------------------------------------------------------------
    op.create_table(
        "institutional_holdings",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("institution_name", sa.String(255), nullable=False),
        sa.Column("institution_cik", sa.String(20), nullable=True),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("market_value", sa.Float(), nullable=True),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("change_shares", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker_id",
            "institution_cik",
            "period_date",
            name="uq_institutional_ticker_inst_period",
        ),
    )
    op.create_index(
        "ix_institutional_ticker_period", "institutional_holdings", ["ticker_id", "period_date"]
    )

    # ------------------------------------------------------------------
    # theses (before alerts which may reference them)
    # ------------------------------------------------------------------
    op.create_table(
        "theses",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("criteria_yaml", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    # ------------------------------------------------------------------
    # alerts
    # ------------------------------------------------------------------
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("context_json", postgresql.JSONB(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alerts_ticker_severity_created",
        "alerts",
        ["ticker_id", "severity", "created_at"],
    )

    # ------------------------------------------------------------------
    # dip_scores
    # ------------------------------------------------------------------
    op.create_table(
        "dip_scores",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("price_drop_magnitude", sa.Float(), nullable=True),
        sa.Column("drop_vs_historical_vol", sa.Float(), nullable=True),
        sa.Column("fundamental_score", sa.Float(), nullable=True),
        sa.Column("sentiment_context", sa.Float(), nullable=True),
        sa.Column("insider_activity", sa.Float(), nullable=True),
        sa.Column("institutional_support", sa.Float(), nullable=True),
        sa.Column("technical_setup", sa.Float(), nullable=True),
        sa.Column("sector_relative", sa.Float(), nullable=True),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alert_id"),
    )

    # ------------------------------------------------------------------
    # thesis_matches
    # ------------------------------------------------------------------
    op.create_table(
        "thesis_matches",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("thesis_id", sa.Integer(), nullable=False),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("match_reasons", postgresql.JSONB(), nullable=True),
        sa.Column(
            "matched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["thesis_id"], ["theses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thesis_id", "ticker_id", name="uq_thesis_matches_thesis_ticker"),
    )
    op.create_index("ix_thesis_matches_thesis_score", "thesis_matches", ["thesis_id", "score"])

    # ------------------------------------------------------------------
    # daily_briefings
    # ------------------------------------------------------------------
    op.create_table(
        "daily_briefings",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=True),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("market_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_channels", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date"),
    )


def downgrade() -> None:
    op.drop_table("daily_briefings")
    op.drop_table("thesis_matches")
    op.drop_table("dip_scores")
    op.drop_table("alerts")
    op.drop_table("theses")
    op.drop_table("institutional_holdings")
    op.drop_table("insider_trades")
    op.drop_table("news_articles")
    op.drop_table("financial_metrics")
    op.drop_table("filing_analyses")
    op.drop_table("filing_sections")
    op.drop_table("filings")
    op.drop_table("technical_snapshots")
    op.drop_table("price_bars")
    op.drop_table("tickers")
