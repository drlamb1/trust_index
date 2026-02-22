"""Add User model and ChatConversation.user_id

Revision ID: be8c6f1d19d2
Revises: 27095eeaeafc
Create Date: 2026-02-21 21:48:51.409190

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be8c6f1d19d2'
down_revision: Union[str, None] = '27095eeaeafc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('hashed_password', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('daily_token_budget', sa.Integer(), nullable=False),
    sa.Column('tokens_used_today', sa.Integer(), nullable=False),
    sa.Column('last_token_reset', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # Add user_id FK to chat_conversations
    op.add_column('chat_conversations', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_chat_conversations_user_id', 'chat_conversations', 'users', ['user_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_chat_conversations_user_id', 'chat_conversations', type_='foreignkey')
    op.drop_column('chat_conversations', 'user_id')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
