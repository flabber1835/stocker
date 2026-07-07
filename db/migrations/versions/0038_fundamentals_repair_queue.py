"""fundamentals_repair_queue — field-regression repair (the PBR incident, layer 4)

Revision ID: 0038
Revises: 0037

A vendor refresh that nulls a previously-populated fundamentals field (AV served
Petrobras with totalAssets=None for one fetch; the correct value was back within
hours) used to persist for a full weekly refresh cadence because nothing revisits
a "successfully" fetched ticker. This table is the persisted repair set: the
ingestor enqueues tickers whose new row REGRESSED a field vs their previous row,
re-fetches them at the start of the next fetch-data run (bypassing the weekly
skip window), and marks them resolved once the regressed fields come back
non-null. attempts caps the re-fetches so a legitimately-lost coverage (delisting)
is not hammered forever.

Backwards compatible and idempotent.
"""
from alembic import op

revision = "0038"
down_revision = "0037"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals_repair_queue (
            ticker            VARCHAR(20) PRIMARY KEY,
            regressed_fields  JSONB       NOT NULL,
            attempts          INTEGER     NOT NULL DEFAULT 0,
            first_detected    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_attempt      TIMESTAMPTZ,
            resolved_at       TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_fund_repair_open "
               "ON fundamentals_repair_queue (attempts) WHERE resolved_at IS NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fundamentals_repair_queue")
