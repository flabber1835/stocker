"""pipeline_runs table

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-01 00:00:01.000000

Adds the pipeline_runs table that tracks consolidated factor+rank+delta chain runs
produced by the unified pipeline service.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID         REFERENCES execution_traces(trace_id),
    strategy_id     VARCHAR(100),
    config_hash     VARCHAR(16),
    status          VARCHAR(20)  NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','success','failed')),
    triggered_by    VARCHAR(50)  NOT NULL DEFAULT 'manual',
    run_date        DATE,
    chain_date      DATE,
    factor_run_id   UUID         REFERENCES factor_runs(run_id),
    ranking_run_id  UUID         REFERENCES ranking_runs(run_id),
    delta_run_id    UUID         REFERENCES delta_runs(run_id),
    factor_status   VARCHAR(20),
    ranking_status  VARCHAR(20),
    delta_status    VARCHAR(20),
    error_message   TEXT,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_runs_date    ON pipeline_runs(run_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status  ON pipeline_runs(status, started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started ON pipeline_runs(started_at DESC)")


def downgrade() -> None:
    pass
