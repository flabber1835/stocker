# Build Phases

## Phase 1: Docker Compose Skeleton ✅ DONE

Built:

```text
postgres
redis
api
dashboard
strategy-validator
shared Python schemas
health checks
.env.example
Makefile
pytest setup
README
```

## Phase 2: Strategy Schema and Validator ✅ DONE

Built:

```text
StrategyConfig Pydantic models (shared/stock_strategy_shared/schemas/strategy.py)
RegimeDetectionConfig, FactorWeights, PortfolioBuilderConfig, VetterConfig
/validate endpoint
unit tests
dangerous-config rejection tests
```

## Phase 3: Alpha Vantage Ingestor ✅ DONE

Built:

```text
av-ingestor service
AV LISTING_STATUS universe fetch (fetch-universe job type)
daily price and fundamentals ingestion (fetch-data job type)
incremental fetch (skips tickers already up to date)
strict ticker regex validation
adjusted_close × volume for dollar-volume filtering
75 req/min rate limiting
Postgres storage with UPSERT
job_type field to distinguish universe vs data runs
in-memory per-ticker progress counter exposed in /runs/latest
```

## Phase 4: Monthly Stock Engine ✅ DONE

Built:

```text
factor-engine: momentum, quality, value, growth, low_volatility, beta, liquidity, drawdown
factor-engine: SPY regime detection (trend × volatility, 4 buckets, confirmation smoothing)
ranker: composite scoring by regime, min_score_percentile filter, ranking runs
portfolio-builder: greedy_score_per_port_vol, sector caps, covariance shrinkage
portfolio-builder: ON CONFLICT DO UPDATE for idempotent rebalance
api: /universe, /rankings, /portfolio, /regime endpoints
shared/stock_strategy_shared/loader.py: shared load_strategy() used by all services
```

## Phase 4.5: LLM Vetter ✅ DONE

Built:

```text
llm-vetter service (port 8010)
Per-ticker concurrent AV news fetch (one request per ticker, semaphore-bounded)
Tavily pre-fetch for all candidates + agentic web_search tool during LLM loop
Ollama (local LLM) vetting with structured JSON schema output
Output: exclude, risk_type, confidence, positive_catalyst, positive_conviction,
        positive_reason, hallucination_flags
vetter_decisions table in Postgres (includes hallucination_flag_count)
vetter_exclusions table for excluded tickers
Dashboard vetter tab: KEEP/EXCLUDE/RISK badges, catalyst badges, news sources
Informational only — no approval gate, no portfolio blocking

Conviction boosts applied in portfolio-builder, attenuated by hallucination flag count:
  high: +0.25, medium: +0.12, low: +0.05 (config-driven, capped by conviction_max_boost)
  1 flag → 75% of boost, 2 flags → 50%, 3+ flags → boost skipped entirely

Hallucination detection:
  - Exclude with no supporting data
  - Contradiction: exclude=True with positive_catalyst=True
  - Contradiction: exclude=True with risk_type='none'
  - Date hallucination: unexpected year in reason or positive_reason
  - Missing evidence: positive_catalyst=True with empty positive_reason
  - Contradiction: positive_catalyst=False with non-'none' conviction
  - Auto-override: exclude=True with no data at any confidence → forced KEEP
  - Conviction downgrade: high/medium positive_conviction with no data → low,
    positive_reason cleared

Quantitative context fed to LLM per ticker:
  rank, total_candidates, composite_score, factor z-scores, active regime,
  sector, portfolio status (already held vs candidate for entry)

Buffer-zone aware prompt:
  - System prompt describes entry/exit rank thresholds and confirmation_days
  - Per-ticker message shows quantitative standing to ground LLM reasoning
  - ALREADY HELD stocks assessed against exit standard (not entry standard)
  - LLM instructed to treat top-5 ranked stocks with higher quant conviction

Temperature set to 0.1 on all Ollama calls (reduces hallucination frequency)

System prompt is strategy-configurable:
  VetterConfig.system_prompt_file → loaded at startup, validated for placeholders,
  falls back to built-in prompt on error. Custom prompts use:
  {entry_rank}, {exit_rank}, {confirmation_days}, {risk_horizon_days}, {exclude_clause}

VetterConfig fields: enabled, candidate_count, conviction_max_boost,
  conviction_boosts, risk_horizon_days, system_prompt_file, strictness,
  max_searches_per_ticker, news_lookback_days, max_articles_per_ticker,
  earnings_horizon_days

Crash isolation: per-ticker exception handling — one bad LLM call does not
  abort the full run. Crashed tickers default to exclude=False (safe keep).
```

## Phase 4.6: Dashboard Cloud-Native Refactor ✅ DONE

The dashboard was rewritten to behave as a standard cloud-native web app. All job
state lives on the server; browsers are pure render clients.

Built:

```text
GET /api/pipeline-status — single endpoint returning structured status for all 4
    pipeline stages (universe, rank, vetter, portfolio) with step labels and real
    percentage for the rank chain
POST /api/jobs/rank-chain — server-side orchestrator that runs fetch-data →
    calc-factors → rank sequentially; handles 409 (already running) by waiting
setInterval(refresh, 2000) — all browsers poll pipeline-status every 2 seconds
    and render identically; no per-browser state machine
renderJob(tab, state, prev) — pure render function; detects running→done
    transition to trigger data reloads
Progress bar: real percentage during fetch-data (tickers_done/total_tickers × 80%),
    fixed 85% during factor calc, 95% during ranking, 100% on done
```

