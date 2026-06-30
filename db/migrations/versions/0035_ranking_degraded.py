"""ranking_runs.degraded — degraded-ranking gate (pipeline-core P2)

Revision ID: 0035
Revises: 0034

A thin ranking (e.g. a fundamentals-ingest failure leaves most names price-only, or
too few tickers clear min_non_null_factors) used to be recorded plain
status='success' and flow downstream with no quality signal — the upstream ROOT of
the degraded-build mass-rotation risk that 0034 guarded only at the builder.

ranking_runs.degraded (BOOL, default FALSE) is set when ranked_count falls below the
strategy's min_ranked floor. The portfolio-builder propagates it into
portfolio_runs.degraded, and the delta engine already holds the book on a degraded
target — so a bad-data day can't mass-orphan-exit, gated at the source.

Backwards compatible (FALSE on existing rows) and idempotent.
"""
from alembic import op

revision = "0035"
down_revision = "0034"


def upgrade() -> None:
    op.execute("ALTER TABLE ranking_runs ADD COLUMN IF NOT EXISTS degraded BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE ranking_runs DROP COLUMN IF EXISTS degraded")
