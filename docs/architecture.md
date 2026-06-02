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
at_risk   — held, exit not yet confirmed: either rank > exit_rank (in-target name
            deteriorating) OR an orphan counting down its build-confirmation window
exit      — held + confirmed: in-target name with rank > exit_rank for
            confirmation_days, OR an orphan absent from the target for
            confirmation_days consecutive builds (orphan exit is rank-independent)
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
spend cash the account doesn't have (`_allocate_capacity` / `_cap_buys` in
`services/pipeline/app/engine.py`, both pure and unit-tested):

- **Capacity gate (position count, entries only):** `retained_held + kept_entries
  ≤ max_positions`. Best-ranked entries fill the free slots; the rest are demoted
  `entry → watch` with reason "deferred — portfolio at capacity". `buy_add`s
  don't add positions, so they are exempt. Instant orphan rotation is RETIRED:
  this gate never force-exits a held position — a deferred entry WAITS for an
  orphan to time out (see orphan exit below). The realized book may therefore
  transiently exceed `max_positions` while orphans count down, then converge to
  the cap as they confirm.
- **Buying-power gate (cash, entries + buy_adds share one budget):** kept buys
  are funded best-ranked-first against
  `available = buying_power/account_value + exit proceeds + sell_trim proceeds`.
  Sell-side proceeds are credited so a same-open rotation (an orphan-timer exit
  funds a new entry) still works at ~0 buying power. Unfunded buys are demoted:
  `entry → watch`, `buy_add → hold` (keep the position, defer the top-up). Only
  enforced when `account_value > 0` and `buying_power` are supplied; otherwise
  the trade-executor and risk-service remain the cash backstop.
- **Orphan exit (target is binding):** a position the builder dropped from the
  target is exited once it has been absent for `confirmation_days` consecutive
  builds (`target_history`), regardless of rank — so a strategy change reaches the
  realized book instead of a well-ranked orphan lingering forever. Until confirmed
  it is `at_risk`. In-target holds are never force-sold here; no-data orphans
  (rank 9999, missing from the ranking universe) are never force-sold at all.

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

**How.** From the **raw** (pre-shrinkage) correlation matrix — `build_covariance`
returns it alongside the shrunk covariance — we form clusters by single-linkage
union-find: tickers A and B are in the same cluster when
`|corr(A,B)| ≥ cluster_correlation_threshold` (default **0.70**). The raw
correlation is used deliberately: clustering off the *shrunk* covariance would
deflate every off-diagonal correlation by the shrinkage factor and split genuine
co-movers into singletons (e.g. gold miners correlated 0.79–0.92 read 0.63–0.74
after 0.20 shrinkage, mostly falling below 0.70).
Those cluster labels are then fed into the *existing* group-cap machinery — the
same greedy count cap (`greedy_select`) and post-build weight redistribution
(`compute_weights`) that previously consumed sector labels. No new constraint
solver: the cluster is just a different grouping passed to proven code.

**Settings** (`PortfolioBuilderConfig`):

```text
cluster_correlation_threshold  default 0.70  — |corr| at/above which two names cluster
max_cluster_weight             default 0.15  — max summed portfolio WEIGHT per cluster (risk cap)
max_tickers_per_cluster        default None  — max NUMBER of holdings per cluster (count cap)
```

**Two caps, complementary.** `max_cluster_weight` bounds a cluster's contribution to
portfolio *risk* (its summed weight); `max_tickers_per_cluster` bounds the *number*
of names from a cluster. They are not redundant under non-equal weighting
(`adj_score_proportional` etc.): the weight cap is enforced post-build by
`compute_weights` (scaling over-cap clusters down), while the count cap is enforced
during `greedy_select` (skip a candidate once its cluster is full). Both apply;
whichever binds first wins. The count cap is an *absolute* count, independent of the
weighting scheme and `max_positions` — unlike the weight cap's selection-stage
`count/target` proxy, which assumes count≈weight. `max_tickers_per_cluster=1` =
at most one name per cluster (max diversification); `None` disables it. Singletons
(no correlated peer) are unaffected — only multi-member clusters are thinned. The
active strategy sets it to **3** (hold the top ~3 names of a theme, no more).

A 15% cap implies the portfolio spans **at least 7 effectively-independent
clusters** (⌈1/0.15⌉) to be fully invested, preventing a single correlated theme
(e.g. "the golds") from dominating even when its members hold the top ranks.

**Sectors are retained for logging only** — per-sector weights are still computed
and surfaced in the trace/`portfolio_runs` for human readability, but they no
longer gate selection or weighting. Setting `max_cluster_weight = 1.0` disables
the cluster cap (mirrors the old `max_sector_weight = 1.0` no-op).

