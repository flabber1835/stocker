"""spinoff-aware prices: raw_adjusted_close + corporate_actions table

Revision ID: 0025
Revises: 0024

Alpha Vantage's adjusted_close handles splits/dividends but NOT spinoffs, so a
spinoff's ex-date price drop stays in the series as a false ~cliff. A trailing
window straddling it then misreads a value distribution as a crash — the vetter's
falling-knife force-excluded FDX (-16.8% "excess drawdown") on the 2026-06-01
FedEx Freight (FDXF) spinoff, which was value handed to shareholders, not a loss.

This makes prices spinoff-aware WITHOUT touching any consumer query:

  - daily_prices.raw_adjusted_close — the IMMUTABLE AV value (split/div adjusted).
    av-ingestor writes it on every upsert; it is never modified by spinoff logic.
  - daily_prices.adjusted_close stays the column everything reads, but av-ingestor
    now derives it as raw_adjusted_close × Π(spinoff gap factors after that date),
    so it is continuous across spinoffs. Idempotent: always recomputed from raw +
    the curated ex-dates, so re-ingestion can't drift it.
  - corporate_actions — curated ex-dates (ticker, ex_date, action_type). The gap
    factor is computed from the price data at apply time (no external valuation),
    so this table only needs the WHEN.

Additive + idempotent (IF NOT EXISTS / ON CONFLICT), so it is a no-op against an
init.sql-built schema and safe to re-run.
"""
from alembic import op

revision = "0025"
down_revision = "0024"


def upgrade() -> None:
    # Immutable AV source column; backfill existing rows from the current AV value.
    op.execute(
        "ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS raw_adjusted_close NUMERIC(14,4)"
    )
    op.execute(
        "UPDATE daily_prices SET raw_adjusted_close = adjusted_close "
        "WHERE raw_adjusted_close IS NULL"
    )

    # Curated corporate-action ex-dates (currently spinoffs). adj_factor is OPTIONAL:
    # NULL → av-ingestor computes the gap factor from price data; a value pins it.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS corporate_actions (
            id           SERIAL       PRIMARY KEY,
            ticker       VARCHAR(20)  NOT NULL,
            ex_date      DATE         NOT NULL,
            action_type  TEXT         NOT NULL DEFAULT 'spinoff',
            adj_factor   NUMERIC(10,6),
            note         TEXT,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (ticker, ex_date)
        )
        """
    )

    # Seed the known FedEx Freight spinoff (factor computed from data → adj_factor NULL).
    op.execute(
        """
        INSERT INTO corporate_actions (ticker, ex_date, action_type, note)
        VALUES ('FDX', '2026-06-01', 'spinoff',
                'FedEx Freight (FDXF) spinoff, 1 FDXF per 2 FDX; AV adjusted_close not spinoff-adjusted')
        ON CONFLICT (ticker, ex_date) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corporate_actions")
    op.execute("ALTER TABLE daily_prices DROP COLUMN IF EXISTS raw_adjusted_close")
