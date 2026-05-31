"""add cluster_id to portfolio_holdings

Revision ID: 0013
Revises: 0012

Persists the correlation-cluster a holding belongs to (the data-driven grouping
that replaced provider sector labels for the concentration cap). NULL when the
ticker is in a singleton cluster (no co-moving peers) — i.e. "no applicable
cluster". Surfaced read-only in the dashboard's Target Portfolio panel.
"""
from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE portfolio_holdings ADD COLUMN IF NOT EXISTS cluster_id VARCHAR(20)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE portfolio_holdings DROP COLUMN IF EXISTS cluster_id")
