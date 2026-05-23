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
pipeline          ← unified factor + rank + delta (Phase 7)
llm-vetter        ← advisory LLM vetting between ranking and portfolio-builder
portfolio-builder
backtester
evaluator
```

Note: `factor-engine`, `ranker`, and `delta-engine` were consolidated into the
single `pipeline` service in Phase 7. Their math modules were copied verbatim
into services/pipeline/app/{factors,rank,engine,regime}.py; the original
service folders still build but docker-compose no longer launches them.

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
  → pipeline (factors → rank → delta)
    [delta step also reads live_positions to generate exit intents for
     orphan broker positions not tracked in portfolio_holdings]
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
1. av-ingestor fetch-data       (also_accept_prev=no  — must fetch today)
2. pipeline                     (also_accept_prev=yes — accepts prev trading day)
3. llm-vetter vet               (optional/advisory — runs before portfolio-builder so
                                 exclusions feed the same-cycle build)
4. portfolio-builder            (also_accept_prev=no  — must rebuild with today's rankings)
5. delta (standalone)           (also_accept_prev=no  — must diff today's target vs live)
```

Steps 4 and 5 have `also_accept_prev=False` so they are always re-triggered each day
even if yesterday's run exists. This ensures portfolio-builder always builds from the
latest rankings and the standalone delta always produces fresh entry/exit intents.

The pipeline service also auto-triggers from av-ingestor via Redis Streams
(stream `stocker:pipeline_events`, key `run_date`), so a manual fetch-data
fires factors→rank→delta even without scheduler involvement. The pipeline
holds a global `_job_lock` for the entire duration of a run, so a concurrent
HTTP /jobs/run or Redis event sees `{"status":"already_running"}`.

`alpaca-sync` is triggered manually or fires automatically after the scheduler
chain completes. Portfolio-builder is now part of the daily scheduler chain.

**Option B: portfolio-builder in scheduler chain; delta uses target-vs-live diff mode**

The standalone delta step (step 4) uses `evaluate_target_vs_live()` instead of
`evaluate_all()` when portfolio_holdings exists:
- Entry: ticker in portfolio_holdings (target) but not yet held at broker
- Exit: ticker held at broker but removed from target portfolio
- Hold: ticker in both target and live positions, weight on target
- Watch: confirmed in entry zone but not yet in target (pending portfolio-builder)

This generates immediate entry intents on cold boot without waiting for
confirmation_days. The pipeline's embedded delta step (step 2) still uses the
same logic for backward compatibility with the "START RANK" button.

Fallback: if no portfolio run exists yet (true cold start before first
portfolio-builder run), the delta step falls back to `evaluate_all()` with
confirmation_days mode.

In `evaluate_all`'s cold-start mode, `current_portfolio` is seeded as
`{ticker: 0.0 for ticker in live_positions}` so broker-held positions can still
hit the exit branch when their rank deteriorates. The 0.0 sentinel is NOT a
real target weight: both `evaluate_ticker` and `evaluate_target_vs_live` skip
the drift-rebalance branch when `current_weight` (or `target_weight`) is None,
0, negative, or NaN. Without that guard, every held position would surface as
a `sell_trim` with `target=0.00%` until portfolio-builder completed its first
run — the exact UX bug fixed in May 2026.

## Force re-run (manual chain trigger)

`POST scheduler/jobs/run-now` always re-executes today's chain, even when it
already succeeded. This is what the dashboard "Run" button calls. Mechanics:

- Scheduler resets `_chain_status` and populates an in-memory `_force_pending`
  set with every step name.
- For each step the supervisor sees as `done` whose name is in `_force_pending`,
  it issues a forced trigger. Pipeline accepts `?force=true` to bypass its
  daily SPY-date idempotency guard; other services have no daily guard and
  naturally accept a fresh trigger.
- `_run_now_lock` is held across the entire supervised loop (including the 3s
  sleep between ticks), so a double-click returns `already_running` instead
  of resetting mid-cycle and spawning a parallel loop.
