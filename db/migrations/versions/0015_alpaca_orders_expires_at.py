"""alpaca_orders.expires_at: deterministic expiry for queued (deferred) orders

Revision ID: 0015
Revises: 0014

Fill-gated market-open draining (Option B, see docs/architecture.md). Approvals
enqueue an order as status='deferred' (queued for the next open) instead of
submitting. The drain submits sells-first, fill-gated, one buy at a time during
market hours. A queued BUY that cannot be funded by buying power before its
session closes must not linger to the next day (the next daily chain rebuilds a
fresh target) — it is marked 'expired'. `expires_at` is the session-close stamp
set at enqueue time so expiry is deterministic and survives restarts (state lives
in the row, not the worker).

Nullable: pre-existing rows and immediate-mode submissions have no expiry.
The 'expired' status value needs no schema change (status is VARCHAR, unconstrained).
"""
from alembic import op

revision = "0015"
down_revision = "0014"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE alpaca_orders ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"
    )
    # The drain scans for due/expiring deferred orders every pass; index the hot path.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alpaca_orders_deferred "
        "ON alpaca_orders(status, deferred_until) WHERE status = 'deferred'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alpaca_orders_deferred")
    op.execute("ALTER TABLE alpaca_orders DROP COLUMN IF EXISTS expires_at")
