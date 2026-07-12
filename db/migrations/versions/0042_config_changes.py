"""config_changes — audit of one-click human-approved strategy-config applies

Revision ID: 0042
Revises: 0041

Evaluator Phase 3 (docs/architecture.md "one-click apply"): every apply of a
recommendation to the active strategy YAML records one row here — what field,
what old/new value, the config_hash before/after, and which report's
recommendation drove it. Answers the registry question "Which config change
came from which review?" auditably.
"""
from alembic import op

revision = "0042"
down_revision = "0041"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS config_changes (
            id                     UUID         PRIMARY KEY,
            applied_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
            config_path            TEXT         NOT NULL,
            config_field           TEXT         NOT NULL,
            old_value              JSONB,
            new_value              JSONB,
            config_hash_before     VARCHAR(16),
            config_hash_after      VARCHAR(16),
            source_report_run_id   UUID,
            recommendation_index   INTEGER,
            applied_by             VARCHAR(40)  NOT NULL DEFAULT 'dashboard',
            validator_status       TEXT
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_config_changes_applied_at
        ON config_changes (applied_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS config_changes")
