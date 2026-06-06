"""fundamentals.shares_outstanding + shares_outstanding_prior: net-issuance factor

Revision ID: 0018
Revises: 0017

The net share issuance anomaly (net issuers underperform, net repurchasers
outperform — one of the more robustly-replicated anomalies) drives an optional
`issuance` factor. Net issuance is computed YoY from balance-sheet annual common
shares outstanding:

    net_issuance = shares_outstanding / shares_outstanding_prior - 1
    factor       = -net_issuance   (buybacks rank high, dilution ranks low)

- shares_outstanding       : AV BALANCE_SHEET annualReports[0] commonStockSharesOutstanding
- shares_outstanding_prior : annualReports[1] (≈ one fiscal year earlier)

Both nullable NUMERIC — share counts can reach the tens of billions; the factor
is optional (default weight 0) so NULLs are expected until backfilled and never
drop a ticker from ranking.
"""
from alembic import op

revision = "0018"
down_revision = "0017"


def upgrade() -> None:
    op.execute("ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS shares_outstanding NUMERIC(22,2)")
    op.execute("ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS shares_outstanding_prior NUMERIC(22,2)")


def downgrade() -> None:
    op.execute("ALTER TABLE fundamentals DROP COLUMN IF EXISTS shares_outstanding")
    op.execute("ALTER TABLE fundamentals DROP COLUMN IF EXISTS shares_outstanding_prior")
