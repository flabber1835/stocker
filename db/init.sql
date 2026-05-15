-- Stocker database schema
-- Run automatically on first postgres startup via docker-entrypoint-initdb.d

-- ── Universe ─────────────────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS universe_snapshots (
    id          SERIAL PRIMARY KEY,
    etf_ticker  VARCHAR(10)  NOT NULL,
    snapshot_date DATE       NOT NULL,
    ticker_count  INTEGER    NOT NULL,
    fetched_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS universe_tickers (
    id           SERIAL PRIMARY KEY,
    snapshot_id  INTEGER      NOT NULL REFERENCES universe_snapshots(id) ON DELETE CASCADE,
    ticker       VARCHAR(20)  NOT NULL,
    name         TEXT,
    weight_pct   NUMERIC(10, 6),
    sector       TEXT,
    asset_class  TEXT
);

CREATE INDEX IF NOT EXISTS idx_universe_tickers_snapshot ON universe_tickers(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_universe_tickers_ticker   ON universe_tickers(ticker);

-- ── Prices ──────────────────────────────────────────────────────────────────────────────────────────

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
);

CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON daily_prices(ticker, date DESC);

-- ── Fundamentals ──────────────────────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fundamentals (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(20)   NOT NULL,
    as_of_date      DATE          NOT NULL,
    pe_ratio        NUMERIC(12,4),
    pb_ratio        NUMERIC(12,4),
    roe             NUMERIC(12,6),   -- decimal, e.g. 0.18 = 18%
    debt_to_equity  NUMERIC(12,4),
    revenue_growth  NUMERIC(12,6),   -- YoY decimal
    eps_growth      NUMERIC(12,6),   -- YoY decimal
    market_cap      BIGINT,
    avg_volume      BIGINT,
    source          VARCHAR(50)   NOT NULL DEFAULT 'alpha_vantage',
    fetched_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker ON fundamentals(ticker, as_of_date DESC);

-- ── Regime ─────────────────────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS regime_snapshots (
    id              SERIAL PRIMARY KEY,
    run_id          UUID,
    snapshot_date   DATE         NOT NULL,
    raw_regime      VARCHAR(30)  NOT NULL,  -- today's signal-derived regime, unconfirmed
    regime          VARCHAR(30)  NOT NULL,  -- confirmed regime (retained until N days of new raw signal)
    spy_price       NUMERIC(10,4),
    spy_sma_slow    NUMERIC(10,4),          -- configurable slow SMA (default 200-day)
    spy_vs_sma      NUMERIC(10,6),          -- (price/sma_slow) - 1
    realized_vol    NUMERIC(10,6),          -- annualized 20-day realized vol used for regime
    calculated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_regime_date ON regime_snapshots(snapshot_date DESC);

-- ── Execution traces ───────────────────────────────────────────────────────────────────────────────────────────────────────
-- One trace per top-level job. Steps record each sub-operation.
-- Answers: what data was used, what config was active, what happened at each step.

CREATE TABLE IF NOT EXISTS execution_traces (
    trace_id        UUID         PRIMARY KEY,
    job_type        VARCHAR(50)  NOT NULL,        -- 'factor_run' | 'rank_run' | 'portfolio_run' | 'vetter_run'
    status          VARCHAR(20)  NOT NULL DEFAULT 'running',  -- running|success|failed|skipped
    root_run_id     UUID,                         -- factor_runs.run_id or ranking_runs.run_id
    strategy_id     VARCHAR(100),
    config_hash     VARCHAR(16),                  -- first 16 hex chars of SHA256 of strategy YAML
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_traces_started    ON execution_traces(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_traces_root_run   ON execution_traces(root_run_id);

CREATE TABLE IF NOT EXISTS execution_steps (
    step_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID         NOT NULL REFERENCES execution_traces(trace_id),
    service         VARCHAR(50)  NOT NULL,
    step_name       VARCHAR(100) NOT NULL,
    status          VARCHAR(20)  NOT NULL,  -- success|failed|skipped
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    input_summary   JSONB,
    output_summary  JSONB,
    warnings        JSONB,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_steps_trace ON execution_steps(trace_id, started_at ASC);

-- ── Ingest runs ────────────────────────────────────────────────────────────────────────────────────────────────
-- One row per av-ingestor job (fetch-universe, fetch-data, fetch-prices, fetch-fundamentals).
-- Allows make data to poll for completion instead of checking price_rows > 0.

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id                    UUID         PRIMARY KEY,
    job_type                  VARCHAR(50)  NOT NULL,   -- fetch-universe|fetch-data|fetch-prices|fetch-fundamentals
    status                    VARCHAR(20)  NOT NULL DEFAULT 'running',  -- running|success|partial_success|failed
    ticker_count              INTEGER,
    price_rows                INTEGER,
    fund_rows                 INTEGER,
    error_count               INTEGER      NOT NULL DEFAULT 0,
    error_message             TEXT,
    price_coverage_pct        NUMERIC(6,4),            -- fraction of tickers with price data (0..1)
    fundamental_coverage_pct  NUMERIC(6,4),            -- fraction of tickers with fundamental data (0..1)
    started_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ingest_runs_started ON ingest_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_job     ON ingest_runs(job_type, started_at DESC);

-- ── Factor runs ────────────────────────────────────────────────────────────────────────────────────────────────────
-- One row per factor calculation job. Regime snapshot and factor scores are
-- written only when status = 'success'. Ranker uses only successful runs.

CREATE TABLE IF NOT EXISTS factor_runs (
    run_id                  UUID         PRIMARY KEY,
    trace_id                UUID,                         -- execution_traces.trace_id
    strategy_id             VARCHAR(100) NOT NULL,
    config_hash             VARCHAR(16),                  -- identifies exact strategy version
    score_date              DATE,                         -- set after success; latest SPY trading date
    universe_snapshot_id    INTEGER,                      -- universe_snapshots.id used for this run
    price_data_max_date     DATE,                         -- latest date in loaded price data
    raw_regime              VARCHAR(30),
    regime                  VARCHAR(30),
    status                  VARCHAR(20)  NOT NULL DEFAULT 'running',  -- running|success|failed|skipped
    ticker_count            INTEGER,
    warning_count           INTEGER      NOT NULL DEFAULT 0,
    error_message           TEXT,
    started_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at            TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_factor_runs_date   ON factor_runs(score_date DESC);
CREATE INDEX IF NOT EXISTS idx_factor_runs_status ON factor_runs(status, score_date DESC);
CREATE INDEX IF NOT EXISTS idx_factor_runs_trace  ON factor_runs(trace_id);

-- ── Factor scores ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS factor_scores (
    id              SERIAL PRIMARY KEY,
    run_id          UUID         NOT NULL REFERENCES factor_runs(run_id),
    ticker          VARCHAR(20)  NOT NULL,
    score_date      DATE         NOT NULL,
    momentum        NUMERIC(10,6),  -- z-score, clipped [-2.5, 2.5]
    quality         NUMERIC(10,6),
    value           NUMERIC(10,6),
    growth          NUMERIC(10,6),
    low_volatility  NUMERIC(10,6),
    liquidity       NUMERIC(10,6),
    calculated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_factor_scores_run  ON factor_scores(run_id);
CREATE INDEX IF NOT EXISTS idx_factor_scores_date ON factor_scores(score_date DESC);
CREATE INDEX IF NOT EXISTS idx_factor_scores_run_ticker ON factor_scores(run_id, ticker);

-- ── Ranking runs ────────────────────────────────────────────────────────────────────────────────────────────────
-- One row per ranking job. Per-ticker rows live in the rankings table.

CREATE TABLE IF NOT EXISTS ranking_runs (
    run_id               UUID         PRIMARY KEY,
    trace_id             UUID,                         -- execution_traces.trace_id
    source_factor_run_id UUID         NOT NULL REFERENCES factor_runs(run_id),
    strategy_id          VARCHAR(100) NOT NULL,
    config_hash          VARCHAR(16),
    regime               VARCHAR(30)  NOT NULL,
    rank_date            DATE         NOT NULL,
    status               VARCHAR(20)  NOT NULL DEFAULT 'running',  -- running|success|failed
    universe_count       INTEGER,                      -- tickers from factor run
    ranked_count         INTEGER,                      -- tickers that passed all gates
    dropped_count        INTEGER,                      -- tickers dropped (no quality, too sparse, etc.)
    error_message        TEXT,
    started_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ranking_runs_started      ON ranking_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ranking_runs_factor_run   ON ranking_runs(source_factor_run_id);
CREATE INDEX IF NOT EXISTS idx_ranking_runs_trace        ON ranking_runs(trace_id);

-- ── Rankings ────────────────────────────────────────────────────────────────────────────────────────────────────────
-- Per-ticker ranking rows. run_id links to ranking_runs.

CREATE TABLE IF NOT EXISTS rankings (
    id                    SERIAL PRIMARY KEY,
    run_id                UUID         NOT NULL REFERENCES ranking_runs(run_id),
    source_factor_run_id  UUID         NOT NULL REFERENCES factor_runs(run_id),
    strategy_id           VARCHAR(100) NOT NULL,
    regime                VARCHAR(20)  NOT NULL,
    rank_date             DATE         NOT NULL,   -- score_date of the source factor run
    ticker                VARCHAR(20)  NOT NULL,
    rank                  INTEGER      NOT NULL,
    composite_score       NUMERIC(10,6),
    percentile            NUMERIC(10,6),
    factor_scores         JSONB,                   -- snapshot of individual z-scores
    ranked_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_rankings_run          ON rankings(run_id);
CREATE INDEX IF NOT EXISTS idx_rankings_factor_run   ON rankings(source_factor_run_id);
CREATE INDEX IF NOT EXISTS idx_rankings_date         ON rankings(rank_date DESC, rank ASC);

-- ── Job queue (Postgres SKIP LOCKED) ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS jobs (
    id           SERIAL PRIMARY KEY,
    job_type     VARCHAR(100)  NOT NULL,
    status       VARCHAR(20)   NOT NULL DEFAULT 'pending',  -- pending|running|done|failed
    payload      JSONB,
    result       JSONB,
    error        TEXT,
    retry_count  INTEGER       NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at ASC);

-- ── Portfolio runs ────────────────────────────────────────────────────────────────────────────────────────────────
-- One row per portfolio-builder job. Holdings live in portfolio_holdings.

CREATE TABLE IF NOT EXISTS portfolio_runs (
    run_id                   UUID         PRIMARY KEY,
    trace_id                 UUID,
    source_ranking_run_id    UUID         NOT NULL REFERENCES ranking_runs(run_id),
    vetter_run_id            UUID         REFERENCES vetter_runs(run_id),
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
);

CREATE INDEX IF NOT EXISTS idx_portfolio_runs_started ON portfolio_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_portfolio_runs_ranking ON portfolio_runs(source_ranking_run_id);

-- ── Portfolio holdings ────────────────────────────────────────────────────────────────────────────────────────────────
-- Per-ticker rows for each portfolio run.

CREATE TABLE IF NOT EXISTS portfolio_holdings (
    id                    SERIAL PRIMARY KEY,
    run_id                UUID         NOT NULL REFERENCES portfolio_runs(run_id),
    source_ranking_run_id UUID         NOT NULL REFERENCES ranking_runs(run_id),
    strategy_id           VARCHAR(100) NOT NULL,
    regime                VARCHAR(20)  NOT NULL,
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
);

CREATE INDEX IF NOT EXISTS idx_portfolio_holdings_run  ON portfolio_holdings(run_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_holdings_date ON portfolio_holdings(portfolio_date DESC, position ASC);

-- ── LLM vetter runs ───────────────────────────────────────────────────────────────────────────────────
-- One row per vetting job. Stores whether the run was approved by a human operator.

CREATE TABLE IF NOT EXISTS vetter_runs (
    run_id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id              UUID,                    -- execution_traces.trace_id
    source_ranking_run_id UUID         NOT NULL REFERENCES ranking_runs(run_id),
    strategy_id           VARCHAR(100) NOT NULL,
    model                 VARCHAR(100) NOT NULL,
    status                VARCHAR(20)  NOT NULL DEFAULT 'running',  -- running|success|failed
    candidate_count       INTEGER,
    flagged_count         INTEGER,
    approved              BOOLEAN      NOT NULL DEFAULT FALSE,
    approved_at           TIMESTAMPTZ,
    started_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at          TIMESTAMPTZ,
    error_message         TEXT
);

CREATE INDEX IF NOT EXISTS idx_vetter_runs_ranking ON vetter_runs(source_ranking_run_id);
CREATE INDEX IF NOT EXISTS idx_vetter_runs_started ON vetter_runs(started_at DESC);

-- ── LLM vetter exclusions ─────────────────────────────────────────────────────────────────────────────
-- Per-ticker exclusion recommendations from the LLM vetter.

CREATE TABLE IF NOT EXISTS vetter_exclusions (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID         NOT NULL REFERENCES vetter_runs(run_id) ON DELETE CASCADE,
    ticker      VARCHAR(20)  NOT NULL,
    reason      TEXT         NOT NULL,
    confidence  VARCHAR(10)  NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    risk_type   VARCHAR(50),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_vetter_exclusions_run ON vetter_exclusions(run_id);