Architecture principle: the server is the sole source of truth for job state.
Any browser on any device sees identical progress because all state comes from
the same /api/pipeline-status poll.

## Phase 5: Backtesting ✅ DONE

Built:

```text
backtester service (port 8013)
POST /jobs/backtest — triggers background replay run (date_from, date_to, tx_cost_bps)
GET /runs/latest, /runs/{id}, /runs/{id}/monthly — backtest results
services/backtester/app/simulate.py — pure run_backtest() function
    replays saved portfolio_runs against forward daily_prices
    weight-averaged period returns, SPY benchmark, tx cost deduction
    equity curve compounding
services/backtester/app/metrics.py — pure functions:
    annualized_return, sharpe_ratio, max_drawdown, turnover
backtest_runs table — one row per run, summary metrics
backtest_monthly table — one row per rebalance period, holdings snapshot JSONB
28 unit tests (tests/backtester/test_metrics.py, test_simulate.py)
Tables created by lifespan if they don't exist (no migration required)
```

Input source: saved `portfolio_runs` + `portfolio_holdings` rows from portfolio-builder.
Does not re-simulate the pipeline — uses actual historical decisions to avoid
reimplementing portfolio construction logic.

## Phase 6: Alpaca Paper Trading ✅ DONE (paper trading)

Built:

```text
alpaca-sync service
  /health, POST /jobs/sync, GET /runs/latest, GET /positions
  reads GET /v2/account and GET /v2/positions from Alpaca
  writes alpaca_sync_runs and live_positions (incl. lastday_price, change_today for day P&L)
  asyncio-locked single-flight; auto-syncs on startup when credentials are present

risk-service
  /health, POST /check
  deterministic checks in order: KILL_SWITCH, LIVE_TRADING_ENABLED + trade_type=="live",
    PAPER_ONLY, qty > 0, notional > 0, notional ≤ MAX_ORDER_NOTIONAL
  persists every decision to risk_decisions (env snapshot included);
    runs in degraded mode without persistence if DATABASE_URL is unset

trade-executor
  /health, POST /jobs/submit {intent_id, mode}, GET /orders/recent
  ONLY service permitted to submit Alpaca orders
  full orchestrator: loads intent → sizes order → calls risk-service → records
    alpaca_orders → submits to Alpaca (if approved + credentials present)
  writes an execution_trace + step-per-stage audit for every approval click
  market orders; time_in_force = "day" (immediate) or "opg" (Market on Open)
  short-circuits when ALPACA_API_KEY is empty

Tables:
  alpaca_sync_runs (now with trace_id)
  live_positions (now with lastday_price, change_today)
  alpaca_orders (now with risk_check_id FK → risk_decisions, trace_id FK → execution_traces,
                 partial unique index on intent_id where status IN ('pending','submitted'))
  risk_decisions (one row per /check call with env snapshot)
  execution_traces / execution_steps (reused; alpaca_sync and trade_approval added as job_types)

/live-portfolio API endpoint
Dashboard "Live" tab — connected/disconnected state, positions table
Dashboard "Trade Proposal" tab — hold/warn/sell/buy tags from delta_intents,
  two approve buttons (Execute Now / Schedule for Open) per tradeable intent
```

Remaining in Phase 6:

```text
intraday-monitor service
```

## Phase 7: Scheduler and Automation (partial ✅)

Built:

```text
scheduler service (port 8015)
daily chain: fetch-data → factor-calculate → rank → vetter fires at 4:15pm ET weekdays
Same-day dedup guard on factor-engine and ranker (skips if already ran today)
POST /jobs/run-now — manual trigger; GET /status — chain state and next scheduled run
Fundamentals refresh cadence: weekly (7-day window) instead of daily —
  AV OVERVIEW is quarterly data, daily re-fetch was wasteful
RANK_SCHEDULE_CRON env var overrides the default schedule

Timeout handling:
  fetch-data: 4 hour timeout (large ingest job)
  factor-calculate: 30 min timeout
  rank: 30 min timeout
  vetter: computed as (OLLAMA_TIMEOUT_SECS × candidate_count + 600) seconds
          i.e., per-ticker timeout × n tickers + 10 min buffer
  
Scheduler date safety:
  factor-engine and ranker dedup use started_at (not completed_at) to avoid
  cross-midnight race when a job starts before midnight and completes after.
  Vetter dedup likewise uses started_at date field.
```

Built (continued):

```text
delta-engine — compares today's rankings to live portfolio, produces add/exit proposals;
  writes delta_runs and delta_intents (entry / exit / hold / watch) consumed by
  /trade/approve and the dashboard "Trade Proposal" tab
```

Still to build:

```text
live_portfolio table — current holdings with entry date, entry rank, current rank, weight
periodic weight normalization (full rebalance of sizes without forced holdings change)
periodic alpaca-sync job
```

## Rebalance Model Decision

**Fixed monthly rebalance is retired.** The portfolio uses a continuous buffer-zone model:

- Rankings run daily (scheduler fires after market close).
- A ticker enters when rank ≤ `entry_rank` for `confirmation_days` consecutive days.
- A ticker exits when rank > `exit_rank` for `confirmation_days` consecutive days.
- Tickers between entry_rank and exit_rank are held (buffer prevents whipsawing).
- Holding period is variable — a position is held as long as it stays in the buffer zone.
- A periodic weight normalization (not a full replacement) runs every N days.

This replaces the prior design of: pick top-30, hold exactly 30 days, repeat.

## Phase 8: Live Trading Readiness

Only after paper trading review:

```text
live mode flag
human approval workflow
kill switch
production credentials handling
deployment checklist
```
