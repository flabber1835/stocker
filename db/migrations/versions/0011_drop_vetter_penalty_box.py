"""Drop vetter_penalty_box table

The penalty-box feature (a 30-day exclusion box for vetter-flagged tickers) has
been removed entirely. This migration drops the table and its indexes. Downgrade
recreates the table (mirroring 0010) so the migration is reversible.
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_vpb_until")
    op.execute("DROP INDEX IF EXISTS idx_vpb_ticker")
    op.execute("DROP TABLE IF EXISTS vetter_penalty_box")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS vetter_penalty_box (
            id                SERIAL PRIMARY KEY,
            ticker            VARCHAR NOT NULL UNIQUE,
            first_flagged_date DATE NOT NULL,
            last_flagged_date  DATE NOT NULL,
            penalty_box_until  DATE NOT NULL,
            flagged_count      INTEGER NOT NULL DEFAULT 1,
            reason             TEXT,
            risk_type          VARCHAR,
            created_at         TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_vpb_ticker ON vetter_penalty_box(ticker)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_vpb_until  ON vetter_penalty_box(penalty_box_until)")