- The pending set is mirrored to `scheduler_runs.steps` under a `__meta`
  sentinel. On container restart `_startup_catch_up` reads this back so a
  rerun interrupted by a deploy or OOM resumes rather than silently truncating.

## Delta Action Types

The delta engine emits one of seven action tags per ticker per run:

```text
entry     — not held at broker, rank confirmed for confirmation_days, capacity available
watch     — not held, rank confirmed, but portfolio already at max_positions
hold      — held, rank within buffer zone, actual weight within drift_threshold of target
buy_add   — held, rank good, actual_weight < target_weight - drift_threshold (underweight)
sell_trim — held, rank good, actual_weight > target_weight + drift_threshold (overweight)
at_risk   — held, rank > exit_rank but exit not yet confirmed for confirmation_days
exit      — held, rank > exit_rank for confirmation_days in a row (confirmed exit)
```

Priority when multiple conditions apply: exit > at_risk > buy_add/sell_trim > hold.
`at_risk` suppresses drift actions — a position being evaluated for exit is not
simultaneously sized for add or trim.

Tradeable actions (require human approval): `entry`, `exit`, `buy_add`, `sell_trim`.
Informational only (no trade button): `hold`, `at_risk`, `watch`.

The drift threshold (`rebalance_drift_threshold`, default 2%) is set in the strategy
config under `delta_engine`. Drift = `actual_weight − target_weight`; actual_weight
comes from the latest alpaca_sync run's `market_value / account_value`.

Fields written to `delta_intents` for drift actions:
- `actual_weight` — current broker weight (market_value / account_value)
- `weight_drift`  — actual_weight − target_weight (positive = overweight)

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
delta-engine → delta_intents (entry / exit / hold / watch / at_risk / buy_add / sell_trim)
  → dashboard "Trade Proposal" tab (human review)
  → human clicks "Execute Now" (mode=immediate) or "Schedule for Open" (mode=scheduled)
  → dashboard POST /api/trade/approve
  → api POST /trade/approve  [thin proxy: UUID + idempotency check, then forward]
  → trade-executor POST /jobs/submit  [the orchestrator]
    1. load_intent       — read delta_intents row
    2. size_order        — entry:    floor(account_value × weight / last_price)
                          exit:     full position qty from latest live_positions
                          buy_add:  floor(account_value × abs(weight_drift) / last_price)
                          sell_trim:floor(account_value × abs(weight_drift) / last_price)
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

All four safety env vars are re-read on every `/check` call. The KILL_SWITCH can
be hot-flipped at runtime without restarting the container by touching or removing
a control file: `docker exec stocker-risk-service-1 touch /tmp/kill_switch` (ON)
/ `rm /tmp/kill_switch` (OFF). The file takes precedence over the env var.

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

### Batch path: scheduler supervisor + Redis Streams

The scheduler is a non-blocking state-machine supervisor (see scheduler/app/main.py).
Each tick reads each step's `/runs/latest`, triggers the first idle step, and
returns. The chain advances on the next tick.

```text
scheduler supervisor (every SUPERVISOR_INTERVAL_SECS seconds)
  → POST av-ingestor /jobs/fetch-data   → next tick checks status
  → POST pipeline    /jobs/run          → next tick checks status
  → POST llm-vetter  /jobs/vet          → next tick checks status (optional)
```

When av-ingestor finishes fetch-data successfully it also publishes
`fetch_data.complete` to the Redis stream `stocker:pipeline_events`. The
pipeline service's consumer (`pipeline-consumers` group) auto-triggers a
pipeline run on receipt, so a manual fetch-data also fires factors→rank→delta
without scheduler involvement.

A `409 Conflict` or `{"status": "already_running"}` response means the target
service is already running an earlier trigger. Both the scheduler and the
pipeline's Redis consumer treat this as "wait for next tick" rather than aborting.

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
