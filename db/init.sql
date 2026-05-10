-- Stocker database schema
-- Run automatically on first postgres startup via docker-entrypoint-initdb.d

-- ── Universe ──────────────────────────────────────────────────────────────────

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

-- ── Prices ────────────────────────────────────────────────────────────────────

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

-- ── Fundamentals ──────────────────────────────────────────────────────────────

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

-- ── Regime ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS regime_snapshots (
    id              SERIAL PRIMARY KEY,
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

-- ── Factor runs ───────────────────────────────────────────────────────────────
-- One row per factor calculation run. Regime snapshot and factor scores are
-- written only when status = 'success'. Ranker uses only successful runs.

CREATE TABLE IF NOT EXISTS factor_runs (
    run_id          UUID         PRIMARY KEY,
    strategy_id     VARCHAR(100) NOT NULL,
    score_date      DATE         NOT NULL,
    raw_regime      VARCHAR(30),
    regime          VARCHAR(30),
    status          VARCHAR(20)  NOT NULL DEFAULT 'running',  -- running|success|failed|skipped
    ticker_count    INTEGER,
    error           TEXT,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_factor_runs_date   ON factor_runs(score_date DESC);
CREATE INDEX IF NOT EXISTS idx_factor_runs_status ON factor_runs(status, score_date DESC);

-- ── Factor scores ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS factor_scores (
    id              SERIAL PRIMARY KEY,
    run_id          UUID         NOT NULL,
    ticker          VARCHAR(20)  NOT NULL,
    score_date      DATE         NOT NULL,
    regime          VARCHAR(20)  NOT NULL,
    momentum        NUMERIC(10,6),  -- z-score, clipped [-3,3]
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

-- ── Rankings ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rankings (
    id               SERIAL PRIMARY KEY,
    run_id           UUID         NOT NULL,
    strategy_id      VARCHAR(100) NOT NULL,
    regime           VARCHAR(20)  NOT NULL,
    rank_date        DATE         NOT NULL,
    ticker           VARCHAR(20)  NOT NULL,
    rank             INTEGER      NOT NULL,
    composite_score  NUMERIC(10,6),
    percentile       NUMERIC(10,6),
    factor_scores    JSONB,         -- snapshot of individual z-scores
    ranked_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_rankings_run  ON rankings(run_id);
CREATE INDEX IF NOT EXISTS idx_rankings_date ON rankings(rank_date DESC, rank ASC);

-- ── Job queue (Postgres SKIP LOCKED) ─────────────────────────────────────────

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