### Sub-decision: cluster on the full universe, apply drawdown/vetter exclusions AFTER

Correlation clustering is a **structural property of the investable universe**;
a drawdown (or vetter) exclusion is a **per-ticker tradeability overlay**. These
live at different layers and must be applied in that order:

```text
1. load top-N candidates
2. drop do-not-buy + apply universe filters (min_price, min_avg_dollar_volume)
     → defines the INVESTABLE UNIVERSE (these names genuinely can't be traded)
3. build covariance + correlation CLUSTERS on that whole universe
     → cluster identity is fixed here, including drawdown-excluded names
4. drop drawdown/vetter exclusions from the SELECTABLE pool only
     → excluded names are never bought, but keep their cluster membership
5. greedy select + weight, capped by max_cluster_weight
```

**Why the order matters — the bridge-fragmentation hole.** Clusters are formed by
**single-linkage**: A–B–C chain into one cluster even when A and C correlate only
weakly, *as long as B bridges them* (A–B and B–C each ≥ threshold). If a
drawdown/vetter exclusion removes a name **before** clustering and that name was a
bridge, the cluster fragments into singletons. Drawdown exclusions specifically
fire on falling knives — which, in a *correlated theme selloff* (the golds all
crashing together), remove some members of the cluster. If the removed members
were bridges, the surviving correlated names split into separate "clusters" and
**escape `max_cluster_weight` — at exactly the moment the cap is most needed.**
Clustering the full universe first preserves linkage *through* the excluded
bridge, so the cap still binds on the survivors.

Over-grouping is the safe direction: correlation geometry is structural and
persistent, whereas a drawdown is temporary (it heals, and the same veto blocks
re-entry until it does). Treating A and C as one theme because B links them is the
conservative choice — under-grouping is the dangerous failure mode, not
over-grouping.

**Necessary nuance — data-quality drops stay BEFORE clustering.** "Full universe"
means *all top-N candidates with a usable price series that pass the universe
filters*. Names dropped for **no price / insufficient observations** have no
return series and genuinely cannot be clustered; names below `min_price` /
`min_avg_dollar_volume_20d` are not in the investable universe at all. Only the
drawdown/vetter exclusion — which is per-ticker and whose names *do* have prices
(drawdown is computed from them) — moves to step 4. A falling knife that has also
crashed below `min_price` is filtered at step 2 as a universe matter, not a
drawdown one.

This also makes the persisted `candidate_clusters` map (the screener overlay)
cover every ranked candidate including excluded ones, which is what that table is
meant to represent.

## Design Decision: scheduler is the single, FRESH source of chain-progress truth

**Problem (root cause of a family of UI bugs).** The dashboard's
`/api/pipeline-status` reconstructed "which step is running / what's the progress"
by *blending* four non-atomic sources fetched in one `asyncio.gather`: the
scheduler `/status` step map, the pipeline `factor/ranking/delta` sub-status
columns, each service's `/runs/latest` row, and av-ingestor's in-memory progress.
These flip between running/terminal independently, so the blend raced. The
symptoms were all one bug: a fresh proposal still showing "Evaluating Signals",
no fetch %, the RUN button re-enabling mid-chain, the auto-approve countdown
suppressed, and "LLM ANALYSIS" shown even with the vetter LLM disabled.

The deeper cause: the scheduler IS the chain state machine, but `/status` returns
the in-memory `_chain_status` which is only refreshed on the supervisor tick —
every `SUPERVISOR_INTERVAL_SECS` (**300 s**) on the cron path. So during the
after-close chain the authoritative state was **up to 5 minutes stale**, and the
dashboard's blend existed only to paper over that. A *manual* run uses a 3 s fast
loop, so its state was fresh — which is exactly why every symptom reproduced on
the cron chain but not on a manual run.

**Decision.**
1. **The scheduler state stays fresh while a chain is active.** Whenever a chain
   is in flight (cron OR manual), a single fast-drain loop ticks the supervisor
   every `FAST_TICK_SECS` (default 5 s) until the chain reaches a terminal state,
   then stops. The 300 s interval becomes just the heartbeat that *starts/notices*
   a chain; once active, the fast drain keeps `_chain_status` current. Guarded so
   only one drain runs (`_supervisor_tick` already no-ops if `_chain_lock` is held).
2. **The dashboard renders the scheduler's state verbatim.** When the scheduler is
   reachable its step map is the SOLE authority for phase/running — a single pure
   function (`derive_pipeline_phase`) maps it to the UI fields. The old blended
   inference is kept ONLY as the fallback for when the scheduler is unreachable.
   The fetch-data % (from av-ingestor) and the vetter's `llm_enabled` flag are
   layered on as presentational detail keyed off the authoritative phase — fixing
   the two gaps where the override previously dropped the fetch % and hardcoded
   the vetter label.
