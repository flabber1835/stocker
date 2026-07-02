"""evaluator_reports — weekly LLM evaluator (Phase 1: read-only report)

Revision ID: 0037
Revises: 0036

One row per evaluator run. The deterministic Python packet (what the LLM saw) is
stored verbatim in `packet` JSONB for auditability; the LLM's output is split into
`report_markdown` (narrative) and `recommendations` JSONB (structured, schema-
validated suggestion objects a future Phase 3 can consume). Model/prompt/token
metadata follows the strategy-registry auditability pattern (which prompt produced
this report? what did it cost?).

Backwards compatible and idempotent.
"""
from alembic import op

revision = "0037"
down_revision = "0036"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS evaluator_reports (
            run_id           UUID         PRIMARY KEY,
            status           VARCHAR(20)  NOT NULL DEFAULT 'running'
                             CHECK (status IN ('running','success','failed')),
            as_of_date       DATE         NOT NULL,
            iso_year         INTEGER      NOT NULL,
            iso_week         INTEGER      NOT NULL,
            manual           BOOLEAN      NOT NULL DEFAULT FALSE,
            strategy_id      VARCHAR(100),
            config_hash      VARCHAR(64),
            packet           JSONB,
            report_markdown  TEXT,
            recommendations  JSONB,
            data_gaps        JSONB,
            provider         VARCHAR(30),
            model            VARCHAR(100),
            prompt_hash      VARCHAR(64),
            input_tokens     INTEGER,
            output_tokens    INTEGER,
            latency_ms       INTEGER,
            error_message    TEXT,
            started_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            completed_at     TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_evaluator_reports_started "
               "ON evaluator_reports (started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_evaluator_reports_week "
               "ON evaluator_reports (iso_year DESC, iso_week DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS evaluator_reports")
