"""ingest_runs.session_date: the trading session a fetch-data run advanced to

Revision ID: 0016
Revises: 0015

The scheduler's daily chain is keyed on the trading SESSION being processed
(the latest closed NYSE session), not wall-clock "today" — so a chain that
starts in the evening and runs past midnight keeps the same key and is never
mistaken for a new cycle (the cross-midnight abandon bug). For that to work the
front step (fetch-data) must report the session it ingested data for, rather
than only its wall-clock started_at.

`session_date` records MAX(SPY date) at completion — i.e. the trading session
whose closing bar this run advanced the price data to. The scheduler compares
it against the target session to decide whether fetch-data is done for the
cycle. Nullable: a fetch that fails before SPY is written (or a non-fetch-data
job) has no session.
"""
from alembic import op

revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS session_date DATE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ingest_runs DROP COLUMN IF EXISTS session_date")
