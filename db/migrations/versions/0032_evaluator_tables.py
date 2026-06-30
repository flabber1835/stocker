"""evaluator_weekly + evaluator_hypotheses — Phase 1 evidence backbone

Revision ID: 0032
Revises: 0031

The (deterministic, read-only) weekly evidence the LLM evaluator will consume:
  - evaluator_weekly: one row per ISO week holding the computed packet (per-factor
    realized IC over all factors incl. dormant/display indicators, factor correlation,
    book-vs-benchmark, hit rate, regret) as JSONB. Built from accumulated rankings +
    forward returns (IC needs forward data, so it's a weekly DERIVED view, not the
    per-run health record).
  - evaluator_hypotheses: the running ledger the Tier-1 LLM narrative updates
    (candidate -> ready -> confirmed/rejected) with evidence counters. Created empty.

Backwards compatible and idempotent.
"""
from alembic import op

revision = "0032"
down_revision = "0031"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS evaluator_weekly (
            id             SERIAL PRIMARY KEY,
            iso_year       INTEGER     NOT NULL,
            iso_week       INTEGER     NOT NULL,
            as_of_date     DATE        NOT NULL,
            packet         JSONB       NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (iso_year, iso_week)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_evaluator_weekly_asof "
               "ON evaluator_weekly (as_of_date DESC)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS evaluator_hypotheses (
            id                 SERIAL PRIMARY KEY,
            statement          TEXT        NOT NULL,
            status             VARCHAR(20) NOT NULL DEFAULT 'candidate',
            config_diff        JSONB,
            economic_rationale TEXT,
            weeks_supported    INTEGER     NOT NULL DEFAULT 0,
            weeks_total        INTEGER     NOT NULL DEFAULT 0,
            confidence         VARCHAR(10),
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_updated       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS evaluator_hypotheses")
    op.execute("DROP TABLE IF EXISTS evaluator_weekly")
