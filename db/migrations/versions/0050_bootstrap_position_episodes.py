"""Bootstrap position_episodes for holdings that predate the trailing stop

Revision ID: 0050
Revises: 0049

Enabling the trailing stop on an existing book is not a no-op. `plan_episode_sync`
opens an episode the first time it sees a ticker held, stamping `opened_on` with
THAT session — so on activation day every holding gets an episode dated today, and
`build_stop_states` derives its peak from prices since then, i.e. today's close.

The consequence is the opposite of what the stop is for: a position already 25%
off its real high looks perfectly flat, cannot trip a 30% stop, and would have to
fall another 30% FROM HERE before the rule notices. The names most in need of the
stop are exactly the ones it would ignore.

So the episodes are reconstructed from evidence that already exists:

  opened_on  the earliest FILLED buy in alpaca_orders (by filled_at) for a currently-held ticker
             that has no later confirmed exit; failing that, the ticker's first
             appearance in live_positions. Orders are preferred because they are
             the real event — live_positions only records that we already held it.

  the peak   is NOT stored; build_stop_states derives it from daily_prices since
             opened_on, so a correct opened_on is sufficient and there is no
             second copy to drift.

CONSERVATIVE where evidence is missing: a held ticker with neither a fill nor a
live_positions history gets NO episode here, and the normal sync opens one at the
next run with today's date. That is the safe direction — a stop that arms late
costs an exit, while a fabricated early entry date invents a peak the position
never lived through and sells on a drawdown that never happened.

Idempotent: only inserts where no open episode exists.
"""
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        WITH latest AS (
            -- By completed_at, NOT MAX(sync_run_id): run_id is a UUID and does not
            -- order by recency, so MAX() would pick an arbitrary past sync.
            SELECT run_id FROM alpaca_sync_runs
             WHERE completed_at IS NOT NULL
             ORDER BY completed_at DESC LIMIT 1
        ),
        held AS (
            SELECT DISTINCT lp.ticker FROM live_positions lp
             WHERE lp.sync_run_id = (SELECT run_id FROM latest)
        ),
        first_buy AS (
            SELECT o.ticker, MIN(COALESCE(o.filled_at, o.created_at))::date AS d
              FROM alpaca_orders o
             WHERE o.ticker IN (SELECT ticker FROM held)
               AND o.side = 'buy' AND o.status = 'filled'
             GROUP BY o.ticker
        ),
        first_seen AS (
            SELECT lp.ticker, MIN(s.completed_at)::date AS d
              FROM live_positions lp
              JOIN alpaca_sync_runs s ON s.run_id = lp.sync_run_id
             WHERE lp.ticker IN (SELECT ticker FROM held)
             GROUP BY lp.ticker
        )
        INSERT INTO position_episodes (ticker, opened_on)
        SELECT h.ticker, COALESCE(fb.d, fs.d)
          FROM held h
          LEFT JOIN first_buy  fb ON fb.ticker = h.ticker
          LEFT JOIN first_seen fs ON fs.ticker = h.ticker
         WHERE COALESCE(fb.d, fs.d) IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM position_episodes e
                            WHERE e.ticker = h.ticker AND e.closed_on IS NULL)
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    # Only the rows this migration could have created: open, never stopped, no
    # close reason. A stop that has since fired is real state and is left alone.
    op.execute("DELETE FROM position_episodes "
               " WHERE closed_on IS NULL AND close_reason IS NULL "
               "   AND stop_peak IS NULL")
