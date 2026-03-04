"""add content_hash to simulation_logs and merkle_anchors table

Revision ID: b4c5d6e7f8a9
Revises: a7b3c1d2e3f4
Create Date: 2026-03-04 03:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a7b3c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add content_hash column to simulation_logs
    op.add_column(
        "simulation_logs",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )

    # Create merkle_anchors table
    op.create_table(
        "merkle_anchors",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("anchor_date", sa.String(10), nullable=False, unique=True),
        sa.Column("merkle_root", sa.String(64), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column(
            "entry_hashes",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("chain_tx_id", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_merkle_anchor_date", "merkle_anchors", ["anchor_date"])


def downgrade() -> None:
    op.drop_index("ix_merkle_anchor_date", table_name="merkle_anchors")
    op.drop_table("merkle_anchors")
    op.drop_column("simulation_logs", "content_hash")
