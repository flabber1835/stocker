"""theme_exposures: standalone thematic-universe scores (AI-infra, etc.)

Revision ID: 0020
Revises: 0019

Backs the standalone theme-classifier service + the read-only Theme tab. Completely
decoupled from the trading pipeline: the theme-classifier WRITES this table, the
dashboard READS it, and nothing in ranking / portfolio-builder / delta / risk /
trade-executor references it. Adding this table changes no existing behavior.

One row per (theme, ticker, as_of_date) — point-in-time so the membership at a past
date can be reconstructed. `exposure` is the AI-specific correlation score in [0,1]
(market + orthogonalized-sector stripped); membership for display is exposure >=
threshold (applied at read time, so the cutoff is tunable without recompute).
"""
from alembic import op

revision = "0020"
down_revision = "0019"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS theme_exposures (
            id             SERIAL PRIMARY KEY,
            theme          VARCHAR(40)  NOT NULL,
            ticker         VARCHAR(20)  NOT NULL,
            exposure       NUMERIC(6,4) NOT NULL,
            in_seed        BOOLEAN      NOT NULL DEFAULT FALSE,
            avg_dollar_vol NUMERIC(20,2),
            as_of_date     DATE         NOT NULL,
            computed_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (theme, ticker, as_of_date)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_theme_exposures_theme_date "
               "ON theme_exposures(theme, as_of_date DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS theme_exposures")
