"""Add ticker_fetch_state to track stuck/no-new-data tickers

When fetch-data calls AV TIME_SERIES_DAILY_ADJUSTED for a ticker whose
`MAX(date)` in daily_prices is behind `SPY.MAX(date)`, AV often has no newer
row to return (delisted-in-progress, ADR session mismatch, very thin volume,
recently IPO'd, etc.). Without tracking, every subsequent fetch-data run
re-calls the API for the same ticker and gets the same empty response,
burning ~0.8s of the 75 rpm budget per stuck ticker. With ~300 stuck names a
warm fetch-data takes ~5 min instead of ~5 s.

This migration adds a per-ticker state row so av-ingestor can:
  - Quarantine after `consecutive_empty_days` >= threshold (skip until a date)
  - Reset the streak when AV finally returns new data
  - Let fetch-universe drop chronic stuck names from the universe entirely

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-27 00:00:00.000000
"""
from alembic import op


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ticker_fetch_state (
            ticker                  TEXT PRIMARY KEY,
            last_consulted_date     DATE NOT NULL,
            consecutive_empty_days  INT  NOT NULL DEFAULT 0,
            quarantined_until       DATE,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ticker_fetch_state_quarantined
        ON ticker_fetch_state(quarantined_until)
        WHERE quarantined_until IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ticker_fetch_state_quarantined")
    op.execute("DROP TABLE IF EXISTS ticker_fetch_state")
