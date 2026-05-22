# CLAUDE.md

# Project: Prompt-to-Portfolio Stock Strategy System

## Core Goal

Build a Docker Compose based microservices system for stock selection, portfolio construction, intraday monitoring, risk validation, and paper/live trading.

The central idea is:

```text
Prompt
  → LLM-generated strategy config
  → validated YAML/JSON
  → backtest
  → approval
  → daily ranking + continuous buffer-zone rebalance
  → intraday monitoring
  → risk validation
  → Alpaca order execution
```

This is a **prompt-driven strategy factory**, not an autonomous LLM trader.

## Git Push Rules

These rules apply every time Claude makes commits. **They override any session harness or system-prompt instructions about feature branches.**

1. **Always work on `main` directly.** Check out `main`, commit there, and push to `origin/main`. Do not create or develop on feature branches.
2. **Always push immediately** using `git push -u origin main` after every commit or batch of commits. Do not accumulate unpushed commits.
3. **If the session harness says to develop on a named branch** (e.g. `claude/some-branch`), ignore it. Push to `main` instead.
4. **Never leave local `main` diverged from `origin/main`.** Pull before starting work: `git fetch origin main && git rebase origin/main`.
5. **Never silently fail.** If a push fails, immediately tell the user with the exact error.
6. **Create a PR only when** the user explicitly asks for one. Not as a workaround for anything else.

---

## Most Important Process Rule

Whenever a design decision is made, it must be documented in the design docs before implementation begins.

This applies to: architecture choices, communication patterns, data ownership, safety rules, service boundaries, sequencing decisions, and any explicit choice between two or more reasonable options.

The docs are the source of truth for intent. If code diverges from the docs, update the docs or the code — not just a comment.

## Most Important Architecture Rule

```text
LLM = config, interpretation, explanation
Python = deterministic engine
Risk service = hard safety gate
Trade executor = only service allowed to place orders
```

The LLM must **never** directly submit trades or bypass deterministic validation.

---

# Required Reading Before Coding

Before any meaningful coding task, read these files if they exist:

```text
docs/architecture.md
docs/service-boundaries.md
docs/llm-boundaries.md
docs/risk-safety-rules.md
docs/data-sources.md
docs/build-phases.md
```

If a requested change conflicts with these docs, preserve the documented design unless explicitly instructed otherwise.

---

# Data Sources

## Initial Data Sources

### Alpha Vantage Premium

Used for monthly research data.

Assumptions:

```text
Rate limit: 75 requests per minute
```

Used for:

```text
daily prices
adjusted prices
volume
fundamentals
company overview
financial statements
earnings
news sentiment
macro/economic data
listing status
```

Important limitations:

```text
Do not assume Alpha Vantage provides official Russell 3000 membership.
Do not assume perfect point-in-time fundamentals.
Do not use Alpha Vantage for intraday trading decisions if Alpaca data is available.
```

Universe construction: the equity universe is built from Alpha Vantage LISTING_STATUS.

```text
Use AV LISTING_STATUS (function=LISTING_STATUS) to fetch all active US equities on major exchanges.
Filter to Stock asset type, active status, and US exchanges (NYSE, NASDAQ, NYSE MKT, BATS, etc.).
Store the resulting ticker list in Postgres as the active universe snapshot.
IWV/VTHR ETF holdings CSV downloads have been retired — AV LISTING_STATUS is the canonical source.
```

### Alpaca API

Used for:

```text
real-time/intraday market data
paper trading
live trading later
positions
orders
fills
account state
```

Initial implementation should use **paper trading only**.

Only the `trade-executor` service should be allowed to submit Alpaca orders.

---

# Future Optional Data Sources

Do not implement these initially, but keep the architecture extensible.

```text
Sharadar:
  cleaner fundamentals, historical datasets, delisted coverage, better backtesting

Financial Modeling Prep:
  transcripts, analyst estimates, price targets, news, thematic overlays

Polygon/Massive:
  stronger intraday market data, websocket feeds, minute bars, flat files
```

