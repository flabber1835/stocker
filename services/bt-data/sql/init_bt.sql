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
    close_unadjusted NUMERIC(24,6),  -- SEP closeunadj: the AS-TRADED price
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
-- The AS-TRADED price. Added after the fact, so an existing bt-postgres picks
-- it up on the next bt-data startup (this file is re-applied idempotently) —
-- but it stays NULL until the SEP stage is RE-BACKFILLED, and anything that
-- needs a raw price must refuse rather than fall back to `close`.
ALTER TABLE bt_prices ADD COLUMN IF NOT EXISTS close_unadjusted NUMERIC(24,6);

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
    -- Coverage-contract fields (2026-07). SF1 always carried these; the mapper
    -- discarded them, which made small_cap/issuance structurally null here and
    -- narrowed the tunnel's rankable universe vs live (availability counts even
    -- weight-0 factors toward min_non_null_factors). See docs/architecture.md
    -- "factor-coverage contract between live and the wind tunnel".
    market_cap               NUMERIC(24,2),   -- SF1 marketcap    → small_cap
    shares_outstanding       NUMERIC(22,2),   -- SF1 sharesbas    → issuance
    shares_outstanding_prior NUMERIC(22,2),   -- the ~year-ago filing
    -- Novy-Marx gross-profits-to-assets, the profitability leg of `quality` when
    -- quality_use_gross_profitability is on — which every strategy config in the
    -- repo sets. Absent, compute_quality falls back to ROE per ticker, so the
    -- tunnel scored a DIFFERENT quality factor under the same name at 25% of the
    -- composite, and the coverage contract saw a perfectly non-null column.
    gross_profit             NUMERIC(24,2),   -- SF1 gp
    total_assets             NUMERIC(24,2),   -- SF1 assets
    PRIMARY KEY (ticker, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_bt_fundamentals_asof ON bt_fundamentals(as_of_date);
-- Idempotent add for pre-existing DBs (bt-data re-applies this file on startup,
-- so an existing bt-postgres picks the columns up without a manual migration —
-- they stay NULL until the SF1 stage is re-backfilled).
ALTER TABLE bt_fundamentals
    ADD COLUMN IF NOT EXISTS market_cap               NUMERIC(24,2),
    ADD COLUMN IF NOT EXISTS shares_outstanding       NUMERIC(22,2),
    ADD COLUMN IF NOT EXISTS shares_outstanding_prior NUMERIC(22,2),
    ADD COLUMN IF NOT EXISTS gross_profit             NUMERIC(24,2),
    ADD COLUMN IF NOT EXISTS total_assets             NUMERIC(24,2),
    ADD COLUMN IF NOT EXISTS revenue                   NUMERIC(24,2),
    ADD COLUMN IF NOT EXISTS eps                       NUMERIC(24,6);

-- ── Corpus version ────────────────────────────────────────────────────────────
-- The factor cache in bt-engine used to key on the SHAPE of the loaded data (row
-- counts, ticker count, price date span). Nothing in that changes when data is
-- CORRECTED IN PLACE — e.g. the SF1 re-backfill that writes market_cap and
-- shares_outstanding onto EXISTING rows: same primary keys, same counts, same
-- span, byte-identical fingerprint, stale cache silently reused.
--
-- bt-data installs a fresh UUID only after one whole mutation generation has
-- completed and returned this singleton from PUBLISHING to READY. bt-engine
-- keys the cache on it and DISABLES the cache entirely if it cannot be
-- read — a weak identity is worse than no cache, which is only an optimization.
CREATE TABLE IF NOT EXISTS bt_data_version (
    id          INTEGER      PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version     UUID         NOT NULL DEFAULT gen_random_uuid(),
    status      TEXT         NOT NULL DEFAULT 'READY'
                    CHECK (status IN ('PUBLISHING','READY','FAILED')),
    source_mode TEXT
                    CHECK (source_mode IN ('sharadar','mock','frozen')),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    note        TEXT
);
ALTER TABLE bt_data_version
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'READY',
    ADD COLUMN IF NOT EXISTS source_mode TEXT;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_bt_data_version_status')
    THEN ALTER TABLE bt_data_version ADD CONSTRAINT ck_bt_data_version_status
        CHECK (status IN ('PUBLISHING','READY','FAILED')); END IF; END $$;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_bt_data_version_source_mode')
    THEN ALTER TABLE bt_data_version ADD CONSTRAINT ck_bt_data_version_source_mode
        CHECK (source_mode IN ('sharadar','mock','frozen')); END IF; END $$;
INSERT INTO bt_data_version (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Point-in-time quarterly EPS, the raw material for reproducing the
-- earnings-surprise (PEAD) factor. POPULATED BUT NOT YET CONSUMED: Sharadar has
-- no analyst estimates, so live's analyst-based SUE cannot be computed from it.
-- `estimated_eps` is deliberately absent rather than fabricated.
--   fiscal_date_ending = SF1 calendardate (the period described)
--   reported_date      = SF1 datekey      (when it became PUBLIC — the
--                        no-look-ahead key, same value as bt_fundamentals.as_of_date)
CREATE TABLE IF NOT EXISTS bt_earnings (
    ticker             VARCHAR(20)  NOT NULL,
    fiscal_date_ending DATE         NOT NULL,
    reported_date      DATE         NOT NULL,
    reported_eps       NUMERIC(24,6),
    PRIMARY KEY (ticker, fiscal_date_ending, reported_date)
);
CREATE INDEX IF NOT EXISTS idx_bt_earnings_reported ON bt_earnings(reported_date);
DO $$
BEGIN
    IF (SELECT array_length(conkey, 1) FROM pg_constraint
          WHERE conrelid = 'bt_earnings'::regclass AND contype = 'p') = 2
    THEN ALTER TABLE bt_earnings DROP CONSTRAINT bt_earnings_pkey; END IF; END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_bt_earnings_vintage
    ON bt_earnings(ticker, fiscal_date_ending, reported_date);
-- Idempotent widen for pre-existing DBs (same-scale precision increase).
ALTER TABLE bt_fundamentals
    ALTER COLUMN pe_ratio TYPE NUMERIC(24,6),
    ALTER COLUMN pb_ratio TYPE NUMERIC(24,6),
    ALTER COLUMN roe TYPE NUMERIC(24,6),
    ALTER COLUMN debt_to_equity TYPE NUMERIC(24,6),
    ALTER COLUMN revenue_growth TYPE NUMERIC(24,6),
    ALTER COLUMN eps_growth TYPE NUMERIC(24,6);

-- Observed TICKERS securities-master snapshot. Membership and nullable fields
-- are authoritative only on snapshot_date; this is not by itself a historical
-- investable-universe reconstruction. Sharadar SEP includes delisted names, so
-- a backtest can still hold a name that later disappeared.
CREATE TABLE IF NOT EXISTS bt_universe (
    snapshot_date   DATE         NOT NULL,
    ticker          VARCHAR(20)  NOT NULL,
    name            VARCHAR(200),
    sector          VARCHAR(100),
    exchange        TEXT,
    -- Vendor listing interval (2026-07). Sharadar TICKERS carries these and
    -- map_tickers_row discarded them. A later observation may use the interval
    -- to resolve historical ticker/permaticker identity; decision eligibility
    -- additionally requires the TICKERS observation for that exact session.
    --
    -- HONEST LIMIT: TICKERS is CURRENT-STATE metadata with historical DATE
    -- columns. The dates are point-in-time; `sector` is NOT — it is today's
    -- classification, and stays in the simulator's caveats.
    first_price_date DATE,
    last_price_date  DATE,
    is_delisted      BOOLEAN,
    PRIMARY KEY (snapshot_date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_bt_universe_date ON bt_universe(snapshot_date);
ALTER TABLE bt_universe
    ADD COLUMN IF NOT EXISTS first_price_date DATE,
    ADD COLUMN IF NOT EXISTS last_price_date  DATE,
    ADD COLUMN IF NOT EXISTS is_delisted      BOOLEAN;

-- Wealth Core v1 needs three TICKERS fields the mapper previously discarded:
-- `category` decides common-equity membership from its RAW string.
-- `permaticker` is permanent SECURITY identity; issuer-family grouping is a
-- separate construction from contemporaneous `related_tickers`. Idempotent
-- adds, so an existing bt-postgres picks them up on
-- bt-data startup; they stay NULL until TICKERS is re-fetched.
--
-- POSITION MATTERS: this must sit AFTER the CREATE TABLE above. It was first
-- written ~60 lines earlier, before bt_universe exists, so on a FRESH database
-- it failed — and because the whole file ran in one transaction, that single
-- failure rolled back every other statement in it, including an unrelated
-- ALTER on bt_prices.
ALTER TABLE bt_universe
    ADD COLUMN IF NOT EXISTS category        TEXT,
    ADD COLUMN IF NOT EXISTS permaticker     TEXT,
    ADD COLUMN IF NOT EXISTS related_tickers TEXT,
    ADD COLUMN IF NOT EXISTS exchange        TEXT,
    -- TRUE only when the source row contained every nullable decision field
    -- before normalization. Existing rows default FALSE: SQL NULL alone cannot
    -- distinguish authoritative empty from an incomplete legacy delivery.
    ADD COLUMN IF NOT EXISTS decision_metadata_complete BOOLEAN NOT NULL
        DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_bt_universe_window
    ON bt_universe(first_price_date, last_price_date);

-- IDENTITY MIGRATION (2026-08-08): the key becomes (snapshot_date, permaticker).
--
-- THE DEFECT. `permaticker` was added as a COLUMN without changing the KEY, so
-- the table could not represent the thing that column exists to express. Sharadar
-- TICKERS returns a separate row per permanent security, and a REUSED symbol
-- means two companies with the same `ticker` in one snapshot: they collided on
-- (snapshot_date, ticker) and the last row processed silently overwrote the
-- other. WHICH company survived depended on the order the API returned rows in.
--
-- Observed: ticker BIOT carried BIOTECH ACQUISITION CO (a SPAC, delisted, priced
-- 2021-01-26..2023-02-02) and INSTINCT BIO TECHNICAL CO INC (listed 2026-07-24).
-- The SPAC's row lost its permaticker, `_META_SQL`/`_IDENTITY_SQL` filter
-- `permaticker IS NOT NULL`, so the resolver saw ONE owner for the symbol, SKIPPED
-- the listing-window check by design, and attributed three years of SPAC prices
-- to the 2026 ADR. See docs/data-sources.md "Defect A".
--
-- `ticker` stays an ATTRIBUTE and a lookup key. It is not identity and must never
-- be unique within a snapshot again — that uniqueness WAS the bug.
--
-- NULL permatickers are LEFT ALONE rather than deleted. A plain (non-partial)
-- unique index treats NULLs as distinct, so legacy rows predating the column
-- coexist untouched; the WRITER rejects and counts them going forward. Deleting
-- them would gut the latest snapshot for the three readers that select
-- `WHERE snapshot_date = (SELECT MAX(snapshot_date) ...)` in the window between
-- this migration and the universe rebuild.
--
-- ORDER IS LOAD-BEARING, and so is the absence of a DO block with RAISE.
-- `_ensure_schema` splits this file on ";\n" and runs each statement in its OWN
-- transaction, reporting failures individually without aborting startup. That is
-- exactly the behaviour wanted here: if duplicate (snapshot_date, permaticker)
-- pairs exist, the CREATE UNIQUE INDEX below FAILS and says so on every boot,
-- the old primary key is left in place by the guarded drop that follows, and
-- bt-data still serves — which matters because bt-data is the service that runs
-- the universe rebuild that would repair it. A fatal migration here would
-- crash-loop the only thing able to fix the problem it is complaining about.
CREATE UNIQUE INDEX IF NOT EXISTS uq_bt_universe_snapshot_permaticker
    ON bt_universe (snapshot_date, permaticker);

-- Drop the ticker primary key ONLY once the identity index actually exists, so a
-- failed index creation can never leave the table with no uniqueness at all.
-- Written with its tail on one line because of the ";\n" split described above.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes
                WHERE tablename = 'bt_universe'
                  AND indexname = 'uq_bt_universe_snapshot_permaticker')
    THEN ALTER TABLE bt_universe DROP CONSTRAINT IF EXISTS bt_universe_pkey; END IF; END $$;

-- Ticker is now a LOOKUP key, deliberately NON-unique: two companies may share
-- one symbol within a snapshot, which is precisely what the old primary key made
-- unrepresentable.
CREATE INDEX IF NOT EXISTS idx_bt_universe_snapshot_ticker
    ON bt_universe (snapshot_date, ticker);

-- SHARADAR/ACTIONS — the AUTHORITATIVE corporate-action stream.
--
-- Until this existed the backtester DERIVED split ratios from the divergence
-- between SEP.close and SEP.closeunadj, and modelled no terminal action at all.
-- That was a reasonable use of data already present, and it cannot support a
-- certified claim: it can only see events the vendor's own adjustment made
-- visible, and it says nothing about WHY a security stopped printing.
--
-- EVERY action type is stored, not only the ones consumed today. `dividend` and
-- `ticker_change` are ingested here so wiring them later is a replay-side
-- change rather than a second multi-hour ingest against the same table.
--
-- `value` and `contraticker` carry the economics and they are frequently NULL:
-- a delisting with no terms is the ordinary case, not an error. Nothing in this
-- table may be interpreted as a zero — see docs/wealth-core-v1.md, "a delisting
-- is NOT a write-off". Absence of terms BLOCKS; only a stated zero writes off.
--
-- No natural primary key: a ticker can legitimately carry two actions of
-- different kinds on one date (a merger closing and the delisting that follows
-- it), and a re-fetch must not duplicate them. (ticker, date, action) is the
-- key, which collapses the pathological case of the same action twice on a day
-- while keeping the legitimate one.
CREATE TABLE IF NOT EXISTS bt_actions (
    ticker          VARCHAR(20)  NOT NULL,
    date            DATE         NOT NULL,
    action          TEXT         NOT NULL,
    name            TEXT,
    value           NUMERIC(20,6),
    contraticker    VARCHAR(20),
    contraname      TEXT,
    PRIMARY KEY (ticker, date, action)
);
CREATE INDEX IF NOT EXISTS idx_bt_actions_date   ON bt_actions(date);
CREATE INDEX IF NOT EXISTS idx_bt_actions_action ON bt_actions(action, date);

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
    error_message   TEXT,
    source_mode     TEXT CHECK (source_mode IN ('sharadar','mock','frozen'))
);
ALTER TABLE bt_data_runs ADD COLUMN IF NOT EXISTS source_mode TEXT;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_bt_data_runs_source_mode')
    THEN ALTER TABLE bt_data_runs ADD CONSTRAINT ck_bt_data_runs_source_mode
        CHECK (source_mode IN ('sharadar','mock','frozen')); END IF; END $$;

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
-- Live progress for the RUNNING config (a single-config experiment only moves
-- n_done 0->1, which is no progress at all): fine-grained pct plus interim
-- stats (return so far, drawdown, trades) so a multi-hour run is informative
-- while it runs. Idempotent for existing DBs.
ALTER TABLE bt_sweeps ADD COLUMN IF NOT EXISTS progress_pct INTEGER;
ALTER TABLE bt_sweeps ADD COLUMN IF NOT EXISTS live_stats JSONB;

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

-- Per-session equity for SWEEP legs. bt_equity cannot serve this: its run_id
-- REFERENCES bt_runs, and sweep legs deliberately do not write that table.
--
-- Why it exists at all: until now a sweep persisted only SUMMARIES, so the shape
-- of a run was unrecoverable the moment it finished. The dashboard's live_stats
-- is transient telemetry, overwritten each poll and gone at completion. That made
-- a real observation — "the book tracked SPY and then collapsed in the final
-- month, in every config" — impossible to confirm or dismiss after the fact. A
-- wind tunnel that decides what goes live should not be returning an exit code
-- and throwing away the execution.
--
-- Volume is modest: ~750 sessions x 2 windows per config, four numbers each.
-- phase is 'tune' | 'validate' so the two spans stay separable without a join.
CREATE TABLE IF NOT EXISTS bt_sweep_equity (
    sweep_id        UUID         NOT NULL REFERENCES bt_sweeps(sweep_id) ON DELETE CASCADE,
    config_idx      INTEGER      NOT NULL,
    window_idx      INTEGER      NOT NULL DEFAULT 0,
    phase           VARCHAR(10)  NOT NULL CHECK (phase IN ('tune','validate')),
    date            DATE         NOT NULL,
    portfolio_value NUMERIC(18,2) NOT NULL,
    spy_value       NUMERIC(18,2),
    drawdown        NUMERIC(10,6),
    PRIMARY KEY (sweep_id, config_idx, window_idx, phase, date)
);
-- The read this exists for: one config's curve, in order.
CREATE INDEX IF NOT EXISTS idx_bt_sweep_equity_cfg
    ON bt_sweep_equity (sweep_id, config_idx, phase, date);

-- Every fill for SWEEP legs, with its REASON. The equity curve says WHEN a
-- candidate diverged; this says WHY — a wave of "delisted — exited at 70% of last
-- available price" and an ordinary drawdown look identical in the curve alone, and
-- the first is an artifact of delist_recovery_pct while the second is the strategy.
--
-- No natural key (a ticker can legitimately trade twice on a date), so idempotency
-- comes from the writer deleting the leg's rows before inserting rather than from
-- ON CONFLICT. reason is what makes this worth storing at all: it carries the
-- mechanism that produced the fill (orphan exit, trailing stop, delist sweep,
-- drift trim), which is the attribution the summaries cannot express.
CREATE TABLE IF NOT EXISTS bt_sweep_trades (
    sweep_id        UUID         NOT NULL REFERENCES bt_sweeps(sweep_id) ON DELETE CASCADE,
    config_idx      INTEGER      NOT NULL,
    window_idx      INTEGER      NOT NULL DEFAULT 0,
    phase           VARCHAR(10)  NOT NULL CHECK (phase IN ('tune','validate')),
    date            DATE         NOT NULL,
    ticker          VARCHAR(20)  NOT NULL,
    action          VARCHAR(12)  NOT NULL,
    qty             NUMERIC(18,6) NOT NULL,
    price           NUMERIC(16,6) NOT NULL,
    tx_cost         NUMERIC(16,4) NOT NULL DEFAULT 0,
    reason          TEXT
);
CREATE INDEX IF NOT EXISTS idx_bt_sweep_trades_cfg
    ON bt_sweep_trades (sweep_id, config_idx, phase, date);

-- What the book HELD on each rebalance date, for SWEEP legs. Trades say what
-- changed; positions say what was actually owned, which is the only way to see
-- breadth (how many names) and deployment (how much capital) over time. The
-- 35-names-drifting-to-26 defect was invisible in both the summary and the
-- trade log, and obvious here.
CREATE TABLE IF NOT EXISTS bt_sweep_positions (
    sweep_id        UUID         NOT NULL REFERENCES bt_sweeps(sweep_id) ON DELETE CASCADE,
    config_idx      INTEGER      NOT NULL,
    window_idx      INTEGER      NOT NULL DEFAULT 0,
    phase           VARCHAR(10)  NOT NULL CHECK (phase IN ('tune','validate')),
    date            DATE         NOT NULL,
    ticker          VARCHAR(20)  NOT NULL,
    qty             NUMERIC(18,6) NOT NULL,
    weight          NUMERIC(10,6),
    market_value    NUMERIC(18,2),
    PRIMARY KEY (sweep_id, config_idx, window_idx, phase, date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_bt_sweep_positions_cfg
    ON bt_sweep_positions (sweep_id, config_idx, phase, date);

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

-- The ranked universe per rebalance — what the model SAW, not only what it held.
--
-- Every other bt_sweep_* table records what the book DID. None of them can answer
-- "what did we pass over, and how did it do?", which is the question behind
-- growth-capture, oracle recall and paired regret. forest_map has been declaring
-- that gap in its own `missing` field since it was written: "growth_capture:
-- needs the ranked universe per date — not derivable from a run's own trace".
--
-- DELIBERATELY CAPPED, not the whole universe. A 20-year run over ~2000 names at
-- daily cadence would be ~10M rows per config, which is a corpus, not a
-- diagnostic. `rank_cap` rows per date covers the decision-relevant head: the
-- selected book plus the near-misses that any regret analysis compares against.
-- The cap is RECORDED on bt_sweeps so a later reader knows whether an absent
-- ticker was ranked-and-passed-over or simply beyond the cap — an ambiguity that
-- would silently corrupt exactly the recall numbers this table exists to compute.
--
-- `selected` and `reject_reason` are what make this more than a rank dump: they
-- separate "the model ranked it low" from "the model ranked it high and the
-- builder refused it", which are different failures with different fixes.
CREATE TABLE IF NOT EXISTS bt_sweep_rankings (
    sweep_id        UUID         NOT NULL REFERENCES bt_sweeps(sweep_id) ON DELETE CASCADE,
    config_idx      INTEGER      NOT NULL,
    window_idx      INTEGER      NOT NULL DEFAULT 0,
    phase           VARCHAR(10)  NOT NULL CHECK (phase IN ('tune','validate')),
    date            DATE         NOT NULL,
    ticker          VARCHAR(20)  NOT NULL,
    rank            INTEGER      NOT NULL,
    composite_score NUMERIC(12,6),
    selected        BOOLEAN      NOT NULL DEFAULT FALSE,
    weight          NUMERIC(10,6),
    reject_reason   VARCHAR(32),
    PRIMARY KEY (sweep_id, config_idx, window_idx, phase, date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_bt_sweep_rankings_cfg
    ON bt_sweep_rankings (sweep_id, config_idx, phase, date);
-- The growth-capture read: "the names we passed over, best-ranked first".
CREATE INDEX IF NOT EXISTS idx_bt_sweep_rankings_passed
    ON bt_sweep_rankings (sweep_id, config_idx, phase, date, rank)
    WHERE NOT selected;

ALTER TABLE bt_sweeps ADD COLUMN IF NOT EXISTS ranking_rank_cap INTEGER;
