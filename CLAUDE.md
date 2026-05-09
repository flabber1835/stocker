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
  → monthly portfolio ranking
  → intraday monitoring
  → risk validation
  → Alpaca order execution
```

This is a **prompt-driven strategy factory**, not an autonomous LLM trader.

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

Universe construction: the equity universe is built from ETF holdings, not from Alpha Vantage.

```text
Use IWV (iShares Russell 3000 ETF) or VTHR (Vanguard Russell 3000 ETF) daily holdings files.
Download the holdings CSV, extract tickers, store in Postgres as the active universe snapshot.
See docs/data-sources.md for full details.
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

The system supports monthly stock picking from a Russell-3000-like U.S. equity universe.

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
av-ingestor
factor-engine
ranker
portfolio-builder
alpaca-sync
intraday-monitor
risk-service
trade-executor
llm-gateway
strategy-config-service
strategy-validator
backtester
evaluator
scheduler
api
dashboard
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

## factor-engine

Reads stored market/fundamental data from Postgres.

Calculates:

```text
quality
value
momentum
growth
low volatility
beta
liquidity
drawdown
```

Writes factor scores back to Postgres.

Should be deterministic.

## ranker

Combines factor scores according to a validated strategy config.

Produces:

```text
ranked universe
factor contribution breakdown
final score
rank percentile
reason codes
```

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

Hard safety gate.

Approves or rejects trade intents.

The LLM must not bypass this service.

Hard-coded safety laws include:

```text
max position size
max daily turnover
max order size
max daily loss
no trade if data is stale
no trade if config is invalid
no trade if Alpaca data is unavailable
paper/live mode guard
kill switch
human approval requirement for live trading
```

Risk service should be deterministic and heavily tested.

## trade-executor

Only service allowed to place Alpaca orders.

Responsibilities:

```text
receive approved trade intents
submit Alpaca paper/live orders
record submitted orders
record fills
record errors
write audit log
```

No other service should contain Alpaca order-submission credentials.

Initial implementation must be paper-trading only.

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
monthly rebalance history
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

Triggers scheduled workflows:

```text
daily Alpha Vantage refresh
monthly ranking
backtests
Alpaca sync jobs
intraday monitor startup
reports
```

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

```yaml
strategy_id: quality_ai_overlay_v1
description: Monthly quality strategy with mild AI infrastructure overlay

universe:
  source: alpha_vantage
  base: russell_like_us_equities
  min_price: 5
  min_avg_dollar_volume_20d: 20000000

portfolio_strategy:
  rebalance: monthly
  ranking:
    quality: 0.35
    momentum: 0.25
    value: 0.15
    low_volatility: 0.10
    growth: 0.10
    ai_theme: 0.05

portfolio:
  max_positions: 30
  max_position_weight: 0.06
  max_sector_weight: 0.25
  cash_reserve: 0.02

trading_behavior:
  intraday_monitoring: true
  rules:
    - name: trim_big_winner
      trigger:
        intraday_return_gt: 0.06
        outperforms_qqq_by_gt: 0.03
        require_not_top_decile: true
      action:
        type: trim
        percent_of_position: 0.25
        execution_window: close_minus_30m

risk_limits:
  max_daily_turnover: 0.20
  max_order_value_pct_of_portfolio: 0.05
  paper_trading_only: true
  require_human_approval_for_live_orders: true
```

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

# Repo Structure Target

Initial target structure:

```text
stock-strategy/
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

  strategies/
    quality_ai_overlay_v1.yaml

  prompts/

  backtests/

  shared/
    pyproject.toml
    stock_strategy_shared/
      __init__.py
      schemas/
        strategy.py

  services/
    api/
      Dockerfile
      pyproject.toml
      app/
        main.py
      tests/

    strategy-validator/
      Dockerfile
      pyproject.toml
      app/
        main.py
        validator.py
      tests/
        test_validator.py

    av-ingestor/
    factor-engine/
    ranker/
    portfolio-builder/
    alpaca-sync/
    intraday-monitor/
    risk-service/
    trade-executor/
    llm-gateway/
    backtester/
    evaluator/
    scheduler/
    dashboard/
```

---

# First Implementation Task

When starting from an empty repo, implement only this first:

```text
docker-compose.yml
.env.example
Makefile
README.md
shared Python package for strategy schemas
services/api with FastAPI health endpoint
services/strategy-validator with FastAPI health endpoint and /validate endpoint
sample strategy config under strategies/quality_ai_overlay_v1.yaml
pytest tests for the strategy validator
postgres and redis services in compose
```

Do not implement real Alpha Vantage or Alpaca calls in the first task.

Use mocks/placeholders first.

`docker compose up` should work.

`make test` should run tests.

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