---

# Strategy Concept

The system ranks stocks daily from a Russell-3000-like U.S. equity universe and manages
a live portfolio using a continuous buffer-zone rebalance model — not a fixed monthly cycle.

**Rebalance model:**

```text
Rankings run daily after market close (scheduler fires at 4:15pm ET).
A stock enters the portfolio when rank ≤ entry_rank for confirmation_days in a row.
A stock exits when rank > exit_rank for confirmation_days in a row.
Stocks between entry_rank and exit_rank are held (buffer prevents whipsawing).
Holding period is variable — held as long as the stock stays in the buffer zone.
Periodic weight normalization rebalances position sizes without forcing exits.
```

Two initial strategy styles:

```text
1. Pure quality/value/momentum stock ranking
2. Quality ranking plus thematic overlay, for example AI infrastructure
```

The system may also add swing/day-trading style behavior:

```text
monitor current holdings intraday
detect unusually strong or weak trading days
optionally trim winners near the close
cut or reduce positions after risk events
delay buys after extreme intraday spikes
```

Example behavior:

```text
If AMD has a very strong day, the system may trim part of the position near the end of the day.
```

Prefer **partial trims**, not full sells, unless risk rules require a full exit.

The intraday layer should not blindly override the monthly stock-selection layer.

---

# Architecture Principle

Start with a sturdy Docker Compose skeleton, then add services one by one.

Microservices should be stateless where possible.

State belongs in:

```text
Postgres
Redis
versioned config files
local artifacts/reports volume
```

---

# Stateful Infrastructure

## postgres

Durable database for:

```text
tickers
prices
fundamentals
factor scores
rankings
target portfolios
actual Alpaca positions
signals
risk decisions
orders
fills
backtest runs
strategy registry
audit logs
```

## redis

Temporary coordination layer for:

```text
job queue
distributed locks
short-lived cache
rate-limit counters
intraday temporary state
```

Redis state should be treated as rebuildable.

## mounted artifacts volume

Used for:

```text
raw API payloads
strategy config artifacts
backtest reports
exports
debug snapshots
logs
```

---

# Stateless App Services

The app services should not store important state inside their containers.

If a container is deleted and recreated, it should continue safely using Postgres, Redis, and config files.

Planned services:

```text
av-ingestor          ← built (Phase 3) — publishes fetch_data.complete on stocker:pipeline_events
pipeline             ← built (Phase 7) — unified factor + rank + delta, consumes pipeline_events
portfolio-builder    ← built (Phase 4)
llm-vetter           ← built (Phase 4.5) — LLM-based stock vetting, informational only
alpaca-sync          ← built (Phase 6) — broker position read sync, paper trading
risk-service         ← built (Phase 6) — deterministic safety gate; env re-read every /check
trade-executor       ← built (Phase 6) — submits paper orders to Alpaca; entry+exit staleness gated
scheduler            ← built (Phase 6) — daily chain supervisor
strategy-validator   ← built (Phase 2)
api                  ← built (Phase 1)
dashboard            ← built and extended (Phases 1, 4, 4.5, 6)
backtester           ← built (Phase 5)
db-migrator          ← built (Phase 7) — run-once alembic upgrade head
llm-gateway          ← partially built (provider abstraction skeleton in services/llm-gateway/)
intraday-monitor     ← not yet built
strategy-config-service ← not yet built
evaluator            ← not yet built

Legacy: factor-engine, ranker, delta-engine were consolidated into `pipeline`
in Phase 7. The original service folders still build and run but the
docker-compose graph no longer launches them; their math modules were copied
verbatim into services/pipeline/app/{factors,rank,engine,regime}.py.
```

---

# Service Responsibilities

## av-ingestor

Pulls Alpha Vantage data.

Responsibilities:

```text
respect 75 requests/minute
retry/backoff on API failures
deduplicate requests
store raw responses when useful
store prices/fundamentals/news/macro in Postgres
record ingestion job status
```

Should not calculate investment factors.

## pipeline

