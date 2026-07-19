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

### Per-control isolation & fail-closed on DB error

The DB-dependent controls (sync-staleness, data-staleness, daily-loss,
max-positions, max-position-pct) each run in their **own** `try/except`
(`_control_error`), not one shared block. On a query error:

- **Opening risk** (`entry` / `buy_add`) fails **CLOSED** — the trade is rejected
  with a control-specific rule name (`<control>_unavailable`, e.g.
  `max_positions_unavailable`), never a silent approve.
- **Closes** (`exit` / `sell_trim`) are **EXEMPT** — a control outage can never
  trap us in a position.

Isolation matters because a single defect previously aborted *all* controls and
rejected every entry with a generic "Safety control unavailable" — which is
exactly what a `run_date = :sim_date` type mismatch in the max-positions query
did in production (asyncpg infers a bare `= :date` placeholder as DATE and
rejects an ISO string). Now the failure is contained and names the culprit, and
the remaining controls still evaluate.

Testing note: the risk-service unit tests use a mock engine that never executes
SQL, so query-level defects are invisible to them. `tests/risk_service/
test_max_positions_sql_pg.py` drives the **real** `_decide` against an ephemeral
**Postgres** so every control's actual SQL is exercised in CI.

## Implemented Safety Controls (Phase 6)

These are actually enforced in code today.

```text
KILL_SWITCH              — if active, risk-service rejects all checks (see hot-flip below)
LIVE_TRADING_ENABLED     — must be "true" for trade_type=="live" to pass; default "false"
PAPER_ONLY               — when "true", any live trade is rejected; default "true"

trade_type is DERIVED FROM THE ENDPOINT by the trade-executor
(trade_type_for_base_url): "live" iff ALPACA_BASE_URL's host is
api.alpaca.markets (the only endpoint that can reach real money); paper-api,
the alpaca-sim harness, and anything else stay "paper". It was previously
hardcoded "paper" on every risk check, which made the two gates above
decorative — pointing ALPACA_BASE_URL at the live API traded real money
through the paper-labeled path. Going live is now a deliberate two-key turn:
switch the URL *and* set LIVE_TRADING_ENABLED=true + PAPER_ONLY=false, or the
risk-service rejects every order.
MAX_ORDER_NOTIONAL       — default $50,000 per order; SCALE-AWARE: effective cap =
                           max(MAX_ORDER_NOTIONAL, MAX_ORDER_PCT × account_value), so a
                           grown account keeps rotating instead of silently rejecting
                           every entry once weight × equity exceeds the fixed dollar cap
MAX_ORDER_PCT            — default 0.20 (20% of account_value); the scale-aware leg of
                           the order-notional cap above. Set 0 to revert to absolute-only.
                           Nuance (deliberate, fail-open on the SELL side only): if the
                           account-value DB read fails while an order exceeds the absolute
                           cap, a BUY is rejected (cannot verify the pct leg) but a CLOSE
                           (full exit) is allowed through — de-risking must never be
                           blocked by a telemetry outage, same philosophy as the is_close
                           exemptions elsewhere in this file.
MAX_DAILY_TURNOVER_PCT   — default 0.50 (50%); per-day sell-side cap (see below)
MAX_DAILY_LOSS_PCT       — default 0.10 (10%); halts ALL trades after a daily drawdown
MAX_POSITION_PCT         — default 0.15 (15%); per-ticker concentration cap on buys
MAX_POSITIONS            — default 35; refuses new entries when the PROJECTED post-rotation book (held − queued exits + queued entries) reaches cap
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

### MAX_DAILY_TURNOVER_PCT — discretionary-trim daily cap

Rejects a **`sell_trim`** once today's cumulative `sell_trim` notional plus this
order would exceed `account_value × MAX_DAILY_TURNOVER_PCT`. Default is 0.50.
**`exit` is EXEMPT** (F1): a full close — a de-risking exit or a builder-dropped
rotation — must never be throttled, and an exit doesn't run the turnover query or
count toward the budget. Entries and buy_adds aren't counted either (they deploy
idle cash, not churn). So the cap now bounds only DISCRETIONARY trimming.

Why exits became exempt: exits were formerly counted AND capped. The delta engine
(planner) does not model turnover, so on a big rotation — which is mostly exits —
it would emit more exits than the cap allowed, the gate rejected the overflow
("failed" rows), and the rotation silently completed over several days. That is
the same planner/gate-divergence class as the capacity bug. Exempting exits both
removes the divergence and honors the policy that a close is always allowed; only
`sell_trim` (genuinely discretionary) remains capped, and a single build rarely
trims more than the cap.

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

Refuses `entry` when the **projected post-rotation** book would reach
`MAX_POSITIONS` distinct tickers (default 35) AND this entry is for a ticker
not currently held. `buy_add`, `exit`, and `sell_trim` are not affected (none
of them grow the distinct-ticker count). Acts as defense in depth alongside the
portfolio-builder's `max_positions` config — if a misconfigured strategy or bug
ever generated entries past the cap, this gate blocks them.

Set `MAX_POSITIONS=0` to disable.

**Projected count (net-the-rotation), not the raw broker book.** The gate counts:

```text
projected = held_distinct                            (latest successful alpaca-sync)
          − held names being EXITED this cycle        (on their way out)
          + queued NEW-ticker `entry` orders          (on their way in)
