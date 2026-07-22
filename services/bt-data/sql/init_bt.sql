-- bt-data schema — the backtester's OWN database (bt-postgres on the separate
-- backtest machine). Entirely independent of the live trading DB.
--
-- The bt_prices / bt_fundamentals column shapes deliberately MIRROR what the live
-- pipeline factor functions expect, so the reused logic (compute_all_factors,
-- detect_regime, rank_universe, …) needs ZERO changes:
--
--   prices       → ticker, date, adjusted_close, close, volume
--   fundamentals → ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity,
--                  revenue_growth, eps_growth
--
-- The crucial difference from the live AV-fed tables: fundamentals here are
-- POINT-IN-TIME. `as_of_date` is Sharadar's `datekey` — the date the figure
-- BECAME KNOWN (filing date), not the fiscal period end. The backtester filters
-- `as_of_date <= D` so a simulated day D never sees fundamentals that hadn't been
-- reported yet (no look-ahead bias). This is the whole reason for Sharadar over AV.

-- ── Source data (filled by bt-data from Sharadar) ──────────────────────────────

CREATE TABLE IF NOT EXISTS bt_prices (
    ticker          VARCHAR(20)  NOT NULL,
    date            DATE         NOT NULL,
    -- NUMERIC(24,6): Sharadar closeadj is split+div adjusted BACKWARD, so a
    -- heavily reverse-split (often delisted penny) stock's old adjusted prices
    -- balloon into the billions+ — NUMERIC(16,6)'s ~10-billion ceiling
    -- overflowed mid-backfill. 18 integer digits is ample headroom.
    open            NUMERIC(24,6),
    high            NUMERIC(24,6),
    low             NUMERIC(24,6),
    close           NUMERIC(24,6),
    adjusted_close  NUMERIC(24,6),   -- Sharadar SEP closeadj (split+div adjusted)
    volume          NUMERIC(20,2),
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_bt_prices_date ON bt_prices(date);
-- Idempotent widen for pre-existing DBs (same-scale precision increase → no
-- row rewrite; a no-op once already NUMERIC(24,6)). See the reverse-split note.
ALTER TABLE bt_prices
    ALTER COLUMN open TYPE NUMERIC(24,6),
    ALTER COLUMN high TYPE NUMERIC(24,6),
    ALTER COLUMN low TYPE NUMERIC(24,6),
    ALTER COLUMN close TYPE NUMERIC(24,6),
    ALTER COLUMN adjusted_close TYPE NUMERIC(24,6);

CREATE TABLE IF NOT EXISTS bt_fundamentals (
    ticker          VARCHAR(20)  NOT NULL,
    as_of_date      DATE         NOT NULL,   -- Sharadar SF1 datekey (known-as-of)
    fiscal_period   VARCHAR(32),             -- e.g. 2023-03-31/ARQ (audit; not used in math)
    -- NUMERIC(24,6): pe/pb from a near-zero denominator, and our compute_growth
    -- dividing by abs(year_ago), can explode a ratio well past NUMERIC(16,6).
    -- Widened alongside prices so the SF1 stage can't overflow the same way.
    pe_ratio        NUMERIC(24,6),
    pb_ratio        NUMERIC(24,6),
    roe             NUMERIC(24,6),
    debt_to_equity  NUMERIC(24,6),
    revenue_growth  NUMERIC(24,6),
    eps_growth      NUMERIC(24,6),
    PRIMARY KEY (ticker, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_bt_fundamentals_asof ON bt_fundamentals(as_of_date);
-- Idempotent widen for pre-existing DBs (same-scale precision increase).
ALTER TABLE bt_fundamentals
    ALTER COLUMN pe_ratio TYPE NUMERIC(24,6),
    ALTER COLUMN pb_ratio TYPE NUMERIC(24,6),
    ALTER COLUMN roe TYPE NUMERIC(24,6),
    ALTER COLUMN debt_to_equity TYPE NUMERIC(24,6),
    ALTER COLUMN revenue_growth TYPE NUMERIC(24,6),
    ALTER COLUMN eps_growth TYPE NUMERIC(24,6);

-- Per-day investable universe snapshot (which tickers were tradeable / listed on D).
-- Sharadar SEP includes delisted names, so a backtest can hold a name that later
-- disappeared — survivorship-bias-free.
CREATE TABLE IF NOT EXISTS bt_universe (
    snapshot_date   DATE         NOT NULL,
    ticker          VARCHAR(20)  NOT NULL,
    name            VARCHAR(200),
    sector          VARCHAR(100),
    PRIMARY KEY (snapshot_date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_bt_universe_date ON bt_universe(snapshot_date);

-- Bookkeeping for the fetch jobs (backfill + incremental top-up).
CREATE TABLE IF NOT EXISTS bt_data_runs (
    run_id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type        VARCHAR(30)  NOT NULL,   -- 'backfill' | 'topup'
    table_name      VARCHAR(40),             -- bt_prices | bt_fundamentals | bt_universe
    status          VARCHAR(20)  NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','success','failed')),
    rows_written    BIGINT       NOT NULL DEFAULT 0,
    date_min        DATE,
    date_max        DATE,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    error_message   TEXT
);

-- ── Backtest results (filled by bt-engine; defined here so the one DB has it all) ─

CREATE TABLE IF NOT EXISTS bt_runs (
    run_id                      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    config                      JSONB        NOT NULL,
    strategy_id                 VARCHAR(100),
    start_date                  DATE         NOT NULL,
    end_date                    DATE         NOT NULL,
    drawdown_backstop_pct       NUMERIC(6,4),
    tx_cost_bps                 INTEGER      NOT NULL DEFAULT 0,
    fill_timing                 VARCHAR(16)  NOT NULL DEFAULT 'next_open',
    starting_capital            NUMERIC(18,2) NOT NULL DEFAULT 100000,
    status                      VARCHAR(20)  NOT NULL DEFAULT 'running'
                                    CHECK (status IN ('running','success','failed')),
    progress_pct                INTEGER      NOT NULL DEFAULT 0,
    total_return                NUMERIC(12,6),
    annualized_return           NUMERIC(12,6),
    sharpe_ratio                NUMERIC(10,4),
    max_drawdown                NUMERIC(10,4),
    benchmark_total_return      NUMERIC(12,6),
    alpha                       NUMERIC(12,6),
    avg_turnover                NUMERIC(10,4),
    win_rate                    NUMERIC(10,4),
    started_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at                TIMESTAMPTZ,
    error_message               TEXT
);
CREATE INDEX IF NOT EXISTS idx_bt_runs_started ON bt_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS bt_equity (
    run_id          UUID         NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
    date            DATE         NOT NULL,
    portfolio_value NUMERIC(18,2) NOT NULL,
    spy_value       NUMERIC(18,2),
    drawdown        NUMERIC(10,6),
    PRIMARY KEY (run_id, date)
);

CREATE TABLE IF NOT EXISTS bt_positions (
    run_id          UUID         NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
    date            DATE         NOT NULL,
    ticker          VARCHAR(20)  NOT NULL,
    qty             NUMERIC(18,6) NOT NULL,
    weight          NUMERIC(10,6),
    market_value    NUMERIC(18,2),
    PRIMARY KEY (run_id, date, ticker)
);

CREATE TABLE IF NOT EXISTS bt_trades (
    run_id          UUID         NOT NULL REFERENCES bt_runs(run_id) ON DELETE CASCADE,
    date            DATE         NOT NULL,
    ticker          VARCHAR(20)  NOT NULL,
    action          VARCHAR(12)  NOT NULL,   -- entry | exit | buy_add | sell_trim
    qty             NUMERIC(18,6) NOT NULL,
    price           NUMERIC(16,6) NOT NULL,
    tx_cost         NUMERIC(16,4) NOT NULL DEFAULT 0,
    reason          TEXT
);
CREATE INDEX IF NOT EXISTS idx_bt_trades_run_date ON bt_trades(run_id, date);

-- ── Phase 5: walk-forward parameter sweep ─────────────────────────────────────
-- One bt_sweeps row per sweep; one bt_sweep_results row per (config, both
-- windows). Sweep legs deliberately do NOT write bt_runs (that table stays the
-- interactive-run history); each result row is self-contained.
CREATE TABLE IF NOT EXISTS bt_sweeps (
    sweep_id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    spec            JSONB        NOT NULL,       -- grid + windows + base config + params
    status          VARCHAR(20)  NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','success','failed')),
    n_configs       INTEGER      NOT NULL,
    n_done          INTEGER      NOT NULL DEFAULT 0,
    tune_start      DATE         NOT NULL,
    tune_end        DATE         NOT NULL,
    validate_start  DATE         NOT NULL,
    validate_end    DATE         NOT NULL,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    error_message   TEXT
);

-- Uniqueness lives in uq_bt_sweep_results_cfg_win below (NOT a PK): Phase 5b
-- rolling mode writes one row per (config, window). Existing DBs are migrated
-- by the idempotent ALTERs that follow — bt-data re-runs this whole file on
-- every startup, which is the bt stack's schema-evolution channel.
CREATE TABLE IF NOT EXISTS bt_sweep_results (
    sweep_id        UUID         NOT NULL REFERENCES bt_sweeps(sweep_id) ON DELETE CASCADE,
    config_idx      INTEGER      NOT NULL,
    window_idx      INTEGER      NOT NULL DEFAULT 0,  -- chronological rolling window (0 = classic two-window)
    config_diff     JSONB        NOT NULL,       -- {dotted.path: value} over the base config
    in_sample       JSONB,                       -- full sim summary, tune window
    out_sample      JSONB,                       -- full sim summary, validate window
    is_sharpe       NUMERIC(10,4),
    oos_sharpe      NUMERIC(10,4),
    oos_return      NUMERIC(12,6),
    oos_max_drawdown NUMERIC(10,4),
    overfit_gap     NUMERIC(10,4),               -- is_sharpe − oos_sharpe (large = fit, not robust)
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_bt_sweep_results_oos
    ON bt_sweep_results (sweep_id, oos_sharpe DESC NULLS LAST);
-- Phase 5b migration for pre-rolling DBs (no-ops once applied / on fresh DBs):
ALTER TABLE bt_sweep_results ADD COLUMN IF NOT EXISTS window_idx INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bt_sweep_results DROP CONSTRAINT IF EXISTS bt_sweep_results_pkey;
CREATE UNIQUE INDEX IF NOT EXISTS uq_bt_sweep_results_cfg_win
    ON bt_sweep_results (sweep_id, config_idx, window_idx);

-- Phase 5b: per-config aggregates across the rolling windows. Rows exist only
-- for rolling-mode sweeps; the leaderboard endpoint auto-detects them. The
-- champion (max median_oos_sharpe; ties broken by worst_oos_sharpe then
-- config_idx) is the ONLY config replayed on the untouched holdout.
-- Champion/leaderboard rank on median OOS COMPOUNDED RETURN (owner objective =
-- long-run wealth). Sharpe/consistency/overfit_gap are retained as diagnostics.
CREATE TABLE IF NOT EXISTS bt_sweep_aggregates (
    sweep_id          UUID        NOT NULL REFERENCES bt_sweeps(sweep_id) ON DELETE CASCADE,
    config_idx        INTEGER     NOT NULL,
    config_diff       JSONB       NOT NULL,
    n_windows         INTEGER     NOT NULL,
    n_failed          INTEGER     NOT NULL DEFAULT 0,   -- error legs (excluded from stats, reported)
    median_oos_return NUMERIC(12,6),                    -- RANKING KEY: median compounded return across windows
    worst_oos_return  NUMERIC(12,6),
    median_oos_sharpe NUMERIC(10,4),                    -- diagnostic only
    worst_oos_sharpe  NUMERIC(10,4),
    consistency       NUMERIC(6,4),                     -- fraction of windows with OOS Sharpe > 0
    mean_overfit_gap  NUMERIC(10,4),
    is_champion       BOOLEAN     NOT NULL DEFAULT FALSE,
    holdout           JSONB,                            -- champion only: untouched-holdout sim summary
    PRIMARY KEY (sweep_id, config_idx)
);
-- Idempotent add for pre-existing DBs:
ALTER TABLE bt_sweep_aggregates ADD COLUMN IF NOT EXISTS median_oos_return NUMERIC(12,6);
ALTER TABLE bt_sweep_aggregates ADD COLUMN IF NOT EXISTS worst_oos_return  NUMERIC(12,6);
CREATE INDEX IF NOT EXISTS idx_bt_sweep_aggregates_return
    ON bt_sweep_aggregates (sweep_id, median_oos_return DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_bt_sweep_aggregates_median
    ON bt_sweep_aggregates (sweep_id, median_oos_sharpe DESC NULLS LAST);
-- Two-window results are ranked by oos_return (compounded return) too:
CREATE INDEX IF NOT EXISTS idx_bt_sweep_results_return
    ON bt_sweep_results (sweep_id, oos_return DESC NULLS LAST);
