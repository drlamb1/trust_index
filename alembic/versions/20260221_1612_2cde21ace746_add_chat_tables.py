"""add chat tables

Revision ID: 2cde21ace746
Revises: 0002
Create Date: 2026-02-21 16:12:38.623136

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2cde21ace746'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('chat_conversations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('active_persona', sa.String(length=30), nullable=False),
    sa.Column('message_count', sa.Integer(), nullable=False),
    sa.Column('total_input_tokens', sa.Integer(), nullable=False),
    sa.Column('total_output_tokens', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('chat_messages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('persona', sa.String(length=30), nullable=True),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('tool_name', sa.String(length=100), nullable=True),
    sa.Column('tool_input', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('tool_result_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('model_used', sa.String(length=50), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=True),
    sa.Column('output_tokens', sa.Integer(), nullable=True),
    sa.Column('cache_read_tokens', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['chat_conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_chat_messages_conv_seq', 'chat_messages', ['conversation_id', 'sequence'], unique=False)
    op.create_table('feature_requests',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('user_story', sa.Text(), nullable=True),
    sa.Column('acceptance_criteria', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('priority', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['chat_conversations.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('feature_requests')
    op.drop_index('ix_chat_messages_conv_seq', table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_table('chat_conversations')
