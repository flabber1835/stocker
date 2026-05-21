# Architecture

## System Concept

This is a prompt-driven strategy factory.

```text
Prompt
  → LLM-generated strategy config
  → validated YAML/JSON
  → backtest
  → approval
  → daily ranking (continuous buffer-zone rebalance)
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
llm-vetter        ← advisory LLM vetting between ranker and portfolio-builder
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

Daily chain (scheduler):

```text
1. av-ingestor fetch-data
2. factor-engine calculate
3. ranker rank
4. llm-vetter vet
5. portfolio-builder build
6. delta-engine evaluate
7. alpaca-sync refresh
```

Startup catch-up: scheduler runs `alpaca-sync` first (non-blocking) so the live
position view is current before any rank-chain work begins.

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

## Trade Approval Flow

Every paper trade requires a human button click. The system does not auto-submit
even after the delta engine fires — the delta_intents row is just a proposal until
a human approves it on the dashboard.

```text
delta-engine → delta_intents (entry / exit / hold / watch)
  → dashboard "Trade Proposal" tab (human review)
  → human clicks "Execute Now" (mode=immediate) or "Schedule for Open" (mode=scheduled)
  → dashboard POST /api/trade/approve
  → api POST /trade/approve  [thin proxy: UUID + idempotency check, then forward]
  → trade-executor POST /jobs/submit  [the orchestrator]
    1. load_intent       — read delta_intents row
    2. size_order        — entries: floor(account_value × weight / last_price)
                          exits:   full position qty from latest live_positions
    3. risk_check        — call risk-service POST /check
    4. record_order      — INSERT alpaca_orders (pending or risk_rejected)
    5. submit_alpaca     — POST /v2/orders if approved + credentials present
```

Every approval click writes one `execution_traces` row plus an `execution_steps`
row per step above, so the dashboard's trace viewer shows exactly which step
succeeded, was skipped, or failed for any given click. Sizing decisions
(weight source, account value, price source) and risk decisions (rule_triggered,
reason) are recorded in step outputs.

Risk-service writes one row to `risk_decisions` per `/check` call with the env
snapshot (KILL_SWITCH, PAPER_ONLY, LIVE_TRADING_ENABLED, MAX_ORDER_NOTIONAL at
the time of the decision) so historical decisions remain auditable even if the
config later changes. `alpaca_orders.risk_check_id` is a FK into this table.

### Audit chain

```text
execution_traces  ←  alpaca_orders.trace_id           (one trace per click)
                  ←  alpaca_sync_runs.trace_id        (one trace per sync)
execution_steps   ←  trace_id                          (one row per step)
risk_decisions    ←  alpaca_orders.risk_check_id       (rule + env snapshot)
delta_intents     ←  alpaca_orders.intent_id           (proposal lineage)
```

This satisfies the audit requirements from CLAUDE.md:
- "Which prompt created this strategy?" → strategy_id + config_hash
- "Which signal caused this trade?" → alpaca_orders.intent_id → delta_intents
- "Which risk rule approved or rejected it?" → alpaca_orders.risk_check_id → risk_decisions

## Inter-Service Communication

Two mechanisms are used, matched to path semantics.

### Batch path: direct HTTP from dashboard orchestrator

The dashboard server orchestrates the rank chain via direct HTTP calls to the
downstream services. This is initiated by `POST /api/jobs/rank-chain` and runs
as a background task on the dashboard process.

```text
dashboard (rank-chain bg task)
  → POST av-ingestor  /jobs/fetch-data   → poll /runs/latest until done
  → POST factor-engine /jobs/calculate   → poll /runs/latest until done
  → POST ranker        /jobs/rank        → poll /runs/latest until done
```

Each service independently manages its own run state in Postgres (one row per
run, status transitions: running → success/failed). The dashboard polls each
service's `/runs/latest` endpoint every 5 seconds to detect completion before
advancing to the next step.

A `409 Conflict` response means a step is already running from a previous trigger.
The orchestrator treats this as "wait for it" rather than aborting.

Why direct HTTP (not a Postgres jobs table): the rank chain is triggered
interactively from the dashboard and completes within an hour. Durability of the
queue itself is not required — each service's run table already provides the audit
log and recovery point. A scheduler service (Phase 7) can call the same HTTP
endpoints.

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

Why: the intraday path is latency-sensitive and benefits from a simple, traceable
request-response model. The risk-service becomes a synchronous gatekeeper — every
call either returns approved or rejected with a reason. This makes the boundary easy
to test and audit.

Requirement: all HTTP calls on this path must have explicit timeouts. If risk-service
does not respond within the timeout, the signal is dropped and logged.
intraday-monitor must never block indefinitely.

### Upgrade path

If intraday latency requirements tighten after observing real paper trading, the
real-time path may be migrated to Redis Streams. Only the intraday-monitor producer
and risk-service consumer need to change. Defer until Phase 6 data is available.

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

Confirmation smoothing: both the trend signal and the vol signal must be consistent
for `confirmation_days` consecutive trading days before a regime switch is accepted.
This prevents flipping regimes on a single bad day. Default is 5 days. If signals
are mixed, a majority vote across the confirmation window is used. This is especially
important for continuous rebalancing where a one-day blip should not trigger a position change.

The SMA period, vol window, vol threshold, confirmation days, regime names, and
conditions are all defined in the strategy YAML under `regime_detection`. The
factor-engine reads this config at startup. The factor weights in `factor_weights`
use the same regime names as keys. Adding a fifth regime requires only a YAML
change — no code change.

## State Rule

App services should be stateless. Durable state belongs in Postgres, Redis, and versioned files.

## Design Decision Rule

Whenever a design decision is made, it must be documented in the design docs before implementation begins.

This applies to: architecture choices, communication patterns, data ownership, safety rules, service boundaries, sequencing decisions, and any explicit choice between two or more reasonable options.

The docs are the source of truth for intent. If code diverges from the docs, update the docs or the code — not just a comment.
