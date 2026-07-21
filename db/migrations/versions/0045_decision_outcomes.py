"""decision_outcomes — durable decision ledger with multi-horizon outcome labels

Revision ID: 0045
Revises: 0044

Closed-loop evaluation upgrade (optimizer-essay adoption, item 1): one row per
harvested decision (delta intents except 'hold', vetter exclusions), labeled
retroactively with forward returns at 1/5/20/60 trading sessions, SPY over the
same spans, and 20-session max-favorable/adverse excursion. Harvest + labeling
are idempotent (UNIQUE (source, source_id); relabeling only fills nulls whose
horizons have newly elapsed). See docs/architecture.md "closed-loop evaluation
upgrades".
"""
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS decision_outcomes (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    source        VARCHAR(20)  NOT NULL
                      CHECK (source IN ('delta_intent','vetter_exclusion')),
    source_id     UUID         NOT NULL,
    decision_date DATE         NOT NULL,
    ticker        VARCHAR(20)  NOT NULL,
    action        VARCHAR(20)  NOT NULL
                      CHECK (action IN ('entry','exit','buy_add','sell_trim',
                                        'at_risk','watch','vetter_exclude')),
    base_price    NUMERIC(16,6),
    fwd_1d        NUMERIC(12,6),
    fwd_5d        NUMERIC(12,6),
    fwd_20d       NUMERIC(12,6),
    fwd_60d       NUMERIC(12,6),
    spy_fwd_1d    NUMERIC(12,6),
    spy_fwd_5d    NUMERIC(12,6),
    spy_fwd_20d   NUMERIC(12,6),
    spy_fwd_60d   NUMERIC(12,6),
    mfe_20d       NUMERIC(12,6),
    mae_20d       NUMERIC(12,6),
    complete      BOOLEAN      NOT NULL DEFAULT FALSE,
    labeled_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (source, source_id)
)
""")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_incomplete "
        "ON decision_outcomes(decision_date) WHERE NOT complete"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_outcomes_action "
        "ON decision_outcomes(action, decision_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS decision_outcomes")
