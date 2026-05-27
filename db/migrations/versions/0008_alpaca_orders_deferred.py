"""Add 'deferred' status + deferred_until column to alpaca_orders

Alpaca rejects market-on-open (time_in_force='opg') orders submitted outside
the [19:00 ET, 09:28 ET] window with "opg orders must be submitted after
7:00pm and before 9:28am". The default daily pipeline lands auto-approval
into the 16:00–19:00 ET dead zone, so trades fail without retry.

This migration adds:
- alpaca_orders.deferred_until — when the trade-executor's deferral worker
  should next attempt submission. Set when the row is created during the
  OPG dead zone, or when Alpaca returns the OPG-window error after a
  best-effort submit.
- Updated idx_alpaca_orders_intent_open: 'deferred' joins ('pending',
  'submitted') as a state that blocks a duplicate submission for the same
  intent. A re-approval click while a deferred order exists returns
  duplicate instead of stacking a second row.
- idx_alpaca_orders_deferred for cheap polling by the background worker.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-27 23:00:00.000000
"""
from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE alpaca_orders ADD COLUMN IF NOT EXISTS deferred_until TIMESTAMPTZ")
    op.execute("DROP INDEX IF EXISTS idx_alpaca_orders_intent_open")
    op.execute("""
CREATE UNIQUE INDEX idx_alpaca_orders_intent_open
  ON alpaca_orders(intent_id)
  WHERE intent_id IS NOT NULL AND status IN ('pending','submitted','deferred')
""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alpaca_orders_deferred "
        "ON alpaca_orders(deferred_until) WHERE status = 'deferred'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alpaca_orders_deferred")
    op.execute("DROP INDEX IF EXISTS idx_alpaca_orders_intent_open")
    op.execute("""
CREATE UNIQUE INDEX idx_alpaca_orders_intent_open
  ON alpaca_orders(intent_id)
  WHERE intent_id IS NOT NULL AND status IN ('pending','submitted')
""")
    op.execute("ALTER TABLE alpaca_orders DROP COLUMN IF EXISTS deferred_until")
