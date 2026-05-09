# Architecture

## System Concept

This is a prompt-driven strategy factory.

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

## Core Boundary

```text
LLM = config, interpretation, explanation
Python = deterministic engine
Risk service = hard safety gate
Trade executor = only service allowed to place orders
```

The LLM may propose and explain strategy behavior. It must not directly trade.

## Service Groups

### Stateful Infrastructure

```text
postgres
redis
artifacts volume
```

### Research and Ranking

```text
av-ingestor
factor-engine
ranker
portfolio-builder
backtester
evaluator
```

### Trading and Monitoring

```text
alpaca-sync
intraday-monitor
risk-service
trade-executor
```

### LLM and Strategy Configuration

```text
llm-gateway
strategy-config-service
strategy-validator
strategy-registry
```

### User Interface and Operations

```text
api
dashboard
scheduler
```

## Data Flow

```text
Alpha Vantage
  → av-ingestor
  → Postgres
  → factor-engine
  → ranker
  → portfolio-builder
  → target portfolio

Alpaca
  → alpaca-sync
  → Postgres

Alpaca real-time data
  → intraday-monitor
  → signal
  → risk-service
  → trade-executor
  → Alpaca order
```

## Strategy Flow

```text
User prompt
  → llm-gateway
  → strategy-config-service
  → YAML/JSON config
  → strategy-validator
  → backtester
  → evaluator
  → approval
  → active strategy registry
```

## Inter-Service Communication

Two mechanisms are used, matched to path semantics. Do not collapse them into one.

### Batch path: Postgres job table

The scheduler and all batch-triggered workflows use a `jobs` table in Postgres as a durable task queue.

```text
Pattern: SELECT ... FOR UPDATE SKIP LOCKED
```

Used for:

```text
scheduler → av-ingestor (daily Alpha Vantage refresh)
scheduler → factor-engine (factor recalculation)
scheduler → ranker (monthly ranking run)
scheduler → portfolio-builder (monthly rebalance)
scheduler → backtester (scheduled backtest runs)
scheduler → alpaca-sync (periodic position sync)
```

Why: batch jobs require durability, retry on failure, and a natural run history. The `jobs` table doubles as an audit log of what ran and when. If the scheduler or a worker restarts, no job is lost.

The scheduler writes a job row to Postgres before triggering work. Workers poll with SKIP LOCKED. On completion the row is updated with status, result, and timestamp.

### Real-time path: synchronous HTTP

The intraday signal-to-order path uses direct synchronous HTTP calls between services.

```text
intraday-monitor  →  POST /approve  →  risk-service
risk-service      →  approved/rejected response
trade-executor    →  called only on approval
```

Used for:

```text
intraday-monitor → risk-service (signal approval)
risk-service → trade-executor (approved trade intent)
strategy-validator → api (validation result)
```

Why: the intraday path is latency-sensitive and benefits from a simple, traceable request-response model. The risk-service becomes a synchronous gatekeeper — every call either returns approved or rejected with a reason. This makes the boundary easy to test and audit.

Requirement: all HTTP calls on this path must have explicit timeouts. If risk-service does not respond within the timeout, the signal is dropped and logged. intraday-monitor must never block indefinitely.

### Upgrade path

If intraday latency requirements tighten after observing real paper trading, the real-time path may be migrated to Redis Streams. Only the intraday-monitor producer and risk-service consumer need to change. This decision should be deferred until Phase 6 data is available.

## Regime Detection

### Design Decision: 4-bucket regime using trend × volatility

Market regime is classified on two independent dimensions:

```text
Trend:      SPY price vs its configurable slow SMA (default 200-day)
Volatility: SPY 20-day annualized realized vol vs a threshold (default 20%)
```

This produces four regimes:

```text
bull_calm   — SPY above SMA, vol below threshold — ride winners (momentum-heavy)
bull_stress — SPY above SMA, vol above threshold — choppy bull (rotate to quality)
bear_stress — SPY below SMA, vol above threshold — crisis mode (max defense)
bear_calm   — SPY below SMA, vol below threshold — orderly bear (value works)
```

Why 4 instead of 3: three buckets only capture trend. Volatility is an independent
dimension that materially changes which factors perform best. A volatile bull market
calls for very different weights than a calm one.

Why not more: five or six buckets add marginal signal at the cost of sparse data in
each bucket and harder LLM config generation. Four covers the most important cases.

Vol proxy: SPY 20-day realized vol (std of daily log returns × √252) is calculated
from prices already in Postgres. No VIX subscription is needed.

The SMA period, vol window, vol threshold, regime names, and conditions are all
defined in the strategy YAML under `regime_detection`. The factor-engine reads this
config at startup. The factor weights in `factor_weights` use the same regime names
as keys. Adding a fifth regime requires only a YAML change — no code change.

## State Rule

App services should be stateless. Durable state belongs in Postgres, Redis, and versioned files.

## Design Decision Rule

Whenever a design decision is made, it must be documented in the design docs before implementation begins.

This applies to: architecture choices, communication patterns, data ownership, safety rules, service boundaries, sequencing decisions, and any explicit choice between two or more reasonable options.

The docs are the source of truth for intent. If code diverges from the docs, update the docs or the code — not just a comment.
