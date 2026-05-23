"""Add at_risk/buy_add/sell_trim actions, actual_weight, weight_drift, and counters

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-23 00:00:00.000000
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Widen the action CHECK constraint on delta_intents to allow new action values.
    #    The constraint is dropped by name then re-added; the IF EXISTS guard makes this
    #    safe to re-run.
    op.execute("""
        ALTER TABLE delta_intents
        DROP CONSTRAINT IF EXISTS delta_intents_action_check
    """)
    op.execute("""
        ALTER TABLE delta_intents
        ADD CONSTRAINT delta_intents_action_check
        CHECK (action IN ('entry','exit','hold','watch','at_risk','buy_add','sell_trim'))
    """)

    # 2. New columns on delta_intents for drift tracking
    op.execute("""
        ALTER TABLE delta_intents
        ADD COLUMN IF NOT EXISTS actual_weight  NUMERIC(10,6),
        ADD COLUMN IF NOT EXISTS weight_drift   NUMERIC(10,6)
    """)

    # 3. New counter columns on delta_runs
    op.execute("""
        ALTER TABLE delta_runs
        ADD COLUMN IF NOT EXISTS at_risk_count   INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS buy_add_count   INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS sell_trim_count INTEGER NOT NULL DEFAULT 0
    """)


def downgrade() -> None:
    pass
