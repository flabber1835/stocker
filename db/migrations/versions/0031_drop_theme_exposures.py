"""drop theme_exposures (AI theme retired)

Revision ID: 0031
Revises: 0030

The thematic overlay / theme-classifier were retired (the engine is theme-agnostic),
so `theme_exposures` (added in 0020) is no longer written or read by any service.
Drop it. Reversible: downgrade recreates the empty table + index (mirrors 0020) — the
data is gone, but the schema is restorable.
"""
from alembic import op

revision = "0031"
down_revision = "0030"


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS theme_exposures")


def downgrade() -> None:
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