```

clamped at 0. "Queued" = any of `pending, submitted, deferred, accepted, new,
partially_filled` (mirrors trade-executor `OPEN_ORDER_STATUSES`).

"Being exited this cycle" is detected from **two OR'd sources**:
- a queued `exit` **order** (one of the open statuses above), **OR**
- an `exit` **intent** in the latest `delta_runs` row for `sim_date` (the run the
  entry belongs to; `sim_date` = its `delta_runs.run_date`, passed by the
  trade-executor) — read from `delta_intents`.

The intent source is required because of a confirmed **ordering race**: the
after-close auto-approve does **not** submit all exits strictly before entries, so
an entry checked early in the pass sees zero deferred exit *orders* and — with
order-only netting — computes the full pre-rotation count, rejects, and (since
auto-approve never retries a `risk_rejected` row) stays wedged even after the exits
later defer. Prod evidence: entries stamped "42 projected positions" at check time
while a later snapshot showed `held=42, held_exiting=33`. Exit **intents** exist the
instant the delta step completes (before any approval), so netting them is
order-independent. When `sim_date` is absent (cold-start / manual without a run) the
intent subquery is empty and only the order source applies.

**Why netting is required (design decision — full-rotation wedge, 2026-06-16).**
All chain orders are `day` orders queued for the same market open, so the exits
and entries settle together. Counting the raw broker book instead self-wedges any
rotation: a strategy switch that holds 42 names and builds a 30-name target emits
34 exits + 22 entries; the raw count sees `42 ≥ 35` and rejects *every* entry,
even though the post-open book is only 30. The portfolio could then never rotate
unattended — exactly the manual-cleanup scenario the system is meant to avoid.

The exits are in `deferred` (not `pending`) at entry-check time: the after-close
cron approves sells **first** (executor Step 4 risk-check → Step 5b drain routing
flips them to `deferred`), then risk-checks the entries while `live_positions`
still shows the full pre-rotation book. So the netting **must** match `deferred`.

This is the count-axis twin of the buying-power netting in trade-executor
`_size_partial` (exits free cash at the same open, so entries size against
`account_value`). Execution-time over-commit remains backstopped by the drain's
fill-gate + buying-power check, so an optimistic projection can never actually
over-fill the book.

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

### Duplicate-order guards (trade-executor)

The root issue these guards address: **`delta_intents` ids are re-minted on every
delta run**, so a re-run (manual RUN / scheduler) re-proposes the same trades under
fresh `intent_id`s. The Step-1 idempotency check is keyed on `intent_id`, so it
does NOT catch a re-proposed trade from a new run. The durable thing that must be
unique is the economic action — **ticker + side per trading session** — so the
guards below re-key on that instead.

Sell side — stops the same position being sold twice (the cause of
`Alpaca: insufficient qty available for order (available: 0)` rejections):

| Failure mode | Guard | Step |
|---|---|---|
| Position **already closed** (sell filled), but a stale proposal resizes from an old sync | `_size_exit` scopes to the **latest successful sync run** and refuses (409) when the ticker is not held (qty>0) | size_order (`e4511d1`) |
| Position **still held** but its sell is **unfilled** (shares reserved at broker → available 0), and a **new delta run** re-proposes the exit under a new `intent_id` | `_open_sell_order_for_ticker` — before any sell-side submit, skip (`status="duplicate"`) when an **open** (`pending`/`submitted`/`deferred`) **sell** order already exists for the ticker from a different intent | Step 2c, `inflight_sell_check` |

Buy side — stops the same position being bought twice (a doubled entry):

| Failure mode | Guard | Step |
|---|---|---|
| Position **filled and held**, but a **new delta run** re-proposes the entry before alpaca-sync captured the fill | `_is_already_held` — block `entry` (`status="failed"`) when the broker already holds the ticker | Step 2b, `already_held_check` |
| Buy order **submitted but not yet filled** (e.g. a day order queued after the close — never fills until the next open, so the position stays un-held and Step 2b can't see it), and a **new delta run** re-proposes the entry/buy_add under a new `intent_id` | `_open_buy_order_for_ticker` — before any buy-side submit, skip (`status="duplicate"`) when an **open** (`pending`/`submitted`/`deferred`) **buy** order already exists for the ticker from a different intent | Step 2b2, `inflight_buy_check` |

Deferred-order purge (target is source of truth) — every delta run supersedes the
prior cycle's **un-sent** orders. The scheduler calls trade-executor
`POST /jobs/cancel-deferred` immediately before each `delta` step (cron, run-now,
and manual paths), flipping all `status='deferred'` rows to `canceled`. Deferred
orders were approved but never sent to Alpaca (no `alpaca_order_id`; the fill-gated
drain would submit them at the next open), so this is a **local-only** cancel — no
broker call, no execution risk. Without it, a leftover deferred order from an
earlier run (e.g. after a config change like raising `orphan_confirmation_days`, or
any same-session re-run) would (a) **fire stale at the open** and (b) **block the
new delta from re-queueing the correct decision** (the in-flight guards above treat
`deferred` as an open order). NOTE: `/jobs/cancel-all-orders` does NOT cover
`deferred` (its `open_statuses` are broker states only) — `cancel-deferred` is the
dedicated un-sent purge; the two are complementary (broker cancel vs local purge).

Sell and buy guards are mirror images, each scoped to its own `side` (an open
`buy_add` never blocks a sell, and vice versa). Together with the dashboard's
order-status join (re-keyed on **ticker + side + `run_date`**, not `intent_id`, so
a re-run's fresh intents resolve to the order already placed today and drop out of
the approvable set), they make re-running the chain idempotent at the
economic-action level — you cannot stack a second order for a ticker already
actioned this session.

### Atomic approve-and-reserve (cross-intent capacity race)

**Audit finding #8.** Risk approval and the local creation of the reservation
(the committed `pending` `alpaca_orders` row) are **not** atomic across *different*
intents. The trade-executor's submit flow is:

```text
risk-service /check   →   record_order (INSERT alpaca_orders, status='pending')
```

The reservation row is recorded **after** the risk-check returns. Risk-service
already counts committed pending `alpaca_orders` rows (statuses in
`OPEN_ORDER_STATUSES`) and `delta_intents` as reservations in BOTH the
`MAX_POSITIONS` projected-count SQL and the `MAX_DAILY_TURNOVER_PCT` sum — so a
committed pending order row **is** the reservation. The defect is purely one of
**ordering**: two concurrent submits for two *distinct* new-ticker entries can both
run `/check` before *either* has committed its `pending` row, so neither sees the
other's reservation, both pass the same `MAX_POSITIONS` / position-pct / turnover
gate, and both commit — breaching the cap by one (or more, under N-way concurrency).

**Why per-intent idempotency did not cover it.** The existing idempotency guard
(`idx_alpaca_orders_intent_open` unique index + the Step-1 check) is keyed on
`intent_id`. It prevents the **same** intent from reserving twice. The capacity
race is between **different** `intent_id`s competing for the same scarce capacity
(a free position slot, a turnover budget), so a per-intent key cannot serialize
them. The duplicate-order guards above (`ticker + side`) close same-ticker double
orders but not the multi-distinct-ticker capacity breach.

**Design — Postgres advisory lock per (account, trading_day) around
[risk-check → reserve].** The trade-executor (NOT risk-service) serializes the
critical section so a waiting submit only proceeds *after* the prior submit has
committed its reservation, and therefore its `/check` sees that reservation and is
correctly rejected at capacity.

```text
acquire advisory lock(account, trading_day)        ← BEFORE risk-check
    risk-service /check
    record_order (INSERT alpaca_orders 'pending'/'risk_rejected', COMMIT)