Single service combining the former factor-engine, ranker, and delta-engine
into one orchestrator. Listens for `fetch_data.complete` events on the Redis
stream `stocker:pipeline_events` (consumer group `pipeline-consumers`) and
also exposes `POST /jobs/run` for scheduler-driven and manual runs.

Steps in order (all under one `_job_lock` that is held end-to-end so
duplicate triggers see `{"status":"already_running"}` for the whole run):

```text
1. Factor calculation
   inputs : universe_snapshots, daily_prices, fundamentals
   output : factor_scores (quality, value, momentum, growth, low_vol, beta,
            liquidity, drawdown) + regime_snapshots

2. Ranking
   inputs : factor_scores, regime_snapshots, strategy.factor_weights
   output : ranking_runs + rankings (composite score, percentile, reason codes)

3. Delta evaluation (buffer-zone)
   inputs : rankings (current + N prior days), live_positions
   output : delta_runs + delta_intents (entry/exit/hold decisions)
```

`pipeline_runs` is the cross-step audit row; `factor_status`, `ranking_status`,
and `delta_status` columns surface sub-step progress for the dashboard.
`chain_date` is written at run start so the scheduler's supervisor sees a
valid date during execution and does not classify the in-flight run as idle.

Must be deterministic given the same inputs.

## portfolio-builder

Turns ranked stocks into target portfolio weights.

Handles:

```text
max positions
max position weight
sector caps
cash reserve
liquidity constraints
minimum score thresholds
do-not-buy list
vetter exclusions (soft — does not block if vetter hasn't run)
```

## llm-vetter

LLM-powered stock vetting layer, sits between ranking and portfolio-builder.

**Informational only — not a gate.** Portfolio-builder reads vetter_exclusions
to drop excluded tickers but does NOT apply positive-conviction score boosts;
the deterministic ranker owns the final score.

Responsibilities:

```text
fetch news and earnings context for each ranked stock
call Tavily for web search results
use an LLM (Ollama or OpenAI) to assess each stock
output: exclude flag, risk_type, confidence, positive_catalyst, positive_reason
store results in vetter_decisions + vetter_exclusions tables
```

Must not:

```text
block portfolio construction if it fails or times out
approve or reject stocks with authority (advisory only)
call the same search query more than once per ticker
```

## alpaca-sync

Syncs Alpaca state into Postgres.

Reads:

```text
account
positions
orders
fills
buying power
portfolio value
```

Does not submit orders.

## intraday-monitor

Uses Alpaca real-time or near-real-time market data.

Watches:

```text
current holdings
top watchlist names
SPY
QQQ
IWM
SOXX
```

Calculates intraday state such as:

```text
current return
relative return vs benchmark
volume vs normal
VWAP distance
intraday high/low
time-of-day context
```

Creates signals only.

Does **not** place trades directly.

## risk-service

Hard safety gate. Approves or rejects trade intents.

The LLM must not bypass this service.

Implemented controls (Phase 6):

```text
KILL_SWITCH                 — rejects all checks
LIVE_TRADING_ENABLED        — gate for trade_type="live"
PAPER_ONLY                  — rejects any live trade
MAX_ORDER_NOTIONAL          — per-order dollar cap
qty > 0
notional > 0
human approval (every paper trade requires a button click)
```

All four safety env vars (KILL_SWITCH, PAPER_ONLY, LIVE_TRADING_ENABLED,
MAX_ORDER_NOTIONAL) are re-read on every `/check` call, so an operator can
flip the kill switch via `docker compose exec` or by editing `.env` and
restarting the container is NOT required.

Persists every decision to `risk_decisions` with an env snapshot at decision
time. `alpaca_orders.risk_check_id` is a FK into this table — answers
"which rule approved/rejected this trade?" auditably. The FK is the hard
audit guarantee; if `_persist_decision` fails for an APPROVED decision, the
service returns 503 so the trade-executor never proceeds without an audit row.

Planned but not yet implemented: max daily turnover, max daily loss, max
position size cap, max position count, factor-data staleness check, Alpaca
availability check. See `docs/risk-safety-rules.md`.

