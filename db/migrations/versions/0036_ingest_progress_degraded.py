"""ingest_runs durable progress + degraded flag (av-ingestor G2/G4)

Revision ID: 0036
Revises: 0035

Fetch-data progress was in-memory only (_fetch_data_progress), so a redeploy mid-fetch
froze the dashboard bar with no percentage (the "stuck-READY" symptom). And a withheld
chain-advance (coverage/SPY gate) was signalled only by a NULL session_date — a run
that withheld the chain still read status='success'/'partial_success'.

  - ingest_runs.tickers_done / tickers_total (INT): DURABLE progress, checkpointed
    every CHECKPOINT_EVERY tickers, so /runs/latest reports progress even after the
    in-memory state is lost to a restart.
  - ingest_runs.degraded (BOOL, default FALSE): set true when the chain-advance gate
    withholds session_date (low coverage / SPY didn't advance / throttle circuit-broke),
    so the degraded state is first-class in status rather than inferred from a NULL date.

Backwards compatible (NULL/FALSE on existing rows) and idempotent.
"""
from alembic import op

revision = "0036"
down_revision = "0035"


def upgrade() -> None:
    op.execute("ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS tickers_done INTEGER")
    op.execute("ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS tickers_total INTEGER")
    op.execute("ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS degraded BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE ingest_runs DROP COLUMN IF EXISTS degraded")
    op.execute("ALTER TABLE ingest_runs DROP COLUMN IF EXISTS tickers_total")
    op.execute("ALTER TABLE ingest_runs DROP COLUMN IF EXISTS tickers_done")
