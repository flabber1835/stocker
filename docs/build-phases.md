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
IWV/ETF holdings universe fetch (fetch-universe job type)
daily price and fundamentals ingestion (fetch-data job type)
incremental fetch (skips tickers already up to date)
strict ticker regex validation
adjusted_close × volume for dollar-volume filtering
75 req/min rate limiting
Postgres storage with UPSERT
job_type field to distinguish universe vs data runs
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

## Phase 5: Backtesting ← NEXT

Build:

```text
backtester service
replay historical ranking runs against forward returns
simulated trades, returns, drawdowns, turnover
Sharpe-like metrics
benchmark comparison (SPY)
position history
monthly rebalance history
backtest report artifacts
```

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
