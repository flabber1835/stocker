# Risk and Safety Rules

## Default Safety Posture

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

## Implemented Safety Controls (Phase 6)

These are actually enforced in code today.

```text
KILL_SWITCH              — if active, risk-service rejects all checks (see hot-flip below)
LIVE_TRADING_ENABLED     — must be "true" for trade_type=="live" to pass; default "false"
PAPER_ONLY               — when "true", any live trade is rejected; default "true"
MAX_ORDER_NOTIONAL       — default $50,000 per order
MAX_DAILY_TURNOVER_PCT   — default 0.50 (50%); per-day sell-side cap (see below)
MAX_DAILY_LOSS_PCT       — default 0.10 (10%); halts ALL trades after a daily drawdown
MAX_POSITION_PCT         — default 0.15 (15%); per-ticker concentration cap on buys
MAX_POSITIONS            — default 35; refuses new entries when live_positions reaches cap
MAX_DATA_AGE_HOURS       — default 96; refuses buys when pipeline rankings are too stale
MAX_SYNC_AGE_HOURS       — default 24; refuses ALL trades when alpaca-sync is too stale
qty > 0 validation       — enforced in risk-service /check
notional > 0 validation  — enforced in risk-service /check

Human approval window with auto-approve fallback — the dashboard's auto-approve
  background task gives a human TRADE_AUTO_APPROVE_MINUTES (default 60) to
  manually approve or reject each pending intent. After that timeout the
  dashboard automatically POSTs /trade/approve. This applies to all four
  tradeable actions (entry, exit, buy_add, sell_trim). Vetter-excluded BUY-side
  intents (entry, buy_add) are NOT auto-approved — a human must intervene.
  Manually-rejected intents (rejected_at set) are never auto-approved.
  Set TRADE_AUTO_APPROVE_MINUTES to a very large number to keep approval fully
  manual.

Scheduled-only auto-approve (manual runs require a human) — auto-approve fires
  ONLY for the after-close scheduled/cron chain. A manual run (dashboard "Run"
  button → scheduler /jobs/run-now) is tagged `delta_runs.manual=TRUE` and is
  surfaced via /delta/latest; the dashboard never auto-approves a manual run's
  proposals, regardless of the timeout. Rationale: a scheduled run fires after the
  close on a trading day, when the prior day's orders have filled and alpaca-sync
  is current, so auto-approve is safe. A manual run is off-cadence (e.g. a weekend
  catch-up) and can stack new orders on a queued-but-unfilled book, so it requires
  human review. `manual` is a separate column from `triggered_by` (which stays
  'scheduler' for both cron and manual standalone deltas so /runs/delta-latest can
  keep tracking the step).

Manual-run cancel-all pre-step — when a manual run starts (scheduler
  /jobs/run-now), the scheduler first calls trade-executor
  POST /jobs/cancel-all-orders?confirm=yes (cancelling EVERY open Alpaca order)
  and then re-runs alpaca-sync, BEFORE the chain builds fresh proposals. This
  guarantees a manual run computes deltas against a clean broker state and cannot
  submit duplicate orders on top of a still-open book. The after-close cron chain
  does NOT cancel — by then the prior orders have filled and the book is clean.
  A failed cancel is logged but does not wedge the run (unfilled orders carry no
  position). Scheduler needs TRADE_EXECUTOR_URL set for this call.

trade-executor short-circuits when Alpaca credentials are empty
llm-vetter cannot place trades; its exclusions are binding (remove tickers from
  the candidate pool) but it never sizes, approves, or submits orders
```

### Chain liveness heartbeat

The scheduler exposes `GET /health/chain` (also proxied as `GET /health/chain`
on the api). It returns:

```text
200 healthy   — latest successful scheduler_runs row completed within
                CHAIN_HEALTH_MAX_AGE_HOURS (default 36h)
503 unhealthy — no successful chain on record, OR latest success is older than
                the threshold, OR the database is unreachable
```

The response body includes `age_hours`, `last_success_chain_date`,
`latest_run_status`, and a human-readable `reason`. Point an external monitor
(Pingdom / GitHub Actions / k8s liveness probe / cron + curl) at this endpoint
to alert when the daily pipeline stops running. 36h is the default so a normal
weekend gap (~67h from Friday close to Monday close) will trip the alert by
Sunday — adjust via `CHAIN_HEALTH_MAX_AGE_HOURS` if you want a wider tolerance.

### Timezone consistency in step done-detection

The scheduler runs `TZ=America/New_York` and computes `today = date.today()` /
`trading_day` in that local zone. Services stamp `started_at` in UTC
(`datetime.now(timezone.utc)`). When the supervisor decides whether a step "ran
today", it MUST convert a wall-clock `started_at` to local time before taking the
date — see `_comparable_run_date` in `services/scheduler/app/main.py`. Comparing a
raw UTC `started_at[:10]` against a local `today` breaks in the evening-ET window
(≈19:00–24:00 ET) where the UTC date is already tomorrow: the step never reads
"done", so the supervisor re-triggers it every tick. For the vetter (per-ticker
LLM calls) that meant re-billing credits ~every 16 minutes until ET rolled over.
Two defenses: (1) `_comparable_run_date` makes the comparison zone-consistent;
(2) `/jobs/vet` has an idempotency guard (`already_vetted`) so a ranking that was
already vetted is never re-vetted unless `force=true`. Pure DATE columns
(`chain_date`, `run_date`, `portfolio_date`) carry no time component and compare
directly. Orphaned `running` `scheduler_runs` rows from prior days are closed on
startup (`_close_stale_running_chains`).