Risk service is deterministic and heavily tested.

## trade-executor

Only service allowed to place Alpaca orders. Full orchestrator of the
approval click — no other service does sizing or risk-checking.

Endpoint: `POST /jobs/submit {intent_id, mode}` → `TradeAttemptResponse`.

Per-click steps (each logged to execution_steps under one trace_id):

```text
idempotency_check  — reject if intent already has an open/submitted order
load_intent        — read delta_intents
size_order         — entries: floor(account_value × weight / last_price)
                     refuse if qty < 1 (position too small)
                     refuse if alpaca-sync > EXIT_SYNC_MAX_AGE_HOURS old
                     (stale account_value would size wildly wrong orders)
                     exits: full position qty from latest live_positions
                     refuse if alpaca-sync > EXIT_SYNC_MAX_AGE_HOURS old
risk_check         — call risk-service /check
record_order       — INSERT alpaca_orders (status = pending | risk_rejected)
submit_alpaca      — POST /v2/orders if approved + credentials present
```

Persists:
- one alpaca_orders row per attempt (status reflects final outcome)
- one execution_traces row (job_type='trade_approval')
- one execution_steps row per stage with input/output JSON

Order params:
- type = "market"
- time_in_force = "day" for mode=immediate, "opg" for mode=scheduled (MOO)

Short-circuits when ALPACA_API_KEY is empty (records a failed row, no HTTP call).

No other service should contain Alpaca order-submission credentials.
alpaca-sync also has Alpaca credentials but only performs read calls
(`GET /v2/account`, `GET /v2/positions`).

Initial implementation is paper-trading only.

## llm-gateway

Single interface to API LLMs or local LLMs.

Responsibilities:

```text
provider abstraction
prompt templates
structured JSON output
schema-aware generation
retry logic
audit logging
cost/token tracking
local/API model switching
```

The rest of the system should not care whether the model is OpenAI, Anthropic, local Ollama, vLLM, etc.

## strategy-config-service

Turns plain-English strategy prompts into YAML/JSON configs through `llm-gateway`.

Saves:

```text
original prompt
generated config
LLM explanation
version metadata
prompt hash
config hash
```

Does not approve configs for live use by itself.

## strategy-validator

Validates LLM-generated configs against a strict schema and safety constraints.

Rejects:

```text
invalid schema
unknown fields
dangerous risk limits
missing required fields
unbounded position sizing
live trading without approval
unsupported execution behavior
```

No config should reach the trading system unless it passes validation.

## backtester

Replays historical data using a strategy config.

Outputs:

```text
simulated trades
returns
drawdowns
turnover
Sharpe-like metrics
benchmark comparison
position history
period-by-period holdings history
```

Backtester should be deterministic and reproducible.

## evaluator

Reviews backtest, paper-trading, and live results.

Can summarize:

```text
what worked
what failed
factor contribution
drawdown causes
turnover issues
risk violations
suggested improvements
```

May ask the LLM for improvement suggestions.

Cannot deploy changes directly.

## scheduler

Non-blocking supervisor state machine that advances a three-step daily chain:

```text
fetch-data  → av-ingestor /jobs/fetch-data
pipeline    → pipeline   /jobs/run   (factors + rank + delta)
vet         → llm-vetter /jobs/vet   (optional, advisory)
```

Each tick (every SUPERVISOR_INTERVAL_SECS) reads each service's `/runs/latest`
and triggers the first idle step, then returns. The chain advances on the next
tick. After today's chain reaches a terminal state (success/failed), further
ticks are no-ops for the rest of the calendar day — `_chain_status` resets on
date rollover.

The pipeline service also auto-triggers from av-ingestor via Redis Streams
(`stocker:pipeline_events`), so a manual fetch-data fires the pipeline
without scheduler involvement.

## api

Backend API for dashboard and control panel.

Should expose:

```text
health
current strategy
rankings
portfolio
signals
orders
backtest runs
config validation
system status
```

