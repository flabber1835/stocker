"""risk-service hot-path indexes (audit P0)

Revision ID: 0027
Revises: 0026

The risk-service /check runs several DB-dependent controls per call. Two hot paths
were unindexed, making each query a filtered/seq scan and lengthening connection
hold time → under concurrent /check the small pool starved and controls fail-closed
("Safety control unavailable (database error)").

1. Every freshness query does `MAX(completed_at) WHERE status='success'` against
   alpaca_sync_runs (the projected-positions SQL alone does it 4x). The only index
   was on started_at, so this scanned. Add (status, completed_at DESC) so it's an
   index-only probe.
2. The projected-positions + turnover queries filter alpaca_orders by status (and
   action). Only ticker/created_at were indexed. Add (status) — a partial index on
   the open-ish statuses keeps it small and serves the IN-list scans.

Additive, no data change. Indexes are created IF NOT EXISTS so re-runs are safe.
(Not CONCURRENTLY: alembic runs in a transaction, and on this deployment's table
sizes a brief lock is acceptable.)
"""
from alembic import op

revision = "0027"
down_revision = "0026"


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alpaca_sync_runs_status_completed "
        "ON alpaca_sync_runs(status, completed_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alpaca_orders_status "
        "ON alpaca_orders(status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alpaca_orders_action_status "
        "ON alpaca_orders(action, status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alpaca_orders_action_status")
    op.execute("DROP INDEX IF EXISTS idx_alpaca_orders_status")
    op.execute("DROP INDEX IF EXISTS idx_alpaca_sync_runs_status_completed")
