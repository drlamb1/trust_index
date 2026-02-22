"""add macro earnings transcript tables

Revision ID: 27095eeaeafc
Revises: 2cde21ace746
Create Date: 2026-02-21 17:54:50.551277

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '27095eeaeafc'
down_revision: Union[str, None] = '2cde21ace746'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('macro_indicators',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('series_id', sa.String(length=20), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('series_name', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('series_id', 'date', name='uq_macro_series_date')
    )
    op.create_index('ix_macro_series_date', 'macro_indicators', ['series_id', 'date'], unique=False)

    op.create_table('earnings_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ticker_id', sa.Integer(), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('hour', sa.String(length=10), nullable=True),
    sa.Column('eps_estimate', sa.Float(), nullable=True),
    sa.Column('eps_actual', sa.Float(), nullable=True),
    sa.Column('revenue_estimate', sa.Float(), nullable=True),
    sa.Column('revenue_actual', sa.Float(), nullable=True),
    sa.Column('eps_surprise_pct', sa.Float(), nullable=True),
    sa.Column('rev_surprise_pct', sa.Float(), nullable=True),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['ticker_id'], ['tickers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ticker_id', 'event_date', name='uq_earnings_ticker_date')
    )
    op.create_index('ix_earnings_event_date', 'earnings_events', ['event_date'], unique=False)
    op.create_index('ix_earnings_ticker_date', 'earnings_events', ['ticker_id', 'event_date'], unique=False)

    op.create_table('earnings_transcripts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ticker_id', sa.Integer(), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=True),
    sa.Column('quarter', sa.Integer(), nullable=False),
    sa.Column('fiscal_year', sa.Integer(), nullable=False),
    sa.Column('transcript_text', sa.Text(), nullable=True),
    sa.Column('word_count', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['ticker_id'], ['tickers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ticker_id', 'fiscal_year', 'quarter', name='uq_transcript_ticker_fy_q')
    )
    op.create_index('ix_transcript_ticker_date', 'earnings_transcripts', ['ticker_id', 'event_date'], unique=False)

    op.create_table('earnings_analyses',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('transcript_id', sa.Integer(), nullable=False),
    sa.Column('overall_sentiment', sa.Float(), nullable=True),
    sa.Column('management_tone', sa.String(length=20), nullable=True),
    sa.Column('forward_guidance_sentiment', sa.Float(), nullable=True),
    sa.Column('key_topics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('analyst_concerns', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('management_quotes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('bull_signals', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('bear_signals', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('tone_vs_prior', sa.String(length=20), nullable=True),
    sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('model_used', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['transcript_id'], ['earnings_transcripts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('transcript_id')
    )


def downgrade() -> None:
    op.drop_table('earnings_analyses')
    op.drop_index('ix_transcript_ticker_date', table_name='earnings_transcripts')
    op.drop_table('earnings_transcripts')
    op.drop_index('ix_earnings_ticker_date', table_name='earnings_events')
    op.drop_index('ix_earnings_event_date', table_name='earnings_events')
    op.drop_table('earnings_events')
    op.drop_index('ix_macro_series_date', table_name='macro_indicators')
    op.drop_table('macro_indicators')
