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
locks
short-lived cache
rate-limit counters
intraday temporary state
```

Redis does not own the job queue. Batch job scheduling uses the Postgres `jobs` table instead.

Redis should be treated as rebuildable.

## Stateless App Services

### av-ingestor

Pulls Alpha Vantage data. Stores raw and normalized data in Postgres. Respects rate
limits. Does not calculate factors.

Key behaviors:
- `fetch-universe` job: fetches AV LISTING_STATUS, stores ticker list
- `fetch-data` job: incremental price + fundamentals per ticker; skips tickers already current
- `/runs/latest` exposes `tickers_done` and `total_tickers` for real-time progress tracking
  (in-memory counter, cleared on job completion or container restart)
- Lifespan marks any `running` row as `failed` on startup to recover from crashes

### factor-engine

Calculates deterministic factor scores from stored data. Performs SPY regime detection
(trend × volatility, 4 buckets, 5-day confirmation smoothing). Writes factor scores and
regime to Postgres. Lifespan marks orphaned runs as failed on startup.

### ranker

Combines factor scores according to strategy config and produces a ranked universe.
Runs after factor-engine completes. Lifespan marks orphaned runs as failed on startup.

### portfolio-builder

Converts ranked stocks into target portfolio weights. Applies conviction boosts from
the vetter when available (high: +0.25, medium: +0.12, low: +0.05). Does not require
vetter approval — vetter output is advisory only.

### llm-vetter

Vets ranked stocks using LLM reasoning (Ollama or OpenAI) and Tavily web search.
Produces per-stock signals: `exclude`, `risk_type`, `risk_confidence`,
`positive_catalyst`, `positive_conviction`, `reason`. Results stored in
`vetter_decisions` and used by portfolio-builder for soft score adjustments.
The vetter is never a hard gate — portfolio construction proceeds whether or not
the vetter has run.

### backtester

Replays historical portfolio decisions against forward price returns.

Input: saved `portfolio_runs` + `portfolio_holdings` rows from portfolio-builder.
Does not re-simulate the pipeline — uses actual historical weights, which avoids
reimplementing portfolio construction logic and prevents look-ahead bias.

Outputs:
- `backtest_runs` row with summary metrics (total_return, annualized_return,
  sharpe_ratio, max_drawdown, avg_monthly_turnover, win_rate, benchmark comparison)
- `backtest_monthly` rows with per-period holdings snapshot JSONB

Tables are created by the service lifespan if they don't exist, so no manual
migration is required when first deployed.

API:
- `POST /jobs/backtest` — triggers background run (date_from, date_to, tx_cost_bps)
- `GET /runs/latest`, `/runs/{id}`, `/runs/{id}/monthly`

### alpaca-sync

Syncs account, positions, orders, and fills from Alpaca. Does not submit orders.

### intraday-monitor

Monitors holdings and watchlist names using Alpaca market data. Emits signals only.
Does not place trades.

### risk-service

Approves or rejects trade intents. Enforces hard safety rules. Cannot be bypassed.

### trade-executor

Only service allowed to place Alpaca orders. Requires prior risk approval.

### llm-gateway

Central provider abstraction for API or local LLMs.

### strategy-config-service

Converts prompts into YAML/JSON strategy configs using the LLM gateway.

### strategy-validator

Validates strategy configs against strict schema and safety rules.

### evaluator

Reviews backtest and paper trading results. May request LLM suggestions. Cannot
deploy changes.

### scheduler

Triggers recurring jobs.

### api

Backend API for the dashboard and control layer. Exposes:
`/universe`, `/rankings`, `/portfolio`, `/regime`, `/live-portfolio`

### dashboard

Displays strategy, rankings, portfolio, vetter output, live positions, and progress.
Does not directly trade.

Cloud-native render architecture: all job state lives on the server. Browsers poll
`GET /api/pipeline-status` every 2 seconds and render identically regardless of
which browser or device started the job. No per-browser state machine.

Server-side rank chain orchestration: `POST /api/jobs/rank-chain` triggers a
background task on the dashboard server that runs fetch-data → calc-factors → rank
sequentially, polling each service until it completes before starting the next.
Handles 409 (step already running) by waiting rather than aborting.
