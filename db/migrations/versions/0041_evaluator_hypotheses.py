"""evaluator_hypotheses — the evaluator's cross-week hypothesis ledger

Revision ID: 0041
Revises: 0040

prior_reviews shows the evaluator its past CONCLUSIONS, but not its OPEN
EXPERIMENTS — so a thesis raised one week ("momentum weight looks light; test
next week once more IC data lands") had nowhere durable to live. This table is
that memory: thesis → planned test → status/outcome, written by the evaluator's
ONE write-capable tool (hypothesis_ledger, scoped to this table only) and read
back deterministically as a packet section every review.

Backwards compatible and idempotent.
"""
from alembic import op

revision = "0041"
down_revision = "0040"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS evaluator_hypotheses (
            id               SERIAL       PRIMARY KEY,
            status           VARCHAR(12)  NOT NULL DEFAULT 'open',
            hypothesis       TEXT         NOT NULL,
            planned_test     TEXT,
            outcome          TEXT,
            created_iso_year INT,
            created_iso_week INT,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_eval_hypotheses_status "
               "ON evaluator_hypotheses (status, updated_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS evaluator_hypotheses")
