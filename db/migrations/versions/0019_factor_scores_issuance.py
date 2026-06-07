"""factor_scores.issuance: persist the net-issuance factor

Revision ID: 0019
Revises: 0018

Migration 0018 added the raw inputs (fundamentals.shares_outstanding[_prior]) and
the factor math was added to factors.py (compute_issuance → result["issuance"]),
but the factor-score PERSISTENCE layer in services/pipeline/app/main.py was never
extended: the factor_scores table, its INSERT, and the ranker's SELECT all carried
only the six classic factors. So issuance was computed in memory, dropped on write,
read back as NULL, and its config weight (0.06) was renormalized away for every
ticker — the factor was inert (0/N rankings carried a value) despite clean input
data. This adds the missing column; the write/read in main.py are updated to match.

issuance is stored as the cross-sectional percentile rank [0,1] (same as the other
factors — compute_all_factors ranks it), nullable (optional factor; NULL never
drops a ticker since issuance is not a required factor).
"""
from alembic import op

revision = "0019"
down_revision = "0018"


def upgrade() -> None:
    op.execute("ALTER TABLE factor_scores ADD COLUMN IF NOT EXISTS issuance NUMERIC(10,6)")


def downgrade() -> None:
    op.execute("ALTER TABLE factor_scores DROP COLUMN IF EXISTS issuance")
