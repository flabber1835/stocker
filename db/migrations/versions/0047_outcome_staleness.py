"""decision_outcomes: per-horizon forward-price staleness (audit-3 fix #2)

Revision ID: 0047
Revises: 0046

Forward prices hold at the last real print (delisted/halted names), which is
correct for acquisitions (last ≈ deal price) but silently optimistic for
bankruptcy delistings and hides how stale a label is. Rather than pretending
we have delisting returns (AV doesn't provide them), each labeled horizon now
records HOW STALE the price it used was: stale_<h>d = trading sessions between
the ticker's last real print and the horizon session (0 = traded at/after the
horizon session — fresh). Consumers filter/flag; the evaluator packet's
headline stats exclude rows staler than a small threshold and report the
excluded count instead of silently averaging them in.
"""
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE decision_outcomes
        ADD COLUMN IF NOT EXISTS stale_1d  SMALLINT,
        ADD COLUMN IF NOT EXISTS stale_5d  SMALLINT,
        ADD COLUMN IF NOT EXISTS stale_20d SMALLINT,
        ADD COLUMN IF NOT EXISTS stale_60d SMALLINT
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE decision_outcomes
        DROP COLUMN IF EXISTS stale_1d,
        DROP COLUMN IF EXISTS stale_5d,
        DROP COLUMN IF EXISTS stale_20d,
        DROP COLUMN IF EXISTS stale_60d
    """)