3. **Labels.** The vet phase is labelled **"Vetter"** (not "LLM ANALYSIS" — the
   vetter runs as a step even in drawdown-only mode with the LLM disabled, so an
   "LLM" label is misleading). The delta phase is labelled **"Delta Eval"** (not
   "Evaluating Signals").

This collapses the whole symptom family because there is exactly one fresh,
authoritative source and the UI renders it rather than re-deriving it.

## Design Decision: fill-gated market-open order draining (Option B)

**Problem.** The chain runs after the close and approvals (manual or the 60-min
auto-approve) submitted Alpaca `day` orders *immediately*. Those orders queue for
the next open, but Alpaca validates **buying power at submission time, per order**
— proceeds from a not-yet-executed sell do not raise buying power. On a
fully-invested account a queued buy is therefore rejected with *insufficient
buying power* even though, at the open, the sells would have funded it. Submitting
a whole batch at once post-close races buys ahead of their funding sells.

**Decision.** Approval no longer submits. It **enqueues**. A single background
**drain** in the trade-executor is the only thing that submits to Alpaca, and it
does so **only during market hours**, **sells-first**, **fill-gated**, **one buy
at a time**:

```text
approve (manual / auto)
  → trade-executor sizes + risk-checks the intent
  → records alpaca_orders row status='deferred'  (= "queued for open")
     deferred_until = next market open, expires_at = that session's close
  → NO Alpaca submission yet

drain worker (every DEFERRED_WORKER_INTERVAL_SECS):
  GET /v2/clock
  if not is_open → mark any deferred order past expires_at 'expired'; sleep
  if is_open:
    1. submit ALL deferred SELLS (exit / sell_trim) not yet submitted
    2. wait (across passes) until EVERY submitted sell is FILLED
       — proceeds are now credited to buying power
    3. for each deferred BUY, oldest first, ONE at a time:
         GET /v2/account → live buying_power
         if order notional <= buying_power: submit, wait for fill, next
         else: leave queued, retry next pass
    4. any buy still unfunded at expires_at → 'expired'
```

**Why these choices.**
- *Sells fully filled before any buy* (not incremental release): simplest correct
  form and matches "one order at a time". Market sells fill within seconds of the
  open, so the latency cost is small; the alternative interleaves partial-fill
  accounting for marginal speed-up.
- *Unfunded buys expire at close* (not carried over): the next daily chain rebuilds
  a fresh, holdings-agnostic target and re-proposes the name if still wanted.
  Carrying a stale order risks acting on a target the next build already changed.
- *Drain lives in trade-executor, not the scheduler*: trade-executor is already the
  ONLY service with order-submission credentials and already owns `_submit_for_action`
  and the (previously unwired) `deferred` worker. Keeping the drain there preserves
  "only trade-executor submits orders" and avoids a new market-hours scheduler path.
- *Buying-power gate uses a live `GET /v2/account`*, re-fetched before each buy, not
  the cached `alpaca_sync` snapshot — the gate must see cash credited by sells that
  filled seconds ago.

**Status lifecycle** (`alpaca_orders.status`): `deferred` (queued for open) →
`submitted` → (broker) `filled`; or `risk_rejected` at enqueue; or `expired` if a
buy can't be funded by its session close; or `failed` on an Alpaca error. The
`deferred` status, `deferred_until` column (migration 0008) and the worker already
existed but were never wired — approval always went `pending → submit`. This
decision wires them and adds the sells-first + fill-gate + buying-power logic.
`expires_at` is added (migration 0015) for deterministic, restart-safe expiry.

**Approval = greenlight, drain = authority.** Risk-check still runs at approval for
fast human feedback, and the kill switch is re-checked at submit. The buying-power
gate is the drain's own pre-submit check. All state lives in `alpaca_orders`, so
the drain is stateless across restarts — each pass re-derives what to do from the
row statuses.

**Trade-off accepted.** Orders execute intraday at live prices a few seconds/minutes
after the open, not in the opening auction. This is deliberate: predictable funding
and no insufficient-buying-power rejects, in exchange for not capturing the auction
print. `mode='immediate'` on `/jobs/submit` still submits inline (single manual
override / tests); the dashboard's batch "Approve Selected" now enqueues
(`mode='scheduled'`) so the drain sequences it.

## Design Decision: vetter drawdown-only mode + ranker drawdown indicator

