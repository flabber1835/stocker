"""Add unique constraint on universe_tickers(snapshot_id, ticker)

Without this, AV LISTING_STATUS can return the same ticker on multiple exchanges
(e.g. NYSE:B = Barnes Group and OTC:B = Barrick Gold Corp) and both rows get
inserted into the same snapshot. The API's names CTE then picks one arbitrarily,
causing the wrong company name to appear in the dashboard.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-25 00:00:00.000000
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove any existing duplicates within each snapshot, keeping the row with
    # the lowest id (first inserted = first seen in AV CSV = preferred exchange).
    # Uses a subquery rather than a self-join alias to avoid dialect quirks.
    op.execute("""
        DELETE FROM universe_tickers
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM universe_tickers
            GROUP BY snapshot_id, ticker
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_universe_tickers_snapshot_ticker
        ON universe_tickers(snapshot_id, ticker)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_universe_tickers_snapshot_ticker")
