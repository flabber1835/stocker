"""candidate_clusters: correlation cluster per candidate-pool ticker

Revision ID: 0014
Revises: 0013

The portfolio-builder computes correlation clusters over its whole candidate pool
(top `candidate_count` ranked names), but only persisted cluster_id for the ~30
SELECTED holdings (portfolio_holdings). The screener wants the cluster for every
ranked candidate, not just the held ones, so persist the full candidate-pool
cluster map per build here. One row per (run_id, ticker). cluster_id NULL for a
singleton (no co-moving peer) is NOT stored — only multi-member memberships are
written, so a missing row reads as "no applicable cluster".
"""
from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS candidate_clusters (
        run_id         UUID         NOT NULL REFERENCES portfolio_runs(run_id) ON DELETE CASCADE,
        portfolio_date DATE         NOT NULL,
        ticker         VARCHAR(20)  NOT NULL,
        cluster_id     VARCHAR(20)  NOT NULL,
        PRIMARY KEY (run_id, ticker)
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_candidate_clusters_run ON candidate_clusters(run_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_clusters")