The LLM vetter can be put into a **drawdown-only mode** (`VETTER_LLM_ENABLED=false`)
in which it skips all LLM / Tavily / Alpha-Vantage-news work and every candidate
defaults to *keep*. The deterministic falling-knife backstop
(`DRAWDOWN_BACKSTOP_PCT`, default 0.15 — force-exclude ANY candidate, held or not,
more than X% below its 21-day peak) becomes the **only** exclusion signal.

**Why a mode, not a chain change.** The vetter step stays mandatory and
portfolio-builder still requires a successful `vetter_run` for today's ranking.
Drawdown-only mode keeps that wiring intact — a `vetter_run` row is still written
and its (drawdown-driven) exclusions still feed portfolio-builder — so disabling
the LLM is a single reversible env flip with no change to the chain shape or the
409 gate. A held name excluded on drawdown is dropped from the fresh target and
orphan-exited by the delta engine after `confirmation_days` builds (source-of-truth
redesign); data-gap names with no recent prices are exempt.

**Ranker drawdown indicator (display-only).** The pipeline computes each ranked
ticker's 21-day peak-to-now drawdown and stores it in `rankings.factor_scores`
JSONB under `drawdown_21d`. It is **not** a scoring factor — it never enters
`rank_universe.compute_score` (which consults only the six `FACTORS`), so rank
order is unchanged. The screener shows a ▼ badge from -10% (red at -25%, matching
the backstop default) purely for human visibility. The same 21-day window is used
by the vetter backstop so the badge agrees with the entry block.

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

## Design Decision: scheduler is the single source of truth for chain progress

**Problem.** The dashboard's `/api/pipeline-status` reconstructed "what step is the
chain on?" by polling 5+ services (`api`, pipeline `/runs/latest`, pipeline
`/runs/progress`, av-ingestor `/runs/latest`, scheduler `/status`) and inferring the
current step through a ladder of `if/elif` precedence rules. Because those services
are read near-simultaneously but each flips its own state at slightly different
moments — and each `/runs/latest` returns the *last* run with no "is this the chain
I just started?" marker — a single poll routinely observed two sources mid-transition
that disagreed. The precedence rules then picked the wrong one for that poll,
producing visible flicker: a stale prior vetter run flashing "LLM ANALYSIS" before
factors; the label alternating Factors↔Ranking during the factors→ranking handoff.
Each was patched with a targeted guard (`confirmed_terminal`, `_rank_chain_running`,
per-step scheduler gates), but that is whack-a-mole: N independent sources ×
transition windows = a whole class of races, only the surfaced ones get fixed.

**Decision.** The **scheduler is the authoritative state machine** for the daily
chain — it is the component that actually advances the steps
(`fetch-data → pipeline → vet → portfolio-builder → delta`) and already tracks each
step's state (`idle/running/done/failed`) plus chain status and origin in
`_chain_status`, exposed verbatim at `GET /status`. The dashboard derives the
top-level chain step **from the scheduler's step map alone**, rather than blending
independent per-service run rows.

```text
scheduler /status.steps  →  authoritative top-level step + status
pipeline /runs/progress  →  sub-detail ONLY (factors/ranking/delta + pct) WITHIN
                            the scheduler's "pipeline" step — never its own label
per-service /runs/latest →  dates / terminal results for idle display only;
                            never used to claim a step is "running"
```

**Why the scheduler, not the pipeline.** The scheduler is the only component with a
total view of all five steps and their ordering. The pipeline only knows its own
sub-steps, so its `factor_status`/`ranking_status` and `/runs/progress` become a
*zoom-in* on the scheduler's `pipeline` step (which sub-phase + percent), not a
competing source of the top-level label. Steps are monotonic
(factors→ranking→delta), so when several pipeline sub-statuses momentarily read
`running` the furthest-along one wins.

**Consequences.**
- One reader, one writer for chain state → the class of cross-source races
  disappears; the scattered precedence guards collapse into "trust the scheduler."
- When the scheduler is **not** driving (manual single-step calls like `/jobs/vet`,
  or the scheduler unreachable), the dashboard falls back to per-service run rows as
  before — manual operations still surface.
- The scheduler's `/status` stays the contract; the dashboard's
  `/api/pipeline-status` response shape (the `universe/rank/vetter/portfolio` blocks
  the frontend reads) is preserved so the JS is unchanged.

## Design Decision Rule

Whenever a design decision is made, it must be documented in the design docs before implementation begins.

This applies to: architecture choices, communication patterns, data ownership, safety rules, service boundaries, sequencing decisions, and any explicit choice between two or more reasonable options.

The docs are the source of truth for intent. If code diverges from the docs, update the docs or the code — not just a comment.
