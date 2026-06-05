"""fundamentals.gross_profit + total_assets: gross-profitability quality factor

Revision ID: 0017
Revises: 0016

The quality factor can switch its profitability leg from ROE to
gross-profits-to-assets (gross_profit / total_assets, Novy-Marx 2013) — the
robust quality signal vs ROE's weakest-form proxy. This is gated behind
FactorEngineConfig.quality_use_gross_profitability (default off), so these
columns can be NULL until backfilled without affecting the legacy ROE path.

- gross_profit  : AV OVERVIEW `GrossProfitTTM` (already fetched, zero new calls).
- total_assets  : AV BALANCE_SHEET most-recent `totalAssets` (best-effort fetch,
                  gated by FETCH_BALANCE_SHEET; non-fatal so NULL is expected for
                  tickers whose balance-sheet call failed).

Both nullable NUMERIC — assets/profits are dollar amounts that can reach the
trillions, so width is generous.
"""
from alembic import op

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    op.execute("ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS gross_profit NUMERIC(22,2)")
    op.execute("ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS total_assets NUMERIC(22,2)")


def downgrade() -> None:
    op.execute("ALTER TABLE fundamentals DROP COLUMN IF EXISTS gross_profit")
    op.execute("ALTER TABLE fundamentals DROP COLUMN IF EXISTS total_assets")