### MAX_DAILY_TURNOVER_PCT — sell-side daily turnover cap

Rejects an `exit` or `sell_trim` once today's cumulative sell notional plus
this order would exceed `account_value × MAX_DAILY_TURNOVER_PCT`. Default is
0.50 (50% of portfolio). Entries and buy_adds are NOT counted — they deploy
idle cash, not portfolio churn. The cap is designed to prevent flipping
half the portfolio in a single day on a regime change (15 exits × $3.3K
= $49.5K ≈ 50% of $100K), while leaving cold-boot capital deployment
unconstrained.

Scoping uses the simulation date when available (trade-executor passes
`sim_date` derived from `delta_runs.run_date` for the intent's run), and
falls back to wall-clock `CURRENT_DATE` otherwise. This makes the cap
behave correctly in both production (each calendar day is its own scope)
and harness simulations (each simulated day is its own scope, even though
all submissions happen on one wall-clock day).

Set `MAX_DAILY_TURNOVER_PCT=1.0` to effectively disable the cap.

### MAX_SYNC_AGE_HOURS — Alpaca availability gate

Refuses ALL actions (entries, exits, buy_adds, sell_trims) when the most
recent successful `alpaca_sync_runs` row is older than the threshold (default
24h) or when no successful sync exists. A stale broker view means qty,
buying_power, and live_positions are unreliable; sizing decisions made
against them could double-spend cash or sell positions we no longer hold.

This is the broad version of trade-executor's existing
`EXIT_SYNC_MAX_AGE_HOURS` check — trade-executor refuses to size exits from
a stale sync (because qty is uncertain), risk-service refuses to approve any
trade because the entire broker picture is suspect.

Set `MAX_SYNC_AGE_HOURS=0` (or any value `≤ 0`) to disable.

### MAX_DATA_AGE_HOURS — factor data staleness gate

Refuses `entry` and `buy_add` when the most recent successful `pipeline_runs`
row completed more than `MAX_DATA_AGE_HOURS` ago (default 96h ≈ 4 days,
generous enough to cover a long weekend without spurious rejections).

Sells (`exit`, `sell_trim`) are NOT gated by this rule — closing a position
on stale data is conservative; opening a new one is not. The rule guards
against the scenario where the daily pipeline has stopped running but the
delta engine fired stale `entry` intents that someone clicks Approve on.

Set `MAX_DATA_AGE_HOURS=0` to disable.

### DELTA_SYNC_MAX_AGE_HOURS — delta broker-state reliability guard (proposal-time)

A deterministic guard inside the **delta step** (not the risk-service), applied
*before* any trade intents are written. The delta's `target_vs_live` mode emits
an `entry` for every target ticker not present in `live_positions`; if the
broker snapshot is unreliable this floods buy-to-open intents that exceed
buying power and bounce at Alpaca for insufficient funds.

The delta suppresses buy-side intents (`entry`, `buy_add`) — keeping
`exit`/`hold`/`watch`/`sell_trim`, since closing is always safe — when the
latest successful `alpaca_sync_runs` snapshot is unreliable, defined as any of:

```text
- no successful alpaca-sync run exists (broker holdings unknown); or
- the latest successful sync is older than DELTA_SYNC_MAX_AGE_HOURS (default 12h); or
- the account is funded with capital clearly deployed (cash < 50% of
  account_value, or cash unrecorded) yet zero live positions were captured —
  an internally inconsistent snapshot.
```

A genuine all-cash account (cash ≈ account_value, no positions) is NOT flagged,
so the first buy of a fresh account still works. The decision is implemented by
the pure function `_broker_state_unreliable()` in `services/pipeline/app/main.py`
(unit-tested in `tests/pipeline/test_broker_state_guard.py`).

This is defense-in-depth with the risk-service: `MAX_SYNC_AGE_HOURS` rejects at
trade time on an *old* sync, but cannot catch a *recent-but-empty* snapshot
(which still looks fresh); the delta guard refuses to *propose* the buys in the
first place. Set `DELTA_SYNC_MAX_AGE_HOURS` very high to relax the age component
(the inconsistency and no-sync components always apply).

### MAX_DAILY_LOSS_PCT — automated trading halt on drawdown

Compares the latest `alpaca_sync_runs.account_value` against the earliest
successful sync from "today" (sim_date when provided, else `CURRENT_DATE`).
If the day's drawdown exceeds `MAX_DAILY_LOSS_PCT` (default 10%), refuses
ALL trades — both buys and sells. The rationale for halting sells too: in a
fast drawdown the system should freeze and let an operator decide manually,
rather than executing potentially panic-driven exits.

This is the automated complement to `KILL_SWITCH`, which is operator-flipped.

Set `MAX_DAILY_LOSS_PCT=1.0` (or higher) to disable.

### MAX_POSITIONS — portfolio count cap

Refuses `entry` when the broker already holds `MAX_POSITIONS` distinct
tickers (default 35) AND this entry is for a ticker not currently held.
`buy_add`, `exit`, and `sell_trim` are not affected (none of them grow the
distinct-ticker count). Acts as defense in depth alongside the portfolio-
builder's `max_positions` config — if a misconfigured strategy or bug ever
generated entries past the cap, this gate blocks them.

Set `MAX_POSITIONS=0` to disable.

### MAX_POSITION_PCT — per-ticker concentration cap

Refuses `entry` and `buy_add` when filling the order would push the ticker
above `MAX_POSITION_PCT` of `account_value` (default 15%). Computed as:

```text
(current_market_value + order_notional) / account_value > MAX_POSITION_PCT
```

The portfolio-builder caps targets at `max_position_weight` (default 10%) at
construction time, but price appreciation can drift an existing position
above that cap. Without this gate a delta-engine `buy_add` could compound
the over-concentration; with it, buy_adds for already-bloated positions are
blocked at the risk-service layer.

Sells are not gated (they reduce concentration).

Set `MAX_POSITION_PCT=1.0` to disable.

### KILL_SWITCH hot-flip (no restart required)

All four safety env vars are re-read on every `/check` call, so changing the Docker
environment variable alone would require restarting the container (because
`os.getenv()` reads the frozen process environment). To hot-flip the kill switch
at runtime without any restart, use the control file:

```bash
# Activate kill switch immediately (blocks all new trades):
docker exec stocker-risk-service-1 touch /tmp/kill_switch

# Deactivate:
docker exec stocker-risk-service-1 rm /tmp/kill_switch
```

The file takes precedence over the `KILL_SWITCH` env var when present. The
`KILL_SWITCH` env var still works as the startup default (read from process
environment at container launch). If the file exists, all `/check` calls are
rejected regardless of the env var value.

## Defense-in-depth pairings

Several safety controls are intentionally checked in two places. If one
layer is bypassed (config error, code regression, or a new caller skipping
a path), the other still catches it:

| Concern | Early-rejection point | Risk-service backstop |
|---|---|---|
| Exit-sizing on stale sync | trade-executor `EXIT_SYNC_MAX_AGE_HOURS` (refuses to size) | `MAX_SYNC_AGE_HOURS` (refuses to approve) |
| Per-ticker concentration | portfolio-builder `max_position_weight` (construction) | `MAX_POSITION_PCT` (post-drift, at check) |
| Portfolio size | portfolio-builder `max_positions` + delta engine capacity | `MAX_POSITIONS` (broker-state-based) |

## Audit Trail

Every approval click produces a chain of audit rows so any trade can be traced
back to its origin:

```text
delta_intents.id
  ← alpaca_orders.intent_id          (which proposal triggered this order)

execution_traces.trace_id
  ← alpaca_orders.trace_id           (per-click trace, one trace per approval)
  ← alpaca_sync_runs.trace_id        (per-sync trace, one trace per sync)
execution_steps.trace_id
  ← step-by-step audit of every trace (status, input/output JSON, duration, errors)

risk_decisions.decision_id
  ← alpaca_orders.risk_check_id      (which rule + env snapshot drove the decision)
```

The `risk_decisions` table captures the env snapshot at decision time
(`KILL_SWITCH`, `PAPER_ONLY`, `LIVE_TRADING_ENABLED`, `MAX_ORDER_NOTIONAL`)
so a later config change cannot rewrite the rationale of historical decisions.
`MAX_DAILY_TURNOVER_PCT` is read on every `/check` call but is not yet
persisted in the env snapshot — when the cap rejects, the rule_triggered
column is `daily_turnover_limit` and the reason text records the actual
limit and today's running total.

## Trade Intent Flow

Actual flow as of Phase 6 (paper trading):

```text
delta-engine                                    [proposes]
  → delta_intents row
  → dashboard human review (Trade Proposal tab)
  → human button click
  → api /trade/approve                          [thin proxy: UUID + idempotency]
  → trade-executor /jobs/submit                 [orchestrator]
      → load_intent
      → size_order
      → risk-service /check                     [→ risk_decisions row]
      → record alpaca_orders                    [→ audit row, always]
      → POST Alpaca /v2/orders                  [only if approved + credentials]
```

`intraday-monitor` will become a second producer of trade intents once built. The
risk-service interface is designed so both producers go through the same gate.

## LLM Restrictions

The LLM may suggest risk rules, but it cannot bypass or weaken enforced safety limits at runtime.

## Initial Trading Mode

Use Alpaca paper trading only until:

```text
strategy config is validated
backtest results are acceptable
paper trading behavior is reviewed
risk-service tests pass
trade-executor tests pass
human approval is enabled
```

## Auditability

Every signal, decision, and order should be traceable:

```text
strategy config
input data timestamp
signal trigger
risk decision
order request
order result
fill result
```
