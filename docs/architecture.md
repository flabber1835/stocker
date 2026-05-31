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
llm-vetter        ← mandatory LLM vetting between ranking and portfolio-builder (binding exclusions)
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
  → pipeline (factors → rank only; delta is NOT run here)
  → llm-vetter  (mandatory; binding exclusions — chain halts if it fails)
  → portfolio-builder  (target weights, reads today's vetter exclusions)
  → delta  (proposals written here — always reflect today's vetter + target)
  → delta_intents (entry / exit / hold proposals visible on dashboard)

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
3. llm-vetter vet               (mandatory — must succeed before portfolio is built;
                                 exclusions feed the same-cycle build)
4. portfolio-builder            (also_accept_prev=no  — must rebuild with today's rankings;
                                 refuses to run if no vetter run exists for today's ranking)
5. delta (standalone)           (also_accept_prev=no  — must diff today's target vs live)
```

The sequence is strictly enforced: each step only starts after the previous one
has completed successfully. If any step fails, the chain halts — including the
vetter. The portfolio will never be built without today's vetter exclusions applied.

Steps 4 and 5 have `also_accept_prev=False` so they are always re-triggered each day
even if yesterday's run exists. This ensures portfolio-builder always builds from the
latest rankings and the standalone delta always produces fresh entry/exit intents.

The pipeline service maintains a Redis consumer on `stocker:pipeline_events` to
drain the Pending Entries List on restart (recovering events claimed before a crash).
Events are ACK'd on receipt but do not auto-trigger pipeline steps — the scheduler
is the sole driver of the chain.

**Why delta does not run inside the pipeline step:**
Running delta inside `/jobs/run` would produce proposals immediately after
ranking, before the vetter and portfolio-builder have run for today.  Those
early proposals would reflect yesterday's vetter exclusions and target weights.
Removing delta from the pipeline step ensures proposals only appear once the
full chain completes (after step 5), and they always reflect today's inputs.

`alpaca-sync` is triggered manually or fires automatically after the scheduler
chain completes. Portfolio-builder is now part of the daily scheduler chain.

**Delta step (step 5) modes:**

The standalone delta step uses `evaluate_target_vs_live()` instead of
`evaluate_all()` when portfolio_holdings exists:
- Entry: ticker in portfolio_holdings (target) but not yet held at broker
- Exit: ticker held at broker but removed from target portfolio
- Hold: ticker in both target and live positions, weight on target
- Watch: confirmed in entry zone but not yet in target (pending portfolio-builder)

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

### Buy-side gating (capacity + buying power)

After the per-ticker actions are assigned, `evaluate_target_vs_live` applies two
deterministic post-passes so a proposal can never breach the position cap or
spend cash the account doesn't have (`_cap_buys` / `_trim_to_cap` in
`services/pipeline/app/engine.py`, both pure and unit-tested):

- **Capacity gate (position count, entries only):** `retained_held + kept_entries
  ≤ max_positions`. Best-ranked entries are kept; the rest are demoted
  `entry → watch` with reason "deferred — portfolio at capacity". `buy_add`s
  don't add positions, so they are exempt from this gate.
- **Buying-power gate (cash, entries + buy_adds share one budget):** kept buys
  are funded best-ranked-first against
  `available = buying_power/account_value + exit proceeds + sell_trim proceeds`.
  Sell-side proceeds are credited so a same-open rotation (exit funds a new
  entry) still works at ~0 buying power. Unfunded buys are demoted:
  `entry → watch`, `buy_add → hold` (keep the position, defer the top-up). Only
  enforced when `account_value > 0` and `buying_power` are supplied; otherwise
  the trade-executor and risk-service remain the cash backstop.
- **Trim-to-cap:** the buffer-zone exit is rank-based, so a *well-ranked* orphan
  (held but covariance-excluded from the target) never exits on its own and the
  realized book can sit above `max_positions`. When `retained + kept_entries >
  max_positions`, `_trim_to_cap` exits the worst-ranked **orphans** first
  (held AND not in target). In-target holds are never force-sold; no-data
  orphans (rank 9999) are skipped.

When the broker state is unreliable (`_broker_state_unreliable()` — no sync,
sync staler than `DELTA_SYNC_MAX_AGE_HOURS`, default 12h, or funded-but-no-
positions), all buy-side intents are suppressed because sizing against a wrong
account snapshot would be unsafe. Exits are never suppressed (closing is always
allowed). See `docs/risk-safety-rules.md` for the full guard description.

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

## Design Decision: correlation-cluster cap replaces the sector cap

The portfolio-builder caps concentration by **correlation cluster**, not by the
data provider's sector label.

**Why.** The provider sector strings are unreliable for risk grouping — e.g.
Alphabet (GOOG) is tagged `Communication Services` while behaving like a mega-cap
tech name, and a basket of gold miners can span `Basic Materials`, `Energy`, and
others while moving as one block. Capping by sector therefore both over- and
under-constrains real co-movement. Correlation is computed directly from the same
covariance matrix the optimizer already builds, so it groups names by how they
actually trade.

**How.** From the (shrunk) covariance matrix we derive the correlation matrix and
form clusters by single-linkage union-find: tickers A and B are in the same
cluster when `|corr(A,B)| ≥ cluster_correlation_threshold` (default **0.70**).
Those cluster labels are then fed into the *existing* group-cap machinery — the
same greedy count cap (`greedy_select`) and post-build weight redistribution
(`compute_weights`) that previously consumed sector labels. No new constraint
solver: the cluster is just a different grouping passed to proven code.

**Settings** (`PortfolioBuilderConfig`):

```text
cluster_correlation_threshold  default 0.70  — |corr| at/above which two names cluster
max_cluster_weight             default 0.15  — max summed portfolio weight per cluster
```

A 15% cap implies the portfolio spans **at least 7 effectively-independent
clusters** (⌈1/0.15⌉) to be fully invested, preventing a single correlated theme
(e.g. "the golds") from dominating even when its members hold the top ranks.

**Sectors are retained for logging only** — per-sector weights are still computed
and surfaced in the trace/`portfolio_runs` for human readability, but they no
longer gate selection or weighting. Setting `max_cluster_weight = 1.0` disables
the cluster cap (mirrors the old `max_sector_weight = 1.0` no-op).

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
  → POST llm-vetter  /jobs/vet          → next tick checks status (mandatory)
  → POST portfolio-builder /jobs/build  → next tick checks status
  → POST pipeline    /jobs/delta        → next tick checks status
```

A `409 Conflict` or `{"status": "already_running"}` response means the target
service is already running an earlier trigger. The scheduler treats this as
"wait for next tick" rather than aborting.

### Restart recovery

`docker compose down` (or any crash) mid-chain must not wedge the chain until
midnight. Every persistence-using service calls the shared
`mark_orphaned_runs_failed()` helper on startup, which marks orphaned
`status='running'` rows as `failed` with a `RESTART_ABORTED:` prefix in
`error_message`. The scheduler's `_step_state` and cold-start branch
distinguish this prefix from a real failure:

```text
marker present → state="idle"   → re-trigger on next tick
marker absent  → state="failed" → suspend chain until tomorrow
```

The pipeline's Redis consumer also drains the Pending Entries List with
`id="0"` on startup before switching to `>` reads, so `fetch_data.complete`
events claimed-but-not-xack'd by a crashed previous instance are still
processed.  See `docs/service-boundaries.md` § "Restart Recovery" for the
full mechanism and step coverage.

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
bull_calm   — SPY above SMA, vol below threshold — momentum dominates; low-vol weight minimized
bull_stress — SPY above SMA, vol above threshold — low-vol and quality absorb momentum crash risk
bear_stress — SPY below SMA, vol above threshold — maximum defense: low-vol + quality lead
bear_calm   — SPY below SMA, vol below threshold — value + quality combination; momentum cut sharply
```

Factor weight rationale by regime (see `strategies/quality_core_v1.yaml` for exact values):

```text
bull_calm:   momentum leads — statistically significant only in UP market states (Cooper et al. JF 2004)
             low_vol at minimum — Blitz & van Vliet show smallest premium in calm bull markets

bull_stress: low_vol and quality elevated — BAB premium doubles above vol=20% (Frazzini & Pedersen 2014)
             momentum reduced — Sharpe drops ~40% when vol rises (Daniel & Moskowitz JFE 2016)

bear_stress: low_vol dominant — largest anomaly in bad market states (Ang et al. JF 2006)
             quality second — QMJ earns ~8% in credit crises (Asness, Frazzini & Pedersen 2019)
             momentum at minimum — highest crash risk state (Daniel & Moskowitz 2016)

bear_calm:   value leads — premium peaks post-distress (Fama & French JF 1996; LSV JF 1994)
             quality raised — Graham-Dodd combination: value WITH quality prevents value traps
             momentum cut sharply — Cooper et al. 2004: momentum −0.37%/month in DOWN market states
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
