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
Mandatory chain step — exclusions are binding (gate, not a hint)

Vetter exclusions are binding. The vetter is a mandatory step in the daily
chain: the scheduler marks it optional=False, so if the vetter fails the whole
chain halts and the portfolio is never built without today's exclusions applied.
portfolio-builder reads vetter_exclusions and removes those tickers from the
candidate pool before construction. The vetter does NOT apply positive-conviction
score boosts — the deterministic ranker owns the final score and the vetter only
excludes.

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

VetterConfig fields: enabled, candidate_count, risk_horizon_days,
  system_prompt_file, strictness, max_searches_per_ticker,
  news_lookback_days, max_articles_per_ticker, earnings_horizon_days

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
  reads GET /v2/account, GET /v2/positions, GET /v2/orders from Alpaca (read-only)
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
  market orders; time_in_force = "day" for ALL orders (both immediate and
    scheduled modes) — mode is audit-only, kept on alpaca_orders but does not
    change the order type. Day orders queue 24/7 for the next session; this
    replaced the earlier "opg" path which expired without an opening auction print
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

## Phase 7: Scheduler, Pipeline Consolidation, Alembic ✅ DONE

Built:

```text
scheduler service (port 8015)
Non-blocking supervisor state machine — each tick reads /runs/latest from each
service, triggers the first idle step, and returns. Chain advances on the next
tick. After today's chain reaches terminal state (success/failed), further
ticks are no-ops until the calendar date rolls over.
Daily chain reduced to 3 steps: fetch-data → pipeline → vet (optional).
RANK_SCHEDULE_CRON env var overrides the default schedule.

Pipeline consolidation:
  factor-engine + ranker + delta-engine merged into a single `pipeline` service
  (port 8018). Math modules copied verbatim into services/pipeline/app/
  {factors,rank,engine,regime}.py — no behaviour change. Single _job_lock is
  held end-to-end (acquired in _do_run_pipeline, released in
  _run_pipeline_steps's finally block) so a duplicate trigger sees
  {"status":"already_running"} for the entire duration of a run. chain_date
  is written at row creation so the supervisor's _step_state sees a valid date.

Redis Streams trigger:
  av-ingestor publishes {event: "fetch_data.complete", run_date, run_id} to
  stream `stocker:pipeline_events`. Pipeline consumer group
  `pipeline-consumers` auto-triggers a run on receipt, so a manual fetch-data
  fires factors→rank→delta without scheduler involvement. xack is always
  called in finally so a failed run doesn't get re-delivered.

Alembic migrations:
  db/migrations/versions/0001_initial_schema.py — all initial tables
  db/migrations/versions/0002_pipeline_runs.py — pipeline_runs audit table
  db-migrator service runs `alembic upgrade head` once before any app
  service starts; every app service has
  depends_on: db-migrator: service_completed_successfully.

delta_intents persistence:
  Only actionable rows are written — entry / exit / hold always, plus watches
  whose confirmation_days_met >= confirmation_days (i.e. "would enter if
  capacity opens"). Non-confirmed watches are skipped to keep the
  trade-proposal UI focused on current holdings + proposed buys.
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

## Phase 7.1: Infrastructure Hardening (Synology NAS deployment) ✅ DONE

Bugs found and fixed during first real deployment on a Synology NAS:

```text
Docker startup tier chain:
  postgres/redis (T1) → api (T2) → av-ingestor/risk-service (T3)
    → pipeline/alpaca-sync/portfolio-builder/llm-vetter/backtester (T4)
    → trade-executor/scheduler/dashboard (T5)
  prevents TCP SYN stampede on cold NAS boot

Healthcheck IPv6 fix:
  Synology has IPv6 disabled; Python resolves "localhost" to ::1 → ENETUNREACH
  Fixed: all healthchecks replaced "localhost" with "127.0.0.1"

Postgres cold-boot timeout:
  pg_isready passes before init.sql finishes — the default 10×5s=50s window was
  too short on NAS storage. Fixed: start_period=120s, retries=20 added.

Pipeline FK violation (every run crashed):
  pipeline_runs and child tables (factor_runs, ranking_runs, delta_runs) were
  inserted BEFORE execution_traces, violating FK constraints. Fixed: execution_traces
  is now always inserted first in all five affected locations.

