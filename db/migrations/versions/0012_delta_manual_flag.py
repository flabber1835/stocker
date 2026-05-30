"""Add manual flag to delta_runs

Marks a delta produced by a human-initiated run (scheduler /jobs/run-now) vs the
after-close cron chain. Kept separate from triggered_by because /runs/delta-latest
filters triggered_by='scheduler'; the dashboard reads `manual` to decide whether to
auto-approve (manual runs require a human, scheduled runs auto-approve after timeout).

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-30 00:00:00.000000
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE delta_runs
        ADD COLUMN IF NOT EXISTS manual BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE delta_runs DROP COLUMN IF EXISTS manual")