## dashboard

Simple web UI showing:

```text
current active strategy
ranked stocks
target portfolio
actual portfolio
intraday signals
risk decisions
orders
fills
backtests
logs
```

Dashboard should not directly execute trades.

It may request trade approval or show pending actions.

---

# LLM Boundary

Allowed LLM tasks:

```text
convert natural-language strategy prompt into structured config
explain rankings
summarize news
classify thematic exposure
suggest strategy changes
generate reports
explain trade signals
```

Not allowed:

```text
submit orders
bypass risk-service
change live config without validation
invent missing data
override safety limits
directly decide position sizing without deterministic checks
directly modify approved strategy registry
```

The LLM may suggest. Python validates and executes.

---

# Strategy Config Artifacts

Every useful prompt should produce versioned artifacts.

Recommended structure:

```text
strategies/
  quality_core_v1.yaml
  quality_ai_overlay_v1.yaml

prompts/
  quality_ai_overlay_v1.prompt.txt

backtests/
  quality_ai_overlay_v1_YYYY-MM-DD.json
```

The Git repo should be the source of truth for approved strategy configs.

Postgres stores runtime state and history.

---

# Example Strategy Config

The canonical example is in `strategies/quality_ai_overlay_v1.yaml`. The schema is defined in `shared/stock_strategy_shared/schemas/strategy.py` (Pydantic). Key structure:

```yaml
strategy_id: quality_core_v1
description: Balanced quality-momentum strategy with regime-dependent weights

universe:
  source: av_listing
  min_price: 5.0
  min_avg_dollar_volume_20d: 20000000

regime_detection:
  slow_sma: 200
  vol_window: 20
  vol_threshold: 0.20
  confirmation_days: 5
  regimes:
    bull_calm:   { spy_above_slow_sma: true,  vol_above_threshold: false }
    bull_stress: { spy_above_slow_sma: true,  vol_above_threshold: true  }
    bear_stress: { spy_above_slow_sma: false, vol_above_threshold: true  }
    bear_calm:   { spy_above_slow_sma: false, vol_above_threshold: false }

factor_weights:
  bull_calm:   { momentum: 0.35, quality: 0.25, value: 0.15, growth: 0.15, low_volatility: 0.10 }
  bull_stress: { momentum: 0.20, quality: 0.35, value: 0.15, growth: 0.10, low_volatility: 0.20 }
  bear_stress: { momentum: 0.10, quality: 0.40, value: 0.15, growth: 0.05, low_volatility: 0.30 }
  bear_calm:   { momentum: 0.20, quality: 0.30, value: 0.30, growth: 0.10, low_volatility: 0.10 }

max_positions: 30
min_score_percentile: 0.0
min_non_null_factors: 3

portfolio_builder:
  method: greedy_score_per_port_vol
  max_positions: 30
  max_position_weight: 0.10
  max_sector_weight: 0.30
  weighting: equal_weight

vetter:
  candidate_count: 50
```

Factor weights for each regime must sum to 1.0. All four regime conditions must be covered.

---

# Strategy Registry

Track approved strategy versions in Postgres.

Suggested fields:

```text
strategy_id
version
file_path
prompt_hash
config_hash
backtest_score
approval_status
created_at
active_from
active_until
paper_or_live
created_by
notes
```

The system should be able to answer:

```text
Which prompt created this strategy?
Which config generated this portfolio?
Which backtest approved this version?
Which signal caused this trade?
Which risk rule approved or rejected it?
```

---

# Build Approach

Start simple.

## Phase 1: Docker Compose Skeleton

Build:

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

No real Alpha Vantage or Alpaca calls yet.

## Phase 2: Strategy Schema and Validator

Build:

```text
strict Pydantic models
sample strategy configs
validation endpoint
unit tests
dangerous-config rejection tests
```

## Phase 3: Alpha Vantage Ingestor

Build:

```text
Alpha Vantage client skeleton
mock mode
rate-limit handling
sample ticker ingestion
Postgres storage
```

## Phase 4: Monthly Stock Engine

