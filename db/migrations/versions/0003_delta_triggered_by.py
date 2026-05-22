"""Add triggered_by to delta_runs

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-22 00:00:00.000000
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE delta_runs
        ADD COLUMN IF NOT EXISTS triggered_by TEXT NOT NULL DEFAULT 'pipeline'
    """)


def downgrade() -> None:
    pass
