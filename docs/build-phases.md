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
llm-vetter service
Tavily web search for news and catalysts
Ollama (local) or OpenAI LLM vetting
Output: exclude, risk_type, risk_confidence, positive_catalyst, positive_conviction, reason
vetter_decisions table in Postgres
Dashboard vetter tab: KEEP/EXCLUDE/RISK badges, catalyst badges, news sources
Informational only — no approval gate, no portfolio blocking
Conviction boosts applied in portfolio-builder (high: +0.25, medium: +0.12, low: +0.05)
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

## Phase 6: Alpaca Paper Trading (partial)

DB schema done:

```text
alpaca_sync_runs table
live_positions table
/live-portfolio API endpoint
Dashboard "Live" tab — connected/disconnected state, positions table
```

Still to build:

```text
alpaca-sync service (reads positions/orders/fills from Alpaca, writes to Postgres)
intraday-monitor service
risk-service (hard safety gate)
trade-executor (paper trading only)
```

## Phase 7: Scheduler and Automation

Build:

```text
scheduler service
daily Alpha Vantage refresh job
monthly ranking job
monthly portfolio rebalance job
periodic alpaca-sync job
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
