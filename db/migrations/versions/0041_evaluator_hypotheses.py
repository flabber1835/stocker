"""evaluator_hypotheses — replace the empty 0032 stub with the ledger schema

Revision ID: 0041
Revises: 0040

Migration 0032 CREATED evaluator_hypotheses EMPTY with an earlier, more elaborate
schema (statement / config_diff / economic_rationale / weeks_supported / ... ) for
a hypothesis ledger that was never wired to any code — no service ever read or
wrote it. Phase 2's hypothesis_ledger tool is the ledger actually built, and it
uses a simpler schema (thesis → planned test → status/outcome). Because the 0032
table is provably EMPTY (created empty, never written — the only code referencing
the name is this Phase-2 code, which hasn't run) and UNUSED, we drop and recreate
it here rather than leave a mismatched table whose missing `updated_at` broke the
index build. DROP + CREATE runs exactly once under alembic's applied-revision
tracking, before the ledger has any rows, so no data is at risk.

Backwards compatible (fresh DBs: 0032 makes the stub, 0041 replaces it) and safe.
"""
from alembic import op

revision = "0041"
down_revision = "0040"


def upgrade() -> None:
    # Safe: empty + unused 0032 stub (see module docstring). Runs once.
    op.execute("DROP TABLE IF EXISTS evaluator_hypotheses")
    op.execute("""
        CREATE TABLE evaluator_hypotheses (
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
