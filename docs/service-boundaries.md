# Service Boundaries

## Stateful Services

### postgres

Durable system of record for:

```text
tickers
prices
fundamentals
factor scores
rankings
target portfolios
actual positions
signals
risk decisions
orders
fills
backtest runs
strategy registry
audit logs
```

### redis

Temporary coordination layer:

```text
job queue
locks
short-lived cache
rate-limit counters
intraday temporary state
```

Redis should be treated as rebuildable.

## Stateless App Services

### av-ingestor

Pulls Alpha Vantage data. It stores raw and normalized data in Postgres. It should respect rate limits and should not calculate factors.

### factor-engine

Calculates deterministic factor scores from stored data.

### ranker

Combines factor scores according to strategy config and produces ranked universe.

### portfolio-builder

Converts ranked stocks into target portfolio weights.

### alpaca-sync

Syncs account, positions, orders, and fills from Alpaca. It does not submit orders.

### intraday-monitor

Monitors holdings and watchlist names using Alpaca market data. It emits signals only. It does not place trades.

### risk-service

Approves or rejects trade intents. It enforces hard safety rules and cannot be bypassed.

### trade-executor

Only service allowed to place Alpaca orders. It requires prior risk approval.

### llm-gateway

Central provider abstraction for API or local LLMs.

### strategy-config-service

Converts prompts into YAML/JSON strategy configs using the LLM gateway.

### strategy-validator

Validates strategy configs against strict schema and safety rules.

### backtester

Runs historical simulations from configs.

### evaluator

Reviews results and may request LLM suggestions. It cannot deploy changes.

### scheduler

Triggers recurring jobs.

### api

Backend API for the dashboard and control layer.

### dashboard

Displays strategy, portfolio, rankings, signals, trades, logs, and backtest results. It does not directly trade.
