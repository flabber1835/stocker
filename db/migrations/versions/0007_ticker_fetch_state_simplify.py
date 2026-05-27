"""Simplify ticker_fetch_state to just (ticker, last_consulted_date)

The previous streak-based approach (consecutive_empty_days,
quarantined_until) waited 30 days of empty fetches before dropping a
ticker from the universe. That was conservative but slow.

The new approach drops tickers when `MAX(date) < spy_max` in daily_prices
(the same empirical signal that the per-ticker skip check uses), then
re-probes a small rotating slice each fetch-universe so a halted-then-
resumed ticker eventually rejoins. The streak counter and quarantine
expiry are no longer needed; only `last_consulted_date` remains, used
to pick the oldest probation candidates.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-27 00:00:00.000000
"""
from alembic import op


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ticker_fetch_state_quarantined")
    op.execute("ALTER TABLE ticker_fetch_state DROP COLUMN IF EXISTS consecutive_empty_days")
    op.execute("ALTER TABLE ticker_fetch_state DROP COLUMN IF EXISTS quarantined_until")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ticker_fetch_state_last_consulted "
        "ON ticker_fetch_state(last_consulted_date)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ticker_fetch_state_last_consulted")
    op.execute("ALTER TABLE ticker_fetch_state ADD COLUMN IF NOT EXISTS consecutive_empty_days INT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE ticker_fetch_state ADD COLUMN IF NOT EXISTS quarantined_until DATE")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ticker_fetch_state_quarantined "
        "ON ticker_fetch_state(quarantined_until) WHERE quarantined_until IS NOT NULL"
    )
