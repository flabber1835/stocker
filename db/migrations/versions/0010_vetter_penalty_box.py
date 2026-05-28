"""Add vetter_penalty_box table

Stores per-ticker penalty box state.  When the LLM vetter flags a ticker
with exclude=True, the ticker enters a 30-calendar-day penalty box.  If the
same ticker is flagged again within the window the clock resets.  Portfolio-
builder reads this table on every run and excludes any ticker whose
penalty_box_until >= today, regardless of whether the ticker was flagged in
the most recent vetter run.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-28 09:00:00.000000
"""
from alembic import op


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_vpb_ticker ON vetter_penalty_box(ticker)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_vpb_until  ON vetter_penalty_box(penalty_box_until)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vetter_penalty_box")
