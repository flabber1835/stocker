"""earnings table + factor_scores.earnings_surprise column

Revision ID: 0028
Revises: 0027

Supports the earnings-surprise (PEAD) factor — "buy winners (beats) / sell
losers (misses)".

  - `earnings`: per-ticker quarterly results from Alpha Vantage's EARNINGS
    endpoint (reportedEPS / estimatedEPS / surprise). reported_date is the
    point-in-time the result became known — the factor only uses quarters with
    reported_date <= the score date (no look-ahead) and within the drift window.
  - `factor_scores.earnings_surprise`: the cross-sectional percentile of the SUE
    signal, NUMERIC(10,6) to match the other factor columns. Nullable; default
    weight 0 in FactorWeights, so it's inert until a strategy gives it weight.

Backwards compatible and idempotent.
"""
from alembic import op

revision = "0028"
down_revision = "0027"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS earnings (
            ticker               VARCHAR(20)  NOT NULL,
            fiscal_date_ending   DATE         NOT NULL,
            reported_date        DATE,
            reported_eps         NUMERIC(18,6),
            estimated_eps        NUMERIC(18,6),
            surprise             NUMERIC(18,6),
            surprise_percentage  NUMERIC(18,6),
            updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (ticker, fiscal_date_ending)
        )
        """
    )
    # The factor loads, per ticker, the latest quarter with reported_date <= score
    # date — a (ticker, reported_date DESC) index serves that point-in-time lookup.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_earnings_ticker_reported "
        "ON earnings (ticker, reported_date DESC)"
    )
    op.execute(
        "ALTER TABLE factor_scores ADD COLUMN IF NOT EXISTS earnings_surprise NUMERIC(10,6)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE factor_scores DROP COLUMN IF EXISTS earnings_surprise")
    op.execute("DROP TABLE IF EXISTS earnings")
