"""position_episodes: durable per-position lifetime for the trailing stop

Revision ID: 0048
Revises: 0047

The trailing stop needs to know two things the schema could not answer: when a
position OPENED (so "highest close since entry" has an anchor), and what peak
stopped it (so re-entry stays blocked until the close exceeds that peak).

Neither is derivable today. `live_positions` is a per-SYNC-RUN snapshot — unique
on (sync_run_id, ticker), no position identity, no open date, no lifetime. It
carries avg_entry_price and cost_basis but those shift with every buy_add, so they
are not the original entry either. `alpaca_orders` has fills, but positions can
also arrive at the broker by other routes, and the table does not predate the book.

One row per HELD EPISODE — an unbroken period of holding a ticker. Re-buying a
name after an exit opens a NEW episode with a fresh peak, which is the intended
semantics: the stop measures the trend the current position has lived through.

  closed_on IS NULL  ⇒ open episode. The partial unique index enforces at most
                       one per ticker; two open episodes would mean two
                       simultaneous peaks and an ambiguous stop.
  close_reason       ⇒ how it ended, so stop exits can be told apart from orphan
                       exits in analytics WITHOUT parsing reason prose.
  stop_peak          ⇒ set only on a trailing_stop close; the re-entry gate reads
                       it back (blocked while last_close <= stop_peak).
  pending_close_since⇒ absence from ONE sync is not evidence of a sale. A single
                       degraded sync would otherwise close the episode, and the
                       ticker reappearing next run would open a new one with a
                       RESET peak — a risk control silently loosening itself,
                       which is the worst failure mode available here. The
                       pipeline stamps this on first absence and only closes the
                       episode once absence persists across healthy syncs.

Inert until trailing_stop.enabled flips: nothing reads these rows while the
feature is off, and the pipeline maintains them regardless so that turning the
stop on does not start from an empty history.
"""
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS position_episodes (
            id                  SERIAL PRIMARY KEY,
            ticker              VARCHAR(20) NOT NULL,
            opened_on           DATE        NOT NULL,
            closed_on           DATE,
            close_reason        VARCHAR(32),
            stop_peak           NUMERIC(14,4),
            pending_close_since DATE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    # At most ONE open episode per ticker. Partial, so closed history accumulates
    # freely — a ticker bought, stopped and re-bought has many rows but only one
    # live peak at a time.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_position_episodes_open_ticker
        ON position_episodes (ticker) WHERE closed_on IS NULL
    """)
    # The delta step's hot read: "which of today's held tickers already have an
    # open episode, and what is their opened_on".
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_position_episodes_open
        ON position_episodes (closed_on, ticker)
    """)
    # The re-entry gate's read: the most recent stop-out per ticker.
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_position_episodes_stopped
        ON position_episodes (ticker, closed_on DESC)
        WHERE close_reason = 'trailing_stop'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_position_episodes_stopped")
    op.execute("DROP INDEX IF EXISTS idx_position_episodes_open")
    op.execute("DROP INDEX IF EXISTS idx_position_episodes_open_ticker")
    op.execute("DROP TABLE IF EXISTS position_episodes")
