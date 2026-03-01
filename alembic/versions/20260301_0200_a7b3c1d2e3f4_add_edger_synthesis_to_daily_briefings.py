"""add edger_synthesis and lesson_taught to daily_briefings

Revision ID: a7b3c1d2e3f4
Revises: 298a13e4581a
Create Date: 2026-03-01 02:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7b3c1d2e3f4'
down_revision: Union[str, None] = '298a13e4581a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('daily_briefings', sa.Column('edger_synthesis', sa.Text(), nullable=True))
    op.add_column('daily_briefings', sa.Column('lesson_taught', sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column('daily_briefings', 'lesson_taught')
    op.drop_column('daily_briefings', 'edger_synthesis')
