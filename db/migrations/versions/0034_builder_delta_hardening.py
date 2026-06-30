"""portfolio_runs/delta_runs hardening — degraded flag + supersede marker

Revision ID: 0034
Revises: 0033

Supports the builder/delta architecture-delta hardening (see docs/architecture.md
"Design Decision: builder/delta chain hardening"):

  - portfolio_runs.degraded (BOOL, default FALSE): set when a build SUCCEEDED but on
    DEGRADED inputs — selected_count below the strategy's min_selected floor (a
    transiently thin ranking). The delta engine treats a degraded target like an
    EMPTY one (hold the book, suppress the below-floor split) so a one-off bad-data
    day cannot mass-orphan-exit good names. (G2)

  - portfolio_runs.superseded_at / delta_runs.superseded_at (TIMESTAMPTZ): stamped
    on the PRIOR successful run for the same lineage/session when a newer run for it
    succeeds, so "latest" is unambiguous and a manual re-run that supersedes a cron
    run is explicit rather than implied by completed_at ordering. (G5)

Backwards compatible (all-NULL/FALSE on existing rows) and idempotent.
"""
from alembic import op

revision = "0034"
down_revision = "0033"


def upgrade() -> None:
    op.execute("ALTER TABLE portfolio_runs ADD COLUMN IF NOT EXISTS degraded BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE portfolio_runs ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ")
    op.execute("ALTER TABLE delta_runs    ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE delta_runs    DROP COLUMN IF EXISTS superseded_at")
    op.execute("ALTER TABLE portfolio_runs DROP COLUMN IF EXISTS superseded_at")
    op.execute("ALTER TABLE portfolio_runs DROP COLUMN IF EXISTS degraded")
