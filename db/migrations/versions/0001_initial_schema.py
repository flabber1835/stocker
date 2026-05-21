"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000

All statements are idempotent (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
ALTER TABLE ... ADD COLUMN IF NOT EXISTS) so this migration is safe to re-run.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE IF NOT EXISTS universe_snapshots (
    id            SERIAL PRIMARY KEY,
    etf_ticker    VARCHAR(10)  NOT NULL,
    snapshot_date DATE         NOT NULL,
    ticker_count  INTEGER      NOT NULL,
    fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS universe_tickers (
    id           SERIAL PRIMARY KEY,
    snapshot_id  INTEGER      NOT NULL REFERENCES universe_snapshots(id) ON DELETE CASCADE,
    ticker       VARCHAR(20)  NOT NULL,
    name         TEXT,
    weight_pct   NUMERIC(10, 6),
    sector       TEXT,
    asset_class  TEXT
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_universe_tickers_snapshot ON universe_tickers(snapshot_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_universe_tickers_ticker   ON universe_tickers(ticker)")

    op.execute("""
CREATE TABLE IF NOT EXISTS daily_prices (
    id             SERIAL PRIMARY KEY,
    ticker         VARCHAR(20)   NOT NULL,
    date           DATE          NOT NULL,
    open           NUMERIC(14,4),
    high           NUMERIC(14,4),
    low            NUMERIC(14,4),
    close          NUMERIC(14,4),
    adjusted_close NUMERIC(14,4),
    volume         BIGINT,
    source         VARCHAR(50)   NOT NULL DEFAULT 'alpha_vantage',
    fetched_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, date)
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON daily_prices(ticker, date DESC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS fundamentals (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(20)   NOT NULL,
    as_of_date      DATE          NOT NULL,
    pe_ratio        NUMERIC(12,4),
    pb_ratio        NUMERIC(12,4),
    roe             NUMERIC(12,6),
    debt_to_equity  NUMERIC(12,4),
    revenue_growth  NUMERIC(12,6),
    eps_growth      NUMERIC(12,6),
    market_cap      BIGINT,
    avg_volume      BIGINT,
    source          VARCHAR(50)   NOT NULL DEFAULT 'alpha_vantage',
    fetched_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, as_of_date)
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker ON fundamentals(ticker, as_of_date DESC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS regime_snapshots (
    id              SERIAL PRIMARY KEY,
    run_id          UUID,
    snapshot_date   DATE         NOT NULL,
    raw_regime      VARCHAR(30)  NOT NULL,
    regime          VARCHAR(30)  NOT NULL,
    spy_price       NUMERIC(10,4),
    spy_sma_slow    NUMERIC(10,4),
    spy_vs_sma      NUMERIC(10,6),
    realized_vol    NUMERIC(10,6),
    calculated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_regime_date ON regime_snapshots(snapshot_date DESC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS execution_traces (
    trace_id        UUID         PRIMARY KEY,
    job_type        VARCHAR(50)  NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'running',
    root_run_id     UUID,
    strategy_id     VARCHAR(100),
    config_hash     VARCHAR(16),
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    notes           TEXT
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_traces_started  ON execution_traces(started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_traces_root_run ON execution_traces(root_run_id)")

    op.execute("""
CREATE TABLE IF NOT EXISTS execution_steps (
    step_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID         NOT NULL REFERENCES execution_traces(trace_id),
    service         VARCHAR(50)  NOT NULL,
    step_name       VARCHAR(100) NOT NULL,
    status          VARCHAR(20)  NOT NULL,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    input_summary   JSONB,
    output_summary  JSONB,
    warnings        JSONB,
    error_message   TEXT
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_steps_trace ON execution_steps(trace_id, started_at ASC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id                    UUID         PRIMARY KEY,
    job_type                  VARCHAR(50)  NOT NULL,
    status                    VARCHAR(20)  NOT NULL DEFAULT 'running',
    ticker_count              INTEGER,
    price_rows                INTEGER,
    fund_rows                 INTEGER,
    error_count               INTEGER      NOT NULL DEFAULT 0,
    error_message             TEXT,
    price_coverage_pct        NUMERIC(6,4),
    fundamental_coverage_pct  NUMERIC(6,4),
    started_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at              TIMESTAMPTZ
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_ingest_runs_started ON ingest_runs(started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ingest_runs_job     ON ingest_runs(job_type, started_at DESC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS factor_runs (
    run_id                  UUID         PRIMARY KEY,
    trace_id                UUID,
    strategy_id             VARCHAR(100) NOT NULL,
    config_hash             VARCHAR(16),
    score_date              DATE,
    universe_snapshot_id    INTEGER,
    price_data_max_date     DATE,
    raw_regime              VARCHAR(30),
    regime                  VARCHAR(30),
    status                  VARCHAR(20)  NOT NULL DEFAULT 'running',
    ticker_count            INTEGER,
    warning_count           INTEGER      NOT NULL DEFAULT 0,
    error_message           TEXT,
    started_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_factor_runs_date   ON factor_runs(score_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_factor_runs_status ON factor_runs(status, score_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_factor_runs_trace  ON factor_runs(trace_id)")

    op.execute("""
CREATE TABLE IF NOT EXISTS factor_scores (
    id              SERIAL PRIMARY KEY,
    run_id          UUID         NOT NULL REFERENCES factor_runs(run_id),
    ticker          VARCHAR(20)  NOT NULL,
    score_date      DATE         NOT NULL,
    momentum        NUMERIC(10,6),
    quality         NUMERIC(10,6),
    value           NUMERIC(10,6),
    growth          NUMERIC(10,6),
    low_volatility  NUMERIC(10,6),
    liquidity       NUMERIC(10,6),
    calculated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, ticker)
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_factor_scores_run        ON factor_scores(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_factor_scores_date       ON factor_scores(score_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_factor_scores_run_ticker ON factor_scores(run_id, ticker)")

    op.execute("""
CREATE TABLE IF NOT EXISTS ranking_runs (
    run_id               UUID         PRIMARY KEY,
    trace_id             UUID,
    source_factor_run_id UUID         NOT NULL REFERENCES factor_runs(run_id),
    strategy_id          VARCHAR(100) NOT NULL,
    config_hash          VARCHAR(16),
    regime               VARCHAR(50)  NOT NULL,
    rank_date            DATE         NOT NULL,
    status               VARCHAR(20)  NOT NULL DEFAULT 'running',
    universe_count       INTEGER,
    ranked_count         INTEGER,
    dropped_count        INTEGER,
    error_message        TEXT,
    started_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at         TIMESTAMPTZ
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_ranking_runs_started    ON ranking_runs(started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ranking_runs_factor_run ON ranking_runs(source_factor_run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ranking_runs_trace      ON ranking_runs(trace_id)")

    op.execute("""
CREATE TABLE IF NOT EXISTS rankings (
    id                    SERIAL PRIMARY KEY,
    run_id                UUID         NOT NULL REFERENCES ranking_runs(run_id),
    source_factor_run_id  UUID         NOT NULL REFERENCES factor_runs(run_id),
    strategy_id           VARCHAR(100) NOT NULL,
    regime                VARCHAR(50)  NOT NULL,
    rank_date             DATE         NOT NULL,
    ticker                VARCHAR(20)  NOT NULL,
    rank                  INTEGER      NOT NULL,
    composite_score       NUMERIC(10,6),
    percentile            NUMERIC(10,6),
    factor_scores         JSONB,
    ranked_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, ticker)
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_rankings_run        ON rankings(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_rankings_factor_run ON rankings(source_factor_run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_rankings_date       ON rankings(rank_date DESC, rank ASC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS jobs (
    id           SERIAL PRIMARY KEY,
    job_type     VARCHAR(100)  NOT NULL,
    status       VARCHAR(20)   NOT NULL DEFAULT 'pending',
    payload      JSONB,
    result       JSONB,
    error        TEXT,
    retry_count  INTEGER       NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at ASC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS vetter_runs (
    run_id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id              UUID,
    source_ranking_run_id UUID         NOT NULL REFERENCES ranking_runs(run_id),
    strategy_id           VARCHAR(100) NOT NULL,
    model                 VARCHAR(100) NOT NULL,
    status                VARCHAR(20)  NOT NULL DEFAULT 'running',
    candidate_count       INTEGER,
    flagged_count         INTEGER,
    started_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at          TIMESTAMPTZ,
    error_message         TEXT
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_vetter_runs_ranking ON vetter_runs(source_ranking_run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_vetter_runs_started ON vetter_runs(started_at DESC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS portfolio_runs (
    run_id                   UUID         PRIMARY KEY,
    trace_id                 UUID,
    source_ranking_run_id    UUID         NOT NULL REFERENCES ranking_runs(run_id),
    vetter_run_id            UUID REFERENCES vetter_runs(run_id),
    strategy_id              VARCHAR(100) NOT NULL,
    config_hash              VARCHAR(16),
    regime                   VARCHAR(30)  NOT NULL,
    portfolio_date           DATE         NOT NULL,
    status                   VARCHAR(20)  NOT NULL DEFAULT 'running',
    candidate_count          INTEGER,
    selected_count           INTEGER,
    covariance_window_days   INTEGER,
    avg_pairwise_correlation NUMERIC(8,6),
    portfolio_estimated_vol  NUMERIC(8,6),
    error_message            TEXT,
    started_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at             TIMESTAMPTZ
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_runs_started ON portfolio_runs(started_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_runs_ranking ON portfolio_runs(source_ranking_run_id)")

    op.execute("""
CREATE TABLE IF NOT EXISTS portfolio_holdings (
    id                    SERIAL PRIMARY KEY,
    run_id                UUID         NOT NULL REFERENCES portfolio_runs(run_id),
    source_ranking_run_id UUID         NOT NULL REFERENCES ranking_runs(run_id),
    strategy_id           VARCHAR(100) NOT NULL,
    regime                VARCHAR(50)  NOT NULL,
    portfolio_date        DATE         NOT NULL,
    ticker                VARCHAR(20)  NOT NULL,
    position              INTEGER      NOT NULL,
    weight                NUMERIC(8,6) NOT NULL,
    composite_score       NUMERIC(10,6),
    original_rank         INTEGER,
    adj_score             NUMERIC(10,6),
    portfolio_vol_at_add  NUMERIC(10,6),
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, ticker)
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_holdings_run  ON portfolio_holdings(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_holdings_date ON portfolio_holdings(portfolio_date DESC, position ASC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS vetter_exclusions (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID         NOT NULL REFERENCES vetter_runs(run_id) ON DELETE CASCADE,
    ticker      VARCHAR(20)  NOT NULL,
    reason      TEXT         NOT NULL,
    confidence  VARCHAR(10)  NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    risk_type   VARCHAR(50),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, ticker)
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_vetter_exclusions_run ON vetter_exclusions(run_id)")

    op.execute("""
CREATE TABLE IF NOT EXISTS vetter_decisions (
    id                       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                   UUID         NOT NULL REFERENCES vetter_runs(run_id) ON DELETE CASCADE,
    ticker                   VARCHAR(20)  NOT NULL,
    exclude                  BOOLEAN      NOT NULL DEFAULT FALSE,
    reason                   TEXT,
    confidence               VARCHAR(10)  CHECK (confidence IN ('high', 'medium', 'low')),
    risk_type                VARCHAR(50),
    positive_catalyst        BOOLEAN      NOT NULL DEFAULT FALSE,
    positive_reason          TEXT,
    hallucination_flag_count INTEGER      NOT NULL DEFAULT 0,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, ticker)
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_vetter_decisions_run ON vetter_decisions(run_id)")
    op.execute("""
CREATE INDEX IF NOT EXISTS idx_vetter_decisions_catalyst ON vetter_decisions(run_id, positive_catalyst)
    WHERE positive_catalyst = TRUE
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS alpaca_sync_runs (
    run_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    status         VARCHAR(20)  NOT NULL DEFAULT 'running',
    account_value  NUMERIC(14,2),
    buying_power   NUMERIC(14,2),
    cash           NUMERIC(14,2),
    position_count INTEGER,
    error_message  TEXT,
    started_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at   TIMESTAMPTZ
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_alpaca_sync_runs_started ON alpaca_sync_runs(started_at DESC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS live_positions (
    id              SERIAL        PRIMARY KEY,
    sync_run_id     UUID          NOT NULL REFERENCES alpaca_sync_runs(run_id) ON DELETE CASCADE,
    ticker          VARCHAR(20)   NOT NULL,
    qty             NUMERIC(16,6) NOT NULL,
    avg_entry_price NUMERIC(14,4),
    current_price   NUMERIC(14,4),
    market_value    NUMERIC(14,2),
    cost_basis      NUMERIC(14,2),
    unrealized_pl   NUMERIC(14,2),
    unrealized_plpc NUMERIC(10,6),
    side            VARCHAR(10),
    lastday_price   NUMERIC(14,4),
    change_today    NUMERIC(10,6),
    synced_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (sync_run_id, ticker)
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_live_positions_sync ON live_positions(sync_run_id)")

    op.execute("""
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id                      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id                 VARCHAR(100) NOT NULL,
    config_hash                 VARCHAR(16),
    status                      VARCHAR(20)  NOT NULL DEFAULT 'running'
                                    CHECK (status IN ('running','success','failed')),
    date_from                   DATE,
    date_to                     DATE,
    n_rebalances                INTEGER,
    source_portfolio_run_ids    JSONB,
    total_return                NUMERIC(12,6),
    annualized_return           NUMERIC(12,6),
    sharpe_ratio                NUMERIC(10,4),
    max_drawdown                NUMERIC(10,4),
    avg_monthly_turnover        NUMERIC(10,4),
    win_rate                    NUMERIC(10,4),
    benchmark_total_return      NUMERIC(12,6),
    benchmark_annualized_return NUMERIC(12,6),
    tx_cost_bps                 INTEGER      NOT NULL DEFAULT 0,
    trace_id                    UUID         REFERENCES execution_traces(trace_id),
    started_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at                TIMESTAMPTZ,
    error_message               TEXT
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy ON backtest_runs(strategy_id, started_at DESC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS backtest_monthly (
    id                SERIAL       PRIMARY KEY,
    run_id            UUID         NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    period_start      DATE         NOT NULL,
    period_end        DATE         NOT NULL,
    regime            VARCHAR(50),
    portfolio_return  NUMERIC(12,6),
    benchmark_return  NUMERIC(12,6),
    excess_return     NUMERIC(12,6),
    turnover          NUMERIC(10,4),
    n_holdings        INTEGER,
    holdings_snapshot JSONB
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_backtest_monthly_run ON backtest_monthly(run_id, period_start ASC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS delta_runs (
    run_id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id                 UUID,
    strategy_id              VARCHAR(100) NOT NULL,
    config_hash              VARCHAR(16),
    status                   VARCHAR(20)  NOT NULL DEFAULT 'running'
                                 CHECK (status IN ('running','success','failed')),
    run_date                 DATE         NOT NULL,
    source_ranking_run_id    UUID,
    source_portfolio_run_id  UUID,
    entry_rank               INTEGER,
    exit_rank                INTEGER,
    confirmation_days        INTEGER,
    max_positions            INTEGER,
    current_portfolio_size   INTEGER,
    entries_count            INTEGER      NOT NULL DEFAULT 0,
    exits_count              INTEGER      NOT NULL DEFAULT 0,
    holds_count              INTEGER      NOT NULL DEFAULT 0,
    watches_count            INTEGER      NOT NULL DEFAULT 0,
    started_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at             TIMESTAMPTZ,
    error_message            TEXT
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_delta_runs_date ON delta_runs(run_date DESC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS delta_intents (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                UUID         NOT NULL REFERENCES delta_runs(run_id) ON DELETE CASCADE,
    ticker                VARCHAR(20)  NOT NULL,
    action                VARCHAR(10)  NOT NULL CHECK (action IN ('entry','exit','hold','watch')),
    rank                  INTEGER,
    composite_score       NUMERIC(12,6),
    confirmation_days_met INTEGER,
    current_weight        NUMERIC(10,6),
    reason                TEXT,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_delta_intents_run ON delta_intents(run_id, action)")

    op.execute("""
CREATE TABLE IF NOT EXISTS alpaca_orders (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_id         UUID,
    alpaca_order_id   VARCHAR(64),
    ticker            VARCHAR(20)  NOT NULL,
    action            VARCHAR(10)  NOT NULL,
    side              VARCHAR(10)  NOT NULL,
    qty               NUMERIC(16,4),
    notional          NUMERIC(16,4),
    order_type        VARCHAR(20),
    time_in_force     VARCHAR(10),
    status            VARCHAR(20)  NOT NULL DEFAULT 'pending',
    mode              VARCHAR(20),
    risk_approved     BOOLEAN      NOT NULL DEFAULT FALSE,
    risk_reason       TEXT,
    alpaca_status     VARCHAR(30),
    submitted_at      TIMESTAMPTZ,
    filled_at         TIMESTAMPTZ,
    avg_fill_price    NUMERIC(16,4),
    filled_qty        NUMERIC(16,4),
    error_message     TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_alpaca_orders_ticker  ON alpaca_orders(ticker)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alpaca_orders_created ON alpaca_orders(created_at DESC)")

    op.execute("""
CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker               VARCHAR(20)  NOT NULL,
    action               VARCHAR(10)  NOT NULL,
    side                 VARCHAR(10)  NOT NULL,
    qty                  NUMERIC(16,6),
    notional             NUMERIC(16,2),
    mode                 VARCHAR(20),
    trade_type           VARCHAR(10)  NOT NULL DEFAULT 'paper',
    approved             BOOLEAN      NOT NULL,
    rule_triggered       VARCHAR(50),
    reason               TEXT,
    kill_switch          BOOLEAN,
    paper_only           BOOLEAN,
    live_trading_enabled BOOLEAN,
    max_order_notional   NUMERIC(16,2),
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
""")

    op.execute("CREATE INDEX IF NOT EXISTS idx_risk_decisions_created ON risk_decisions(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_risk_decisions_ticker  ON risk_decisions(ticker)")

    # Add FK and extra columns idempotently
    op.execute("ALTER TABLE alpaca_orders ADD COLUMN IF NOT EXISTS risk_check_id UUID")
    op.execute("ALTER TABLE alpaca_orders DROP CONSTRAINT IF EXISTS fk_alpaca_orders_risk")
    op.execute("""
ALTER TABLE alpaca_orders
  ADD CONSTRAINT fk_alpaca_orders_risk
  FOREIGN KEY (risk_check_id) REFERENCES risk_decisions(decision_id) ON DELETE SET NULL
  NOT VALID
""")
    op.execute("ALTER TABLE alpaca_orders     ADD COLUMN IF NOT EXISTS trace_id UUID REFERENCES execution_traces(trace_id)")
    op.execute("ALTER TABLE alpaca_sync_runs  ADD COLUMN IF NOT EXISTS trace_id UUID REFERENCES execution_traces(trace_id)")
    op.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_alpaca_orders_intent_open
  ON alpaca_orders(intent_id)
  WHERE intent_id IS NOT NULL AND status IN ('pending','submitted')
""")
    op.execute("ALTER TABLE alpaca_orders DROP CONSTRAINT IF EXISTS fk_alpaca_orders_intent")
    op.execute("""
ALTER TABLE alpaca_orders
  ADD CONSTRAINT fk_alpaca_orders_intent
  FOREIGN KEY (intent_id) REFERENCES delta_intents(id) ON DELETE SET NULL
  NOT VALID
""")

    op.execute("""
CREATE TABLE IF NOT EXISTS scheduler_runs (
    run_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running',
    chain_date   TEXT NOT NULL,
    steps        JSONB NOT NULL DEFAULT '{}',
    run_ids      JSONB NOT NULL DEFAULT '{}'
)
""")


def downgrade() -> None:
    # Downgrade is intentionally a no-op — we don't drop tables in production.
    pass
