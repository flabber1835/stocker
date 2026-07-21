"""shadow_runs — shadow champion/challenger theoretical daily targets

Revision ID: 0046
Revises: 0045

Closed-loop evaluation upgrade (item 4): when CHALLENGER_CONFIG_PATH is set,
the pipeline builds a THEORETICAL daily target under the challenger config
right after each successful delta step (fire-and-forget; reuses the day's
persisted factor scores + the shared canonical rank/select — no orders, no
vetter, no risk checks). The evaluator packet compares champion vs challenger
theoretical forward returns over the accumulated history; promotion stays a
human Apply/config swap. See docs/architecture.md "closed-loop evaluation
upgrades".
"""
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS shadow_runs (
    run_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_date       DATE         NOT NULL,
    strategy_id    VARCHAR(100) NOT NULL,
    config_hash    VARCHAR(16)  NOT NULL,
    config_path    TEXT,
    source_ranking_run_id UUID,
    regime         VARCHAR(50),
    status         VARCHAR(20)  NOT NULL DEFAULT 'success'
                       CHECK (status IN ('success','failed')),
    target         JSONB,           -- {ticker: weight}, weights sum <= 1
    n_positions    INTEGER,
    error_message  TEXT,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_date, config_hash)
)
""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_shadow_runs_date ON shadow_runs(run_date DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shadow_runs")
