"""add intraday_bars table

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-03-07 18:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intraday_bars",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticker_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval", sa.String(5), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(50), nullable=True, server_default="yfinance"),
        sa.ForeignKeyConstraint(
            ["ticker_id"],
            ["tickers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker_id", "timestamp", "interval",
            name="uq_intraday_bars_ticker_ts_interval",
        ),
    )
    op.create_index(
        "ix_intraday_bars_ticker_ts", "intraday_bars", ["ticker_id", "timestamp"]
    )
    op.create_index(
        "ix_intraday_bars_timestamp", "intraday_bars", ["timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_intraday_bars_timestamp", table_name="intraday_bars")
    op.drop_index("ix_intraday_bars_ticker_ts", table_name="intraday_bars")
    op.drop_table("intraday_bars")
