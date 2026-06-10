"""rankings: composite indexes for the /rankings/with-overlays query

Revision ID: 0022
Revises: 0021

The dashboard screener's /rankings/with-overlays endpoint got slow enough to blow
the proxy timeout once the universe grew (core ~2050 → speculative ~2920) and the
rankings table accumulated runs. The single-column idx_rankings_run (run_id) exists,
but the heaviest CTE —

    SELECT r.ticker, REGR_SLOPE(r.rank, rr.x_pos)
    FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id
    GROUP BY r.ticker

— still had to heap-fetch ticker+rank for every row of the last 5 runs, and as the
table grew the planner could tip from index scan to seq scan.

  - idx_rankings_run_ticker_rank (run_id, ticker, rank): covers that CTE as an
    INDEX-ONLY scan (all three columns it needs are in the index), and also serves
    the held-rank lookup WHERE run_id = ? AND ticker = ANY(?).
  - idx_rankings_run_rank (run_id, rank): serves the final
    WHERE run_id = ? ORDER BY rank LIMIT n (top-N) and the prior-run lookup without
    a separate sort.

Both additive and idempotent (CREATE INDEX IF NOT EXISTS). No data change; the
write cost is one index update per ranking insert (a few thousand rows per daily
run — negligible).
"""
from alembic import op

revision = "0022"
down_revision = "0021"


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_rankings_run_ticker_rank "
        "ON rankings(run_id, ticker, rank)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_rankings_run_rank "
        "ON rankings(run_id, rank)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_rankings_run_rank")
    op.execute("DROP INDEX IF EXISTS idx_rankings_run_ticker_rank")