release advisory lock                               ← in finally
```

- **Key.** A stable 64-bit hash of `f"trade_submit:{account}:{trading_day}"`, passed
  to `pg_advisory_lock`/`pg_try_advisory_lock` (single-bigint form). `account` is the
  Alpaca account (single-account system → a fixed constant derived consistently);
  `trading_day` is the **same** day the risk/turnover scoping uses — `sim_date` when
  the intent carries one, else the executor's local `CURRENT_DATE`. Different
  accounts or different days hash to different keys and so **do not block each
  other**; same account + same day serializes. (Different days must not serialize —
  a compressed harness simulation processes many sim-dates and must not globally
  block; and a real new session must not wait on yesterday.)
- **Reservation = committed pending order.** The lock is held across the risk-check
  AND the reservation INSERT/commit. The reservation is exactly the existing
  `record_order` writing a `pending` (approved) or `risk_rejected` row — no new
  table. Because the lock spans both, by the time a waiting intent acquires it the
  prior intent's `pending` row is committed and visible to the next `/check`.
- **Bounded acquisition (no deadlock on a hung risk call).** Acquisition is
  bounded — `pg_try_advisory_lock` in a short retry loop with a total timeout
  (`SUBMIT_LOCK_TIMEOUT_SECS`, default 30s). A hung risk-service holding the lock
  must not wedge *all* submits forever. **On timeout the submit fails CLOSED**: it
  records the `alpaca_orders` row as `status='failed'` with a clear reason
  (`submit_lock_timeout`) and **does NOT submit to the broker**. (Failing open —
  submitting without the serialized capacity check — would re-introduce the very
  race this fix closes.)
- **Dedicated connection.** The advisory lock is held on its **own** connection
  across the whole section; the reservation INSERT/commit runs in a separate
  `engine.begin()` transaction. Session-level advisory locks are independent of data
  transactions, so the reservation can commit while the lock is still held — what
  matters is the strict order: lock acquired → `/check` → reservation committed →
  unlock. The executor pool is bumped so a lock-holding submit always has a second
  free connection for its reservation insert (it must never starve itself).
- **Scope.** Applied to **every** path that runs risk-check then records/submits an
  order: the immediate per-click submit, the deferred-submit re-check path, and the
  drain submit path — all via one shared `_with_submit_lock(account, trading_day)`
  async context manager.
- **Additive, not a replacement.** The per-intent unique-index/idempotency guard is
  unchanged; the advisory lock is the *cross-intent* serialization layer on top.
- **Risk-service is unchanged.** Its counting logic (projected-count SQL, turnover
  sum) already treats a committed pending order as a reservation. The fix only
  changes *ordering* in the trade-executor so that reservation is visible to the
  next checker. No risk-service code is touched.

This is deliberately a **defer/serialize** trade-off: under heavy concurrency
submits are processed one-account-day-at-a-time (each is a sub-second DB section),
in exchange for the cap being a hard invariant rather than a best-effort check.

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
