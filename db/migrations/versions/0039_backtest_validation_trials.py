"""backtest validation + trials registry + per-config sim fields (G2/G1)

Revision ID: 0039
Revises: 0038

Makes the backtester usable as an evaluator TOOL:
- backtest_runs gains `summary` (full metrics incl. distribution stats),
  `validation` (DSR/PSR/PBO/MinTRL verdict), `sim_mode`
  ('persisted_replay' | 'config_replay') and `config_json` (the request config
  for a per-config run — G1), so a result is self-describing and auditable.
- backtest_trials: one row per (config_hash, date range, tx_cost) actually run.
  DSR/PBO deflate the best Sharpe by the NUMBER OF CONFIGS TRIED; without an
  honest trial count the LLM evaluator could run 20 backtests and cite the best
  with no multiple-testing penalty (the overfitting trap). This is that count.

Backwards compatible and idempotent.
"""
from alembic import op

revision = "0039"
down_revision = "0038"


def upgrade() -> None:
    op.execute("ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS summary JSONB")
    op.execute("ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS validation JSONB")
    op.execute("ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS sim_mode VARCHAR(20)")
    op.execute("ALTER TABLE backtest_runs ADD COLUMN IF NOT EXISTS config_json JSONB")
    op.execute("""
        CREATE TABLE IF NOT EXISTS backtest_trials (
            id           SERIAL      PRIMARY KEY,
            config_hash  VARCHAR(64) NOT NULL,
            strategy_id  VARCHAR(100),
            date_from    DATE,
            date_to      DATE,
            tx_cost_bps  INTEGER,
            sim_mode     VARCHAR(20),
            run_id       UUID,
            sharpe       NUMERIC(10,4),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_backtest_trials_hash "
               "ON backtest_trials (config_hash, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS backtest_trials")
    op.execute("ALTER TABLE backtest_runs DROP COLUMN IF EXISTS config_json")
    op.execute("ALTER TABLE backtest_runs DROP COLUMN IF EXISTS sim_mode")
    op.execute("ALTER TABLE backtest_runs DROP COLUMN IF EXISTS validation")
    op.execute("ALTER TABLE backtest_runs DROP COLUMN IF EXISTS summary")
