"""portfolio_runs.risk_estimate_degraded — hold-safe / buy-closed risk failure mode

Revision ID: 0044
Revises: 0043

Audit finding #8: vol_target_exposure fails OPEN on an unusable book-vol
estimate (never dump the book on a covariance glitch), which silently turned a
broken risk estimate into maximum exposure. The builder now flags such builds;
the delta engine defers risk-INCREASING trades (entries, buy_adds) while the
flag is set and lets de-risking trades (exits, sell_trims) proceed — the
hold-safe / buy-closed failure mode. Distinct from `degraded` (thin/failed
build → treat target as no-information), which suppresses everything.
"""
from alembic import op

revision = "0044"
down_revision = "0043"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE portfolio_runs "
        "ADD COLUMN IF NOT EXISTS risk_estimate_degraded BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE portfolio_runs DROP COLUMN IF EXISTS risk_estimate_degraded")