Kill switch hot-flip:
  os.getenv() reads the frozen process environment; docker exec -e cannot change it.
  Fixed: /tmp/kill_switch control file. File takes precedence over env var.
  docker exec stocker-risk-service-1 touch /tmp/kill_switch  (ON)
  docker exec stocker-risk-service-1 rm    /tmp/kill_switch  (OFF)

Orphan broker positions:
  Positions in live_positions but not in portfolio_holdings were invisible to the
  delta engine and would never receive an exit signal. Fixed: pipeline loads latest
  live_positions before delta evaluation and adds unknown tickers to current_portfolio
  with weight=0.0, causing the existing missing_from_universe force-exit path to
  emit an exit intent.

Dashboard /rankings/with-overlays route missing:
  Dashboard JS fetched /api/rankings/with-overlays but no proxy route existed.
  Fixed: added route to both api service and dashboard proxy layer. SQL also
  updated to JOIN universe_tickers so company name and sector are returned.

Trade idempotency includes risk_rejected:
  Previously only pending/submitted were in the idempotency guard; a risk_rejected
  order could be re-submitted indefinitely. Fixed: risk_rejected added to the list.

Failed orders reported as success:
  HTTP 200 body with status='failed' (no Alpaca credentials) bypassed all JS error
  checks and displayed "Market order sent". Fixed: JS now checks body.status explicitly.
```

## Phase 7.2: Option B — portfolio-builder in scheduler chain; delta uses target-vs-live diff mode ✅ DONE

**Problem:** On cold boot with zero history, the delta engine required `confirmation_days`
consecutive ranking days before generating entry intents. With an empty portfolio and a fresh
ranking run, 0 entry intents were produced even after ranking 2000 tickers.

**Solution (Option B):**

```text
Scheduler chain extended from 3 steps to 5 (current ordering):
  fetch-data → pipeline → vet → portfolio-builder → delta(standalone)

vet runs BEFORE portfolio-builder so the same-cycle exclusions can feed the
build via vetter_decisions/vetter_exclusions. portfolio-builder auto-selects
the latest matching vetter_run by source_ranking_run_id; the scheduler does
not pass vetter_run_id explicitly.

Delta now has two modes:
  target_vs_live (default, when portfolio_holdings exists):
    entry  — ticker in portfolio_holdings but not held at broker
    exit   — ticker held at broker but not in portfolio_holdings
    hold   — ticker in both
    watch  — confirmed entry-zone but not yet in portfolio (pending portfolio-builder)
  confirmation_days_fallback (cold start, before first portfolio-builder run):
    same as legacy evaluate_all() mode

New pipeline endpoints:
  POST /jobs/delta      — standalone delta only (triggered_by='scheduler')
  GET  /runs/delta-latest — most recent delta_run WHERE triggered_by='scheduler'
    (so scheduler tracks standalone delta independently from pipeline's delta)

New delta_runs column:
  triggered_by TEXT NOT NULL DEFAULT 'pipeline'
    migration: db/migrations/versions/0003_delta_triggered_by.py

_StepDef.status_path field added to scheduler:
  default: /runs/latest
  delta step uses: /runs/delta-latest
  prevents scheduler from reading the pipeline's delta run as "the standalone delta"

portfolio-builder step is NOT optional — delta after it needs a fresh target portfolio.

Entry intents carry current_weight = target weight from portfolio_holdings.
trade-executor uses this for order sizing: floor(account_value × weight / price).
```

Changes:
```text
services/pipeline/app/engine.py   — evaluate_target_vs_live() function
services/pipeline/app/main.py     — _do_delta_step(triggered_by), /jobs/delta, /runs/delta-latest
services/scheduler/app/main.py    — status_path field on _StepDef; updated _STEPS (5 steps)
services/dashboard/app/main.py    — delta job path updated to /jobs/delta
db/migrations/versions/0003_delta_triggered_by.py  — triggered_by column
tests/delta_engine/test_engine.py — 11 new tests for evaluate_target_vs_live
docs/architecture.md              — 5-step daily chain
docs/service-boundaries.md        — pipeline, portfolio-builder, scheduler sections updated
docs/build-phases.md              — this entry
```

## Phase 8: Live Trading Readiness

Only after paper trading review:

```text
live mode flag
human approval workflow
kill switch
production credentials handling
deployment checklist
```