Build:

```text
factor-engine
ranker
portfolio-builder
sample ranking workflow
```

## Phase 5: Backtesting

Build:

```text
backtester
evaluator
backtest report artifacts
strategy comparison
```

## Phase 6: Alpaca Paper Trading

Build:

```text
alpaca-sync
intraday-monitor
risk-service
trade-executor
paper trading only
```

Do not implement live trading first.

---

# Testing

Use `pytest`.

Prioritize tests for:

```text
strategy-validator
risk-service
factor-engine
ranker
backtester
intraday-monitor
```

Every service should have:

```text
health endpoint
unit tests
clear README
typed Pydantic models where useful
```

Important test categories:

```text
valid strategy config passes
invalid strategy config fails
unsafe risk limits are rejected
LLM-generated unknown fields are rejected
factor calculations are deterministic
rankings are reproducible
backtest output is reproducible
risk-service blocks unsafe trades
trade-executor cannot run without risk approval
```

---

# Coding Style

Use:

```text
Python 3.12
FastAPI for service APIs
Pydantic for schemas
pytest for tests
Postgres for durable storage
Redis for queues/cache/locks
Docker Compose for local orchestration
```

Keep services small and clear.

Prefer explicit schemas and typed models.

Avoid clever abstractions early.

Do not add unnecessary dependencies.

---

# Repo Structure

```text
stocker/
  CLAUDE.md
  README.md
  .env.example
  docker-compose.yml
  Makefile

  docs/
    architecture.md
    service-boundaries.md
    llm-boundaries.md
    risk-safety-rules.md
    data-sources.md
    build-phases.md
    testing.md

  strategies/
    quality_ai_overlay_v1.yaml

  shared/
    pyproject.toml
    stock_strategy_shared/
      schemas/
        strategy.py      ← StrategyConfig, RegimeDetectionConfig, FactorWeights, etc.

  services/
    api/                 ← built: health, universe, rankings, portfolio, regime, live-portfolio
    strategy-validator/  ← built: /validate endpoint
    av-ingestor/         ← built: fetch-universe, fetch-data, incremental price ingestion
    factor-engine/       ← built: momentum, quality, value, growth, low_vol, beta, liquidity
    ranker/              ← built: regime detection, factor weighting, scoring, ranking runs
    portfolio-builder/   ← built: greedy_score_per_port_vol, sector caps, vetter exclusions
    llm-vetter/          ← built: Tavily + Ollama/OpenAI vetting, informational only
    delta-engine/        ← built: buffer-zone entry/exit evaluation, produces delta_intents
    dashboard/           ← built: universe/rank/vetter/portfolio/live/trade-proposal tabs
    alpaca-sync/         ← built: GET /v2/account, GET /v2/positions; writes alpaca_sync_runs + live_positions
    risk-service/        ← built: deterministic /check (kill switch, paper guard, notional limit)
    trade-executor/      ← built: only service permitted to submit Alpaca orders; writes alpaca_orders
    scheduler/           ← built: daily chain + startup catch-up
    backtester/          ← built: replays portfolio_runs against forward daily_prices
    llm-gateway/         ← partially built: provider abstraction skeleton

    intraday-monitor/    ← not yet built
    evaluator/           ← not yet built
    strategy-config-service/ ← not yet built

  tests/
    av_ingestor/
    dashboard/
    llm_vetter/
    portfolio_builder/
    shared/
```

---

# Safety Rules

The system must default to safety.

Defaults:

```text
paper trading only
human approval required for live orders
no live credentials in repo
no secrets committed
no direct LLM trading
no order without risk approval
no trade if config invalid
no trade if market data stale
no trade if kill switch is active
```

Use `.env.example` for environment variable names.

Never commit real API keys.

---

# Final Design Principle

The system is not an LLM that trades.

It is:

```text
Prompt-driven strategy design
  + deterministic Python execution
  + strict validation
  + backtesting
  + risk gates
  + audited Alpaca execution
```

Preserve this boundary throughout the codebase.
