"""analyst_snapshots table — point-in-time forward-looking analyst data

Revision ID: 0029
Revises: 0028

Supports a future FORWARD-LOOKING (leading) factor: analyst target-price and
rating-distribution REVISIONS. Unlike the trailing factor stack (price/reported
fundamentals), these are expectations data — low-correlation to the existing
factors and anticipatory at fundamental inflections.

Source: Alpha Vantage OVERVIEW (already fetched for fundamentals — these fields
ride in the SAME payload, so capturing them costs no extra API call):
AnalystTargetPrice, AnalystRatingStrongBuy/Buy/Hold/Sell/StrongSell, ForwardPE,
PEGRatio.

Point-in-time by construction: AV exposes only the CURRENT consensus, so we
SNAPSHOT it per fetch (keyed by snapshot_date) and accumulate our own history.
A revision factor is then `latest snapshot − a prior snapshot`. There is no clean
free backfill, so the factor must be evaluated FORWARD/out-of-sample — it cannot
be honestly backtested over dates before snapshots existed.

Backwards compatible and idempotent. No factor column is added here — this
migration only lands the raw snapshot store; the derived factor column is a
separate change once enough history has accumulated.
"""
from alembic import op

revision = "0029"
down_revision = "0028"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analyst_snapshots (
            ticker             VARCHAR(20)  NOT NULL,
            snapshot_date      DATE         NOT NULL,
            target_price       NUMERIC(18,6),
            rating_strong_buy  INTEGER,
            rating_buy         INTEGER,
            rating_hold        INTEGER,
            rating_sell        INTEGER,
            rating_strong_sell INTEGER,
            forward_pe         NUMERIC(18,6),
            peg_ratio          NUMERIC(18,6),
            fetched_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (ticker, snapshot_date)
        )
        """
    )
    # The revision factor reads, per ticker, the latest snapshot and a prior one —
    # a (ticker, snapshot_date DESC) index serves that newest-first lookup.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_analyst_snapshots_ticker_date "
        "ON analyst_snapshots (ticker, snapshot_date DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analyst_snapshots")
