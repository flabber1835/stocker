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

## Design Decision: builder/delta chain hardening (lineage + degraded gate)

Architecture delta on the ranking → vetter → portfolio-builder → delta chain. The
*vetter↔ranking↔builder* leg was already tightly bound (explicit seam guards,
mandatory vetter, per-run config reload). The weak seam was **delta**, which
re-resolved the ranking, portfolio, and vetter **independently** by "newest
successful row (by completed_at)" — relying on chain *ordering* for correctness
rather than enforcing the binding. Two failure clusters followed; this hardens both.

**G1/G7 — delta binds to the builder's lineage (the builder IS the source of truth).**
Delta now ANCHORS on the latest successful `portfolio_runs` row and derives its other
inputs from that row's back-pointers:
```text
port_run            = latest successful portfolio_run (the target to diff)
ranking it diffs    = ranking_runs[ port_run.source_ranking_run_id ]   (NOT "latest ranking")
vetter exclusions   = vetter_exclusions[ port_run.vetter_run_id ]      (NOT "latest vetter")
run_date            = that ranking's rank_date
```
So delta always diffs the portfolio that was built from the ranking it reads, vetted
by the vetter that built fed — by construction, not by timing. A manual pipeline run
that produces a newer ranking with no build yet can no longer make delta diff today's
book against a portfolio from a different ranking. The cold-start fallback (no
portfolio at all) still picks the latest ranking. Config skew is now **fail-closed**
for the delta step (`DELTA_FAIL_ON_CONFIG_SKEW`, default true): if the delta's
reloaded `config_hash` disagrees with the chain it's diffing, it refuses to emit trade
intents rather than acting on mismatched assumptions (this skew has actually occurred
— see the config-reload decision). Set the env false to revert to advisory-only.

**G2 — degraded-build gate (no silent thin target → no bad-data mass rotation).**
The builder builds a fresh holdings-agnostic target each day; a *transiently thin*
ranking (many factors momentarily NULL) used to yield a small but `status='success'`
target that the delta engine then diffed — orphan-exiting every dropped name after
`orphan_confirmation_days` (default 2). Because exits are exempt from
`MAX_DAILY_TURNOVER_PCT`, the orphan timer was the ONLY brake on a bad-data rotation.
Now `PortfolioBuilderConfig.min_selected` (default 0 = off) sets a floor: a build that
selects fewer names is still recorded `success` but flagged `portfolio_runs.degraded =
true`, and the delta engine treats a degraded target exactly like an EMPTY one —
hold the whole book, suppress the below-floor split — so a one-off thin ranking can
never mass-liquidate. (Fail-safe by HOLDING, never by selling.)

**G5 — supersede marker (unambiguous "latest").** Every build/delta mints a fresh
run row and downstream readers pick "latest by completed_at". On a re-run (manual +
cron for the same session) that left two success rows ordered only by timestamp. A
successful build/delta now stamps `superseded_at` on the prior success row for the
same lineage (builder: same `source_ranking_run_id`; delta: same `run_date`), so the
authoritative run is explicit.

**G6 — builder stale-running reclaim.** The builder runs in a BackgroundTask; an
in-request crash (e.g. OOM in universe-scale covariance) left a `running`
`portfolio_runs` row that 409-wedged ALL future builds until a restart. The
no-running-job check now reclaims a `running` row older than `STALE_BUILD_HOURS`
(default 3) as `failed` (mirrors av-ingestor's `STALE_INGEST_HOURS`), so the chain
self-heals without a restart.

**G8 — immutable config snapshot through the build.** `_reload_strategy()` reassigns
module globals (`strategy`, `config_hash`) under the job lock, but `_do_build` runs
detached afterwards and re-read those globals mid-build. The bound strategy +
config_hash are now captured into an immutable snapshot at trigger time and threaded
through `_do_build`, so a concurrent reload can never switch a build's assumptions
partway through (the persisted config_hash always matches the universe/strategy used).

**G3/G4 — invariant + snapshot integrity.** A contract test asserts the Python
capacity rule (`capacity.projected_book_count`) agrees with the risk-service
projected-positions SQL, so the "planner admits ⇔ gate approves" equivalence can't
silently drift. The delta reads broker positions and `account_value` from ONE pinned
`sync_run_id` instead of two independent "latest sync" subqueries (closes the torn-read
where positions came from sync A and account_value from sync B).

## Design Decision: pipeline-core hardening (determinism, degraded gate, integrity)

Architecture delta on the pipeline service's OWN engine (factor + rank steps and
`/jobs/run` orchestration) — distinct from the delta engine it also hosts. The core
finding: `success` was treated as binary, ignoring DATA QUALITY, and several
documented invariants (determinism, single-source factors, cross-step audit) were
guaranteed by prose rather than by construction.

**P1 — determinism enforced.** `rank_universe` sorted composites with pandas' default
(unstable) quicksort and **no secondary key**, so equal-composite tickers — realistic
with percentile/z-score inputs — got a nondeterministic relative rank → a different
top-N → a different vetter pool/portfolio across identical runs, violating "rankings
are reproducible". Now it sorts `["composite_score", "ticker"]` ascending `[False,
True]` with a STABLE `mergesort` (ties break alphabetically). Backed by
reproducibility tests (run-twice identity, input-order invariance, tie ordering) and
a factor-registry sync test (every `FACTOR_REGISTRY` name is actually produced by
`compute_all_factors` and matches the persisted columns — a registry-only factor that
would silently persist all-NaN now fails CI).

**P2 — degraded-ranking gate at the SOURCE.** A thin ranking (fundamentals outage, or
too few names clearing `min_non_null_factors`) used to be plain `success` and flow
downstream — the UPSTREAM root of the mass-rotation risk the builder's G2 only caught
at the symptom. Now `StrategyConfig.min_ranked` (default 0=off): a `ranked_count`
below it flags `ranking_runs.degraded` (migration 0035); the builder propagates that
into `portfolio_runs.degraded`; the delta engine already holds the book on a degraded
target. So `degraded factor set → degraded ranking → degraded portfolio → delta holds
the book` — gated where the bad data enters.

**P4 — cross-step integrity.** (a) The standalone-delta `delta_status` backfill now
targets the pipeline_run whose RANKING the delta consumed (`delta_runs.
source_ranking_run_id → pipeline_runs.ranking_run_id`), not "latest by started_at"
(which mis-attributed when a newer run started meanwhile). (b) `_format_pipeline_run`
no longer spoofs `run_date := chain_date` for a FAILED run (only a still-`running`
one), so a failed run can't surface today's date to the SESSION anchor. (c) A CI test
forbids any real step using the legacy `TODAY`/`TRADING_DAY` wall-clock anchors (the
`_StepDef` default), and the stale `start_run` docstring (claiming it runs delta) is
corrected.

**P5 — honest progress.** The eased progress bar already caps just below the next
milestone, but a hung step shows a frozen-but-nonzero value implying progress.
`/runs/progress` now also returns `stalled` / `stale_secs` (no real-milestone advance
for > `PROGRESS_STALL_SECS`, default 180) so the dashboard can label a stall instead
of a creeping bar.

**P6a — proportionate regime resilience.** The factor step hard-halted the entire
chain on a missing/short benchmark window — disproportionate, since with
`regime_weighting_enabled=false` the regime doesn't drive scoring at all. Now, when
weighting is OFF and at least one benchmark bar exists (for a score_date), it proceeds
with a sentinel regime `'unknown'` (safe: `effective_factor_weights` ignores the
regime when disabled) and a null-metric snapshot, instead of halting. With weighting
ENABLED, or no benchmark at all, it still halts (weights genuinely need the regime /
there is no run date).

**Documented contracts (deliberately not code changes):**
- **P6b — OOM headroom.** `PIPELINE_MEM_LIMIT` (default 2g) makes the factor step the
  predictable OOM victim; the crash-loop breaker turns a deterministic OOM into one
  visible suspension. The limit is a manual knob — on a growing universe (or
  `residual` momentum, which allocates extra arrays) raise it rather than letting the
  chain suspend daily. There is intentionally no automated headroom check yet.
- **P7a — the Redis `pipeline_events` consumer is a stream JANITOR, not a trigger.**
  The scheduler is the sole driver; the consumer only ACKs/drains the stream so it
  can't grow unbounded. It is NOT removed because producers (av-ingestor,
  portfolio-builder) still `XADD` to the stream — deleting the consumer without
  bounding the producers would leak memory. Treat it as a drain-only janitor.
- **P7b — single-worker contract.** The pipeline assumes ONE worker/replica: `_job_lock`
  (in-process) serializes `/jobs/run` vs `/jobs/delta` only within a process; the
  per-claim advisory lock guards only the claim, not execution, and uses distinct keys
  for run vs delta. Run exactly one pipeline replica. Cross-replica execution exclusion
  would require holding an advisory lock for the whole run — out of scope.

## Design Decision: av-ingestor hardening (slow-fetch, rate limit, durable progress)

Architecture delta on the data front of the chain. The "slow fetch / stuck on
calculating / UI says READY" symptom traced to three compounding causes, plus the
usual silent-degraded-success class at the data source.

**G1 — throttle circuit-breaker.** Under an AV throttle every one of ~6,600 tickers
retried 4× with 2/4/8s backoff (plus a second cleanup pass) → a multiplicative
wall-clock blowup (the slow fetch). `AVError` now carries a `rate_limited` flag; the
fetch loop counts CONSECUTIVE rate-limit errors and, past `AV_THROTTLE_CIRCUIT_BREAK`
(default 25), ABORTS the run. Coverage then falls below the floor → the chain-advance
gate withholds `session_date` → the scheduler retries next cycle when the budget has
recovered. Far better than grinding the whole universe.

**G3 — account-wide rate limiter.** The per-process sliding window rebuilt its budget
every run and was blind to other AV consumers (the LISTING path bypassed it; llm-vetter
is a second consumer), so the documented 75 rpm could be breached and a degraded day
re-ran the full fetch without the budget recovering. A shared Redis sliding-window
limiter (`shared/stock_strategy_shared/rate_limit.py`, atomic via a Lua script on the
Redis server clock) is now the account-wide source of truth, wired into every `AVClient`
and the LISTING path; it **fails open** on a Redis outage (the per-process limiter
remains the floor) so a Redis blip can't wedge ingestion.

**G2 — durable progress + watchdog.** Fetch progress was in-memory only, so a redeploy
mid-fetch froze the dashboard bar (stuck-READY). Progress is now checkpointed to
`ingest_runs.tickers_done/tickers_total` (migration 0036) and `/runs/latest` falls back
to it when the live counters are gone. And the scheduler's fetch-data step gains
`max_running_minutes=240` — a HUNG (not crashed) fetch is now coerced to failed and
re-triggered, where before it reported `running` forever and the 6h ingestor reclaim
never fired (the scheduler won't re-POST a `running` step).

**G4 — degraded as first-class status.** A withheld chain-advance was signalled only by
a NULL `session_date` while the row still read `success`. `ingest_runs.degraded`
(migration 0036) is now set whenever the gate withholds (low coverage / SPY didn't
advance / throttle abort), surfaced on `/runs/latest`.

**G8 — gap-force-full.** A `compact` fetch returns ~100 trading days; a ticker dormant
longer (e.g. a probation-readmitted name) would get a permanent hole. The loop now
forces a `full` fetch when the last DB bar is older than `AV_COMPACT_MAX_GAP_DAYS`
(default 130).

**G6 — LISTING resilience.** The universe fetch (the single most important AV call) was
a bare GET with no retry; a transient blip failed the whole `fetch-universe`. It now
retries transient failures (5xx/transport/in-band throttle) with the same exponential
backoff as the per-ticker client; a non-rate-limit key/plan body stays terminal.

**Documented contracts (deliberately not code changes):**
- **G5 — throughput.** The per-ticker loop is serial, but at 75 rpm the fetch is
  *rate-bound, not latency-bound*, so concurrency would only parallelize waiting — it
  doesn't speed a rate-limited fetch. The real levers are the circuit-breaker (G1) and
  warm-run skip-if-current (already present); resume is implicit (a re-trigger skips
  already-current tickers). No concurrency added by design.
- **G6 (raw payload) / news / macro.** Raw-payload persistence and AV NEWS_SENTIMENT /
  macro endpoints remain unbuilt; news is sourced via Tavily in llm-vetter. See
  docs/data-sources.md — the docs are reconciled to match the code rather than the code
  rushed to match the docs.
- **G7 — point-in-time fundamentals / survivorship.** `fundamentals.as_of_date` is the
  fetch date (overwrite-latest), and the universe keeps no delisting record — a known
  backtest-validity limitation (live trading uses latest data, so it's not a live-risk).
  Changing `as_of` to the fiscal period is a data-model change with factor-read
  implications and is deferred deliberately. `earnings` + `analyst_snapshots` ARE
  point-in-time.

## Design Decision: dashboard progress hardening (monotonic view)

Architecture delta on the UI. The progress bar jumped backwards ("vetter →
calculating factors", "100% → 99%") because the displayed phase is recomputed every
poll from ~8 unsynchronized, non-monotonic, resettable sources (scheduler `/status`,
pipeline `/runs/latest` + `/runs/progress`, av-ingestor `/runs/latest`, api panels)
with **no high-water mark anywhere** — not in the contract, the backend, or the
frontend. The fix is at the VIEW layer (display-only; no engine/trade change):

**U1/U6 — client-side monotonic phase latch (`dashboard.js:_latchPhase`).** Holds the
furthest-reached phase (and, within a phase, the highest pct) for the current run and
refuses to render a regression. Resets on a terminal state or a genuine new run (a
drop back to a FETCH phase while past fetch). This is the primary fix — it makes the
bar monotonic regardless of what the racing backend emits.

**U5 — single-flight polling.** An issue-sequence counter (`_pipelineSeq` /
`_pipelineApplied`) so a slower OLDER `/api/pipeline-status` response can't overwrite
a newer applied one (the 5s + 30s pollers were last-writer-wins).

**U6 — keep-last-good.** `loadDelta` no longer blanks `deltaData` on a failed poll
(was flickering the trader/holdings tab to "all clear").

**U8 — selection durability.** The multi-select + optimistic approval state reset ONLY
when the delta run changes (was wiped every poll/tab-switch), and the selection is
persisted to `localStorage` keyed by run so a refresh doesn't strand it.

**U2 — backend hold-last-good phase.** When the scheduler `/status` poll blips (times
out on one fan-out) the backend held the last scheduler-authoritative phase for
`SCHED_PHASE_HOLD_SECS` (default 45) instead of falling back to the divergent
per-service blended inference — reducing the flip at the source (the client latch is
the backstop).

**Scoped follow-ups (deliberately NOT done here — documented, not rushed):**
- **U3 — the dashboard directly initiates trades** (a server-side auto-approve loop
  POSTs `/trade/approve` on timers) and holds supervision state (`_rank_chain_running`,
  approval timers). This violates "dashboard is a stateless view that may *request*
  approval, not execute." Relocating auto-approve into the scheduler/risk domain is a
  trade-execution-path change with its own test surface — scoped separately rather than
  moved blind at the end of a display-layer batch.
- **U4 — pipeline `/runs/progress` is in-memory** (resets to `{}` between runs and on
  restart, unlike av-ingestor's durable checkpoint). The client latch + `_resolveRankPct`
  now hold last-good across a restart blip, so the visible symptom is mitigated; adding
  a durable pipeline-progress column (mirroring av-ingestor G2) is the follow-up if the
  latch proves insufficient.
- **U7 — the phase reconciliation is duplicated** (`derive_scheduler_phase` vs the inline
  blended fallback) and the step order is hardcoded in three places. A DRY pass is
  cosmetic and deferred.

The end state (target): the scheduler — the documented single chain driver — should
expose ONE authoritative, ordered, monotonic progress object with a high-water mark,
and the dashboard should render it verbatim. The client latch is the pragmatic
first step toward that; U3/U4/U7 move the rest of the way.

## Design Decision: scheduler hardening (watchdogs, no-regress, lineage skew)

Architecture delta on the orchestrator, driven by the incidents it caused (the
config-skew deadlock, the "stuck" states, done-step re-triggers). The scheduler's
core weakness was the same "coordinate via global-latest + no durable done-state"
pattern seen elsewhere, at the orchestration layer.

**SG1 — config skew is now a LINEAGE check, not a compare-vs-reloaded-config.** The
delta DIFFS the builder's target; it doesn't re-score, so its own freshly-reloaded
config is irrelevant to the diff. `_detect_lineage_skew(ranking_hash, portfolio_hash)`
(pure) checks only that the ranking and the PORTFOLIO the delta anchors on were built
under the SAME config. The old check compared each vs the delta's reloaded config,
which **false-deadlocked** the delta whenever the config file was edited AFTER a
perfectly self-consistent chain built (the `selection_vol_aversion` incident). Paired
with the builder's cross-config guard (ranking.config == portfolio.config by
construction), skew now only trips on a genuine old pre-guard cross-config lineage.
(This also removed the old `_detect_config_skew`, which queried the nonexistent
`vetter_runs.config_hash` column and threw `UndefinedColumnError` every run.)

**SG2 — `_step_state` no longer regresses a done step on a transport blip.** A non-200
(non-404) or exception used to return `idle`, which made the supervisor **re-trigger an
already-`done` step** (re-running fetch/pipeline, re-billing the vetter) whenever a
finished service momentarily blipped. It now HOLDS the last-known state
(`_hold_last_known`): a `done` step stays `done`, otherwise `blocked` (WAIT). A genuine
404 "no run yet" still returns `idle` so first triggers fire.

**SG3 — watchdogs on the pipeline (60m) and portfolio-builder (30m) steps.** These were
the only steps without `max_running_minutes`; a hung (not crashed) run reported
`running` forever and wedged the chain invisibly. Now they self-heal like fetch/vet/delta.

**SG6 — run-now closes the in-flight cron chain row** (`_db_close_run`) before dropping
the in-memory pointer, so a manual restart no longer orphans a `running` scheduler_runs
row that polluted `/health/chain` and audit until a future-session sweep.

**SG9 — the scheduled-time floor falls back to a conservative default (17:00 ET) on a
malformed cron**, instead of fail-OPEN (which disabled the floor entirely and let the
interval ticker fire the chain at any hour on prior-day data).

**Documented (deliberately not code changes):**
- **SG4 — run-now "ran too early → stale session"** is now mitigated by the av-ingestor
  chain-advance withhold (a fetch that finds no new AV data withholds `session_date`, so
  the SESSION-anchored steps stay not-done rather than scoring a stale session). run-now
  no longer manufactures a stale chain; it just waits for the data.
- **SG5 — bounded auto-retry on a genuine step failure** is intentionally NOT added.
  SG2 already absorbs transient TRANSPORT blips (they no longer surface as `failed`); a
  step whose service returns `status='failed'` is a REAL job failure that should halt
  fail-closed for inspection rather than blindly re-run an expensive/broken step
  (re-billing the vetter, re-OOMing the factor step). run-now provides the one manual retry.
- **SG7 (cancel-all barrier before delta + a bound on the fail-closed cancel-deferred
  wedge), SG8 (scheduler emits the single authoritative monotonic progress object —
  the UI-delta end-state), SG10 (`/health/chain` visibility of a currently-wedged
  chain; multi-day catch-up replays only the frontier), SG11 (single-instance
  contract / leader election)** — scoped follow-ups.

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

## Design Decision: portfolio-level volatility targeting (constant-vol crash control)

The portfolio-builder optionally scales **total invested exposure** so the selected
book's ex-ante annualised volatility is pulled toward a target — Barroso &
Santa-Clara (2015) constant-volatility momentum. Off by default
(`vol_target_enabled: false`); enabled on `momentum_rotation_v2`.

**Mechanism.** After weights are computed (summing to 1.0 = fully invested), the
builder measures the book's ex-ante vol `σ = sqrt(wᵀΣw)` (Σ = the annualised
covariance it already builds) and sets
`exposure = clamp(vol_target / σ, vol_target_min_exposure, 1 − cash_reserve)`,
then scales every weight by `exposure`; the remainder is cash. Pure helpers
`book_volatility` / `vol_target_exposure` live in `services/portfolio-builder/app/select.py`.

**Why.** The deep-research pass (momentum literature) found constant-/dynamic-vol
scaling is the single highest-Sharpe momentum crash control (Barroso–Santa-Clara:
Sharpe ~0.53→0.97, kurtosis 18→2.7; Daniel–Moskowitz: dynamic scaling ~doubles
alpha/Sharpe). It is the intended substitute for a heavy low-vol/value factor
*ballast* in the momentum-dominant rotation configs (v2/v3 cut those weights to
restore semis/leadership; this overlay re-supplies crash protection at the
portfolio level instead of the signal level).

**Properties / guardrails.**
- **Long-only, de-lever-only.** Exposure never exceeds `1 − cash_reserve`, so a calm
  book (recent runs ~7–8% vol vs a 12% target) stays fully invested — **no drag in
  normal markets**; it bites only when book vol exceeds the target (stress /
  correlation spikes).
- **Floor.** `vol_target_min_exposure` (default 0.30) caps how far it de-levers, so a
  vol spike can't dump the book entirely to cash; a validator rejects a floor above
  `1 − cash_reserve`.
- **Fail OPEN.** Degenerate vol (zero / NaN / no covariance overlap) returns
  max exposure rather than liquidating — a transient bad covariance matrix must not
  move the book to cash. Real per-name crash control still flows through the vetter's
  falling-knife veto.
- Complementary to, not a replacement for: the per-name falling-knife drawdown veto
  (reactive, idiosyncratic) and the correlation-cluster / sector / position caps
  (cross-sectional concentration). Vol-targeting governs **gross exposure over time**.

## Design Decision: portfolio-level market-beta targeting (risk-shaping overlay)

The portfolio-builder optionally reweights the invested book toward a **target
market beta** (`β_portfolio = Σ wᵢβᵢ`). Off by default (`beta_target_enabled:
false`, so weighting is exactly as before — fully reversible); enabled on
`momentum_rotation_v2` at `beta_target: 1.3`.

**Why a separate lever.** `selection_vol_aversion` (greedy) is an *indirect* dial —
it changes *which* names win, and empirically only nudged book beta (0.12 → 0.30
across successive cuts). Beta targeting is the *direct* lever: because portfolio
beta is **linear in the weights**, hitting a setpoint is a deterministic reweight
of the *already-selected* names, not a re-selection or a search. It answers "size
the book to a beta of X," which the selection knob structurally cannot.

**Mechanism** (`solve_beta_target_weights` in `services/portfolio-builder/app/select.py`).
Applied AFTER base weighting + caps, on the sum-to-1 relative weights, BEFORE
exposure scaling (so the target is on the invested composition; if vol-targeting
also de-levers, effective beta vs total equity is `exposure × beta_target`). A
single-parameter **exponential (Boltzmann) tilt** `raw_i = w_base_i · exp(λ·βᵢ)`
is renormalized under the position cap (water-fill, `_cap_normalize`) and λ found by
**bisection**: λ=0 is the base weighting, λ→+∞ concentrates on the highest-beta
name, λ→−∞ on the lowest, so `book_beta(λ)` is monotone across the full feasible
range. (A *linear* tilt `w_base + λ·β` saturates at `Σβ²/Σβ` — proportional-to-β
weights — and cannot reach the higher betas, so the exponential form is required.)
Per-name betas are the 120d OLS-vs-SPY values the pipeline already stores
display-only in `rankings.factor_scores.beta`; a missing beta is imputed 1.0
(market). After each tilt the position + cluster + sector caps are re-applied
(iterated to a fixpoint), so **the overlay never breaches a concentration limit**.

**Properties / guardrails.**
- **Caps win over the target.** If the target needs concentrating a capped group
  (or the selected names' betas can't span it), the achieved beta falls short; the
  builder ships the **closest feasible** book and flags `beta_target_infeasible`
  (a warning in the run + dashboard, never a failed build). It will not breach a
  cap to chase the number. Example: a decoupled, low-beta selection (an energy-heavy
  book) cannot be levered to 1.3 by reweighting alone under a 0.08 position cap —
  that is a *selection* problem, surfaced honestly rather than forced.
- **Reversible.** `beta_target_enabled: false` → the overlay is inert and weights
  are byte-for-byte the pre-overlay result. This is the single revert switch.
- **Config-exposed for the evaluator.** `beta_target` / `beta_tolerance` live in the
  strategy YAML so a future evaluator/LLM can tune market sensitivity via config,
  within the deterministic Python engine (the LLM never sizes positions directly).
- **Complementary** to vol-targeting (governs gross *exposure over time*), the
  falling-knife veto (per-name, reactive), and the concentration caps
  (cross-sectional). Beta targeting shapes the book's *market sensitivity*; the
  caps still bound *how* it gets there.
- Shares the exact same cap primitives as `compute_weights` (`_apply_position_cap` /
  `_apply_group_cap` / `_apply_all_caps`, extracted to module level) so the two
  weighting paths can never drift on what a cap means.

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

### Single approval rule — submit now if open, else queue for next open

There is **one** approve action (manual click, Approve-Selected, and auto-approve
all use it): **send to the broker immediately if the market is open, otherwise
queue until the next trading day.** The dashboard shows a single ▶ Approve button
(plus ✕ Reject) and always sends `mode="immediate"`; `_route_to_drain(mode, clock)`:

```text
immediate + market OPEN, side=SELL → submit INLINE now (fills in seconds, frees cash)
immediate + market OPEN, side=BUY  → the DRAIN (released only within live buying power)
immediate + market CLOSED          → the drain entirely (queued for the next open)
(scheduled is retained in _route_to_drain for back-compat but no caller emits it.)
```

The after-close cron chain runs while the market is CLOSED, so its auto-approvals
route to the drain (sells-first, fill-gated) — the dominant path keeps that safety.

During market hours, **sells still submit inline** (they fill in seconds and free
buying power) but **buys route to the drain** so they release only once live buying
power covers them. This closes a confirmed footgun: a rotation approved mid-session
fired its buys inline within seconds of the sells — *before* the sells' proceeds
settled — so each buy saw the stale pre-rotation buying power (~the small free cash
on a fully-invested book) and Alpaca rejected it "insufficient buying power".
Routing buys through the drain makes a fully-invested rotation self-fund instead of
failing; a discretionary buy with spare cash is released on the next drain tick
(seconds). The closed-market case drains everything for the same reason.

Inline submission still flows through the same `risk_check` and
`_submit_for_action` entrypoint (exits → close-position, others → `/v2/orders`),
so `immediate` changes only the *timing*, never the safety path. (Previously the
operator had to approve sells before buys by hand on a fully-invested book; the
buy→drain routing now does this automatically.)

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
defaults to *keep*. The deterministic falling-knife backstop becomes the **only**
exclusion signal: the beta-adjusted excess trigger (`DRAWDOWN_EXCESS_PCT`, default
0.15) plus an absolute floor (`DRAWDOWN_BACKSTOP_PCT`, default 0.25 — set ABOVE the
excess limit so the market-relative excess governs moderate drops and the floor
only catches extreme routs).

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

## Design Decision: AI theme concept RETIRED (theme-agnostic engine)

**What changed.** The thematic overlay and the hardcoded AI-buildout universe were
removed entirely — the engine is now theme-agnostic. Removed: the `theme_overlay`
config block (`ThemeOverlayConfig`), `shared/ai_universe.py` (`AI_BUILDOUT_UNIVERSE`),
the portfolio-builder tilt/restrict overlay, the llm-vetter theme augmentation, the
api `/rankings/theme` endpoint + dashboard proxy, and the `theme-classifier` service.

**Why.** A hot sector should be *discovered organically* by the factors (momentum,
earnings-surprise, near-high, …) and bounded by the correlation-cluster caps, not
hard-wired to a named, hand-maintained ticker list. A single hardcoded theme was the
largest sleeve-specific, non-generic surface; retiring it is part of the move to one
agnostic engine the (future) LLM evaluator tunes. If a thematic tilt is ever wanted
again it should come back as *data* (a populated members table referenced by config),
not code.

**Migration note.** Existing strategy files had their `theme_overlay:` block stripped;
`quality_core_v1`/`quality_momentum_v1` had their sleeve-relaxed caps restored to
pure-core (sector 0.25 / cluster-weight 0.15 / 3 names per cluster).

## Trade Approval Flow

Every paper trade requires a human button click. The system does not auto-submit
even after the delta engine fires — the delta_intents row is just a proposal until
a human approves it on the dashboard.

```text
delta-engine → delta_intents (entry / exit / hold / watch / at_risk / buy_add / sell_trim)
  → dashboard "Trade Proposal" tab (human review)
  → human clicks "Approve Selected" (mode=immediate) — or cron auto-approve after timeout
  → dashboard POST /api/trade/approve-batch {intent_ids:[...], mode}   (one request, returns in ms)
  → api POST /trade/approve-batch  [per-intent: UUID + open-order + vetter-exclusion checks]
  → trade-executor POST /jobs/enqueue-batch  [marks delta_intents.approved_at; kicks worker; returns]
  → (background) trade-executor approval worker — SINGLE CONSUMER, one intent at a time:
    for each approved & unprocessed intent of the LATEST delta run with no open order:
      run the existing /jobs/submit orchestration (load_intent → guards → size_order →
      risk_check → record_order → route), then stamp approval_processed_at.
```

The per-intent orchestration (`/jobs/submit`, still the unit of work) is unchanged:

```text
    1. load_intent       — read delta_intents row
    2. size_order        — entry:    floor(account_value × weight / last_price)
                          exit:     full position qty from latest live_positions
                          buy_add:  floor(account_value × abs(weight_drift) / last_price)
                          sell_trim:floor(account_value × abs(weight_drift) / last_price)
    3. risk_check        — call risk-service POST /check
    4. record_order      — INSERT alpaca_orders (pending or risk_rejected)
    5. submit_alpaca / enqueue for the fill-gated open drain (Option B)
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

### Design Decision: approval = durable enqueue + single-consumer drain (trader flakiness root-cause fix)

**Problem.** Approval was modelled as N synchronous size→risk→submit RPCs. The
dashboard fired every selected approval at once (`Promise.all`), each hitting
`/jobs/submit`, which serialized `[risk-check → record reservation]` on a single
per-`(account, trading_day)` Postgres advisory lock (`with_submit_lock`,
`SUBMIT_LOCK_TIMEOUT_SECS=30`). Two structural faults made a large rotation
(e.g. 15 exits + 15 entries) flaky:

- The lock was held **across `_call_risk`** — an inter-service HTTP call that
  itself retries (`RISK_CALL_RETRIES=3` × 10s + backoff ≈ up to ~30s). One slow
  risk call could hold the lock for the entire 30s budget, so every other waiter
  timed out → `"submit serialization lock timed out after 30s"` recorded `failed`.
- **Three mis-ordered HTTP timeouts** (dashboard proxy 30s < executor lock 30s <
  api proxy 60s): the *outermost* (browser→dashboard) was the *shortest*, so the
  dashboard gave up first and the browser showed `TypeError: Load failed` while
  the executor was still working — an indeterminate outcome from the UI's view.

Both symptoms were the **same event** seen from two layers, and both existed only
because there were **multiple concurrent submitters** (the browser ×N, plus the
cron auto-approve worker). The lock was a band-aid for that concurrency.

**Decision.** Approval is a **durable enqueue**, and a **single background worker
is the sole consumer** that drains approvals sequentially through the existing
per-intent orchestration. This matches the system's own rules — *the dashboard
requests approval (does not execute); only the trade-executor submits; state lives
in Postgres; services advance via non-blocking workers* — and reuses the exact
pattern already proven by the fill-gated open drain.

```text
- The approval marker lives on delta_intents (approved_at, approval_mode,
  approval_processed_at), NOT a new alpaca_orders status — so the risk projection,
  turnover accounting, idempotency index, and the whole /jobs/submit test surface
  are untouched.
- /jobs/enqueue {intent_id, mode} and /jobs/enqueue-batch {intent_ids,mode} set
  approved_at (idempotent: a pre-existing OPEN order → duplicate; an already-marked
  intent → already-queued), then kick the worker. They return in milliseconds —
  no risk/broker work on the request path, so the HTTP-timeout cascade is gone.
- The worker (a single asyncio task) waits on an asyncio.Event with a periodic
  timeout (DEFERRED_WORKER_INTERVAL_SECS). Each pass it processes approved &
  unprocessed intents OF THE LATEST delta run that have no open order, ONE AT A
  TIME, by calling the unchanged submit_order(); then stamps approval_processed_at.
  Single consumer ⇒ the advisory lock is never contended ⇒ never times out. The
  lock is KEPT as a cheap backstop against a stray direct /jobs/submit, but it is
  no longer load-bearing.
- Sequential processing is MORE consistent with the risk gate than the old
  concurrent model: each entry becomes an alpaca_orders row before the next is
  processed, so the MAX_POSITIONS projection (which counts entries from
  alpaca_orders) sees prior admissions exactly as the planner intended.
- LATEST-run guard: the worker only acts on intents whose run_id is the most recent
  delta run, so a superseded proposal (a new chain landed) is never executed — the
  same supersede principle the cron auto-approve already applies.
- Refresh-durable: approval is persisted the instant the POST returns. A browser
  refresh/close (which previously stranded the tail of a client-side `for…await`
  batch) now changes nothing — the browser is a pure status viewer that polls
  order_status (and approved_at) from the durable rows. /delta/latest surfaces
  approved_at so an already-approved intent is non-approvable after a refresh.
- Event-kick: enqueue signals the worker so an intraday "approve now" drains in
  sub-second rather than waiting up to DEFERRED_WORKER_INTERVAL_SECS.
```

Retry semantics are preserved (see next section): `approval_processed_at` is
stamped once per approval, so a DEAD outcome does not loop — a human (or the cron
timer) re-approves, which sets `approved_at` afresh and lets the worker run it once
more. The legacy synchronous `/jobs/submit` endpoint remains for direct/manual/test
use and is the shared per-intent unit of work the worker invokes.

### Design Decision: a DEAD order never wedges its intent (retry semantics)

An order status is either **open** (`pending`/`submitted`/`deferred`, plus the
Alpaca-working `accepted`/`new`/`partially_filled`), **done** (`filled`), or
**dead** (`risk_rejected`/`failed`/`expired`/`canceled`). A dead attempt placed
**no live order at the broker**, so it must remain **manually re-approvable** — the
operator retries once the cause is fixed (this is exactly how a transient or
bug-induced rejection, e.g. the risk-service `control_unavailable` exit bug, is
recovered). Three gates enforce this consistently:

- `/delta/latest` joins order status to an intent by **ticker + side + run_date**
  (so a re-run resolves to a trade already PLACED this session, not re-shown as
  un-actioned). The LATERAL **prefers a live/done order over a dead one**, so a
  stale rejection from earlier in the *same session* can't stick to a fresh
  re-run's intent and mask it. (Bug fixed 2026-06-13: without this, a GOOG exit
  rejected at 07:33 made every later re-run that day un-approvable, because all runs
  share the session `run_date`.)
- The dashboard's `_isApprovable` blocks only **open/done** statuses; dead ones get
  a checkbox + Approve button (the "⚠ Risk rejected" badge still shows via
  `_sectionFor`, so the row stays in *Needs Attention*).
- `/trade/approve` 409s only on **open** orders (`pending`/`submitted`/`deferred`);
  the trade-executor's own idempotency guard (`OPEN_ORDER_STATUSES`) likewise
  excludes dead statuses.

Asymmetry on purpose: the **cron auto-approve** (`_auto_approve_once`) still SKIPS
`risk_rejected`/`failed` so a *persistent* failure can't loop unattended. Only the
**manual** UI path allows the retry — a human decides to try again.

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

## Factor Construction: Industry Neutralization & Gross-Profitability Quality

Two factor-construction upgrades grounded in the cross-sectional asset-pricing
literature (Tier-1 of the strategy-analysis research), both `FactorEngineConfig`
flags. **Industry neutralization of value/quality defaults ON**
(`industry_neutral_factors=[value, quality]`); **gross-profitability quality
defaults OFF** (`quality_use_gross_profitability=False`), opt-in pending backtest
validation. The output shape is unchanged: every factor is still one `[0,1]` percentile per
ticker, fed into the same `rank_universe` weighted sum → one universe-wide
ranking. These change *which names rank near the top*, not the format the
portfolio-builder consumes.

### 1. Industry neutralization (value & quality only — NOT momentum)

**Decision.** When enabled, the `value` and `quality` factors are
percentile-ranked **within the stock's own sector** (`universe_tickers.sector`,
the Alpha Vantage `Sector` label) instead of against the whole universe.

**Why asymmetric.** The literature is two opposing findings:
- Value/quality are "reliably priced *within* industry" and within-industry
  measurement is more precise (Asness, Porter & Stevens 2000). Ranking value
  universe-wide just rediscovers that banks/energy are *structurally* cheap — a
  sector bet masquerading as stock selection.
- Momentum is the opposite: a large part of single-stock momentum *is* industry
  momentum (Moskowitz & Grinblatt 1999). Neutralizing momentum by sector
  **deletes signal**. Low-volatility and liquidity are likewise left
  universe-wide.

Therefore neutralization is restricted by a config validator to
`{value, quality, growth}`; momentum/low_volatility/liquidity may never be
listed.

**Why labels, not correlation clusters.** Neutralization runs over the *whole
universe* and must be stable/reproducible. A universe-scale correlation matrix is
~94% noise (Laloux et al. 1999) and its clusters churn period-to-period
(Kakushadze 2016) — exactly the turnover/reproducibility cost CLAUDE.md's
determinism rule forbids. Classification labels are stable and capture most of
the real comovement (Connor 1995). The correlation-cluster machinery in the
portfolio-builder stays where it is — that is concentration *capping* on a small
candidate set, where the covariance is genuinely needed, a different job.

**Where in the pipeline.** At the cross-sectional normalization step — the moment
a raw factor becomes a percentile — inside `compute_all_factors`, value/quality
only. Not earlier (raw signals are sector-agnostic), not later (the rank step
fuses all factors into one composite; per-factor asymmetry can't be expressed
after the sum).

**Construction level & fallback.** Composite-level: the existing global ranking
on the value/quality series is swapped for a within-sector ranking on the
already-composited series (an accepted approximation vs. neutralizing each inner
component, matching the `_component_zscore` precedent). A ticker falls back to
universe-wide ranking when (a) its sector is NULL/unknown, or (b) its sector has
fewer than `min_sector_group_size` (default 10) tickers with a valid value — so
neutralization never reduces coverage.

### 2. Gross-profitability quality (vs ROE)

**Decision.** When enabled, the `quality` factor's profitability leg switches
from `ROE` to **gross-profits-to-assets** = `gross_profit / total_assets`
(Novy-Marx 2013, "The Other Side of Value"), keeping inverse-leverage as the
"safety" leg (a QMJ-lite profitability+safety composite). ROE is the literature's
weakest quality proxy and mechanically rewards leverage (fighting the
inverse-leverage term). Gross profitability has "roughly the same predictive
power as book-to-market" and drove the Fama-French 2015 profitability factor.

**Data.** `gross_profit` comes from AV OVERVIEW `GrossProfitTTM` (already a
fetched payload — zero new calls). `total_assets` comes from a best-effort AV
`BALANCE_SHEET` fetch added to the fundamentals path (gated by
`FETCH_BALANCE_SHEET`, default on; failures are non-fatal and leave
`total_assets` NULL). New `fundamentals` columns `gross_profit`, `total_assets`
(migration 0017). This roughly doubles AV calls on the fundamentals refresh —
the documented operational cost of the upgrade.

**Graceful degradation.** When the flag is on but `gross_profit`/`total_assets`
are absent (pre-backfill, or a ticker whose balance-sheet call failed), the
profitability leg neutral-fills exactly like any other missing component, so the
factor never breaks. When the flag is off, `compute_quality` is byte-for-byte the
legacy ROE/leverage composite.

## Portfolio Concentration: dual cap (correlation cluster + AV sector)

**Decision (supersedes "cluster cap only / sector cap deprecated").** The
portfolio-builder enforces concentration on TWO independent dimensions:

1. **Correlation-cluster cap** (`max_cluster_weight`, `max_tickers_per_cluster`)
   — bounds correlated micro-groups (e.g. tankers that move together).
2. **AV-sector cap** (`max_sector_weight`, default 0.30; `quality_core_v1` sets
   0.25) — bounds a whole sector's share of the book, on the AV `Sector` label.

**Why both.** A single sector can spread across *several* low-correlation
clusters — energy = tankers + refiners + E&P, each its own cluster under 15% —
so the cluster cap is individually satisfied while the *sector* reaches ~30%
(observed live: ENERGY 29.7%). The cluster cap structurally cannot see "energy";
the sector cap can. This is the momentum-side analogue of the value/quality
banks concentration that industry-neutralization fixed on the ranking side.

**Implementation.** Both caps run in `greedy_select` (count-proxy, blocks a pick
that would push either group over) and `compute_weights` (the binding weight
gate — `_apply_group_cap` is applied per constraint and the constraints are
iterated to a mutual fixpoint, since capping one group redistributes weight that
may violate the other; bounded and convergent because a capped group never
receives weight back). Either cap set to `1.0` disables that dimension. An
infeasible cap (n_groups × cap < 1.0) degrades gracefully: redistribution stops
when no uncapped receiver remains and the final normalization restores sum-to-1.

## av-ingestor fetch cleanup: one-shot price retry

`fetch-data` retries price-fetch failures **once** after the main loop. Most
price errors are transient (AV rate-limit `Note`, a dropped TLS connection) and
clear on a second attempt — real names (VRSN/RHI/IAC) shouldn't sit in the error
list for a flake. Recovered tickers are removed from `error_tickers` and decrement
`error_count` (so a clean retry flips the run from `partial_success` to
`success`); a persistent failure (delisted/odd ticker) errors again and stays
counted. Bounded to the handful that failed; the AV client throttles internally.

## Falling-knife backstop: beta-adjusted (market-relative) drawdown

**Decision (supersedes the fixed-% absolute drawdown as the primary trigger).**
The vetter's falling-knife guard now triggers on **beta-adjusted excess
drawdown**, with the absolute % retained only as a floor:

```text
excess_dd = raw_dd − beta × spy_move        (over the same peak→now span)
exclude if  excess_dd ≤ −DRAWDOWN_EXCESS_PCT   (primary: stock-specific knife, default 0.15)
         OR raw_dd    ≤ −DRAWDOWN_BACKSTOP_PCT  (floor: true collapse, market-blind, default 0.25)
```

The floor is set **above** the excess limit (0.25 > 0.15) on purpose: the
market-relative excess is the primary gate for *moderate* drops (a name the market
dragged down ~20% has excess < 15% and is **kept**), and the absolute floor only
catches *extreme* routs (~25%+) regardless of the market.

**Why.** The fixed-% drawdown was market-blind: on a broad market-down day every
stock breaches 15% via its market beta, so the backstop dumped good names whose
only sin was falling *with* the market. Stripping the beta-implied SPY move
(`raw_dd − β·spy_move`) isolates the IDIOSYNCRATIC drop — a name that fell only
because the market fell has `excess_dd ≈ 0` and is NOT flagged; a name falling on
its own is. This is the standard residual-drawdown / market-relative approach.

**Implementation.** `excess_drawdown` + `estimate_beta` in
`services/llm-vetter/app/drawdown.py` (pure, dependency-free). The vetter loads
`DRAWDOWN_BETA_LOOKBACK` (default 120) days of each candidate's closes plus SPY,
aligns them by date, regresses for β (OLS, clipped to [0, 3] so a noisy/negative
estimate can't invert the adjustment), and computes the excess. SPY history comes
from `daily_prices` (already ingested for regime detection). Graceful degradation:
if there isn't enough aligned history for β, `excess_dd` is None and only the
absolute floor applies — so a data-poor name is never wrongly force-sold. Set
`DRAWDOWN_EXCESS_PCT=0` to revert to absolute-only.

### Volatility-scaled excess threshold (ON by default)

**Decision (refines the flat `DRAWDOWN_EXCESS_PCT`).** A single market-relative
limit is still *volatility*-blind: a −15% idiosyncratic excess is a genuine alarm
for a sleepy staple but ordinary noise for a high-flyer that swings ±15% in a
week. The excess limit is therefore made **per-ticker**, scaled by the stock's own
idiosyncratic volatility:

```text
excess_limit_i = clamp( DRAWDOWN_EXCESS_PCT × idio_vol_i / DRAWDOWN_VOL_ANCHOR,
                        DRAWDOWN_EXCESS_MIN, DRAWDOWN_EXCESS_MAX )
exclude if excess_dd_i ≤ −excess_limit_i
```

`idio_vol_i` is the stock's **annualized residual volatility** — the stdev of
`r_stock − β·r_spy` over `DRAWDOWN_BETA_LOOKBACK` days × √252, i.e. the market
component is stripped out so it measures *stock-specific* turbulence, consistent
with the beta-adjusted excess it gates. `DRAWDOWN_VOL_ANCHOR` (default 0.35) is the
residual vol of a "typical" name: a stock at the anchor keeps the base limit, a
calm name (lower idio_vol) gets a **tighter** limit (flagged on a smaller drop),
a wild one gets **more rope**. The result is clamped to
`[DRAWDOWN_EXCESS_MIN=0.10, DRAWDOWN_EXCESS_MAX=0.30]` so the scaling can never
produce an absurd limit.

**Defaults / safety.** `DRAWDOWN_VOL_SCALING=true` by default (set both in code and
`docker-compose.yml`). When `idio_vol` is unavailable (insufficient aligned
history), `scaled_excess_threshold` falls back to the flat `DRAWDOWN_EXCESS_PCT`,
so a data-poor name is never given a weird threshold. The absolute floor
(`DRAWDOWN_BACKSTOP_PCT`) is unchanged and still market-blind. Set
`DRAWDOWN_VOL_SCALING=false` to revert to the flat percentage. The exclusion
reason string shows the realized per-ticker limit and σ (e.g.
`limit -12% @ σ28%`) for transparency.

**Implementation.** `beta_and_idio_vol` (returns β and residual vol in one pass)
and `scaled_excess_threshold` in `services/llm-vetter/app/drawdown.py`;
`excess_drawdown` now carries `idio_vol` through to the caller, which computes the
per-ticker limit in the backstop block.

## Design Decision: regime factor-weight rotation OFF (static weights)

**Decision (supersedes the 4-bucket regime-conditional factor weighting as the
live weighting scheme).** Factor weights no longer rotate by regime. The regime is
still **detected** (written to `regime_snapshots`, shown on the dashboard) but it
no longer changes the weights — a single `static_factor_weights` vector is used in
all regimes. Controlled by `StrategyConfig.regime_weighting_enabled` (default
`True` for back-compat; set `False` in `quality_core_v1.yaml`).

**Why.** A deep-research pass (Asness "factor timing is deceptively difficult";
Cederburg, O'Doherty, Wang & Yan 2020 on volatility-managed portfolios) found that
broad regime / value-growth-quality *rotation* is weakly supported out-of-sample
and overfits: a 4-regime × 6-factor table is calibrated on a handful of
non-stationary regime episodes, exactly the "structural instability" that kills the
in-sample edge in walk-forward. A single static multi-factor vector is hard to beat
OOS, and momentum-crash protection — the one regime effect with strong evidence
(Barroso–Santa-Clara; Daniel–Moskowitz) — is provided independently by the vetter's
beta-adjusted, vol-scaled falling-knife drawdown veto. So the overfit-prone
rotation is removed while crash protection is retained elsewhere.

**The static vector** evolved in two steps. (1) From the raw centroid of the four
regime vectors it was rebalanced away from an over-defensive tilt (low-vol was the
fragile leg — crowding/valuation/rate risk; momentum the under-weighted
highest-Sharpe diversifier). (2) It was then re-tilted **momentum-forward** to fit
the strategy's actual nature: this is a continuous-turnover rotation book, not
buy-and-hold, so valuation matters less (the value premium is a slow multi-year
effect that barely operates over a weeks-to-months holding horizon, where momentum
dominates). Value and low-vol are demoted (we rent expensive/volatile names and
rotate out); momentum leads; quality stays the anchor; growth raised:
**momentum 0.28, quality 0.22, growth 0.16, liquidity 0.11, value 0.09,
low_volatility 0.08, issuance 0.06** (sums to 1.0). The crash risk of a momentum
tilt is guarded independently by the vetter's beta-adjusted, vol-scaled
falling-knife veto and the residual/risk-adjusted momentum method — which is what
makes an aggressive momentum lean defensible here.

**Implementation.** `StrategyConfig.effective_factor_weights(regime)` is the single
resolver used by both the ranker (`rank_universe`) and the audit/spot-check display:
it returns `static_factor_weights` when rotation is off, else `factor_weights[regime]`.
A validator requires `static_factor_weights` when `regime_weighting_enabled` is
False (and applies the liquidity-required-factor check to it). The four
`factor_weights` regime vectors are kept in the YAML for reference / easy re-enable.

**Re-enable** by setting `regime_weighting_enabled: true`. **Validate** any change
walk-forward, net of costs, against this static baseline before trusting a
rotation scheme — the literature predicts the static vector is hard to beat and any
rotation "edge" lives only in the momentum-de-risking cells.

## Design Decision: net-share-issuance factor (optional 7th factor)

**Decision.** Add an optional `issuance` factor capturing the net-share-issuance
anomaly (net issuers underperform, net repurchasers outperform — one of the more
robustly-replicated anomalies; low turnover, large-cap-native). It is the 7th
factor in `FactorWeights`, **default weight 0.0** (like `liquidity`), so every
existing config still sums to 1.0 and is unaffected; `quality_core_v1` opts in at
a modest 0.06 (it overlaps value/quality, so marginal alpha is modest).

```text
net_issuance = shares_outstanding / shares_outstanding_prior - 1   (YoY)
factor       = -net_issuance        (buybacks rank high, dilution low)
```

Data: computed from balance-sheet **annual** common shares outstanding —
`annualReports[0]` vs `[1]` from AV BALANCE_SHEET (already fetched for
`total_assets`, gated by `FETCH_BALANCE_SHEET`, so no new API surface). Migration
0018 adds `fundamentals.shares_outstanding` + `shares_outstanding_prior` (nullable);
`compute_issuance` returns NaN where shares are missing/non-positive, and the
factor is NOT in `required_factors`, so a missing value never drops a ticker — it
just gets no issuance tilt. Only the live `services/pipeline` factor math + the
`FACTORS` list are extended.

## Design Decision: enhanced momentum (residual + risk-adjusted)

**Decision.** The momentum factor is configurable via `FactorEngineConfig.
momentum_method`; `quality_core_v1` uses `residual_riskadj`. Plain 12-1 price
momentum is the highest-turnover, most crash-prone factor, and the research with
the strongest, most cost-robust evidence is *risk-managing* it, not adding new
factors (Barroso-Santa-Clara "Momentum Has Its Moments", Sharpe 0.53→0.97;
Blitz-Huij-Martens "Residual Momentum", Sharpe ≈ doubles; Daniel-Moskowitz).

Pure portfolio-level vol-scaling doesn't map onto a *cross-sectional* z-score
ranker, so we implement the cross-sectional analogues, computed over the same 12-1
formation window:

```text
raw              — plain Jegadeesh-Titman 12-1 price return (schema default)
risk_adjusted    — raw / formation-period volatility (Sharpe-like; penalizes the
                   high-vol names that drive momentum crashes)
residual         — cumulative residual return after stripping the market (the
                   equal-weight cross-sectional mean daily return) — idiosyncratic
                   momentum, far smaller crash tails; no SPY plumbing needed
residual_riskadj — residual / formation vol (both effects; quality_core_v1 default)
```

**Multi-horizon blend** (`momentum_blend_windows`): when set to >1 long-window
lengths, the factor is the rank-average of the chosen `method` computed at each
horizon — `quality_core_v1` uses `[252, 126]` (12-1 + 6-1). All horizons share the
`momentum_short_window` skip, so the factor reacts sooner to emerging trends while
still skipping the last month (short-term-reversal protection preserved — it does
NOT chase 3-week spikes; that's the falling-knife's domain). `null`/one value =
single-horizon.

Memory-light (the formation-window return slice is a few MB at universe scale,
built once and freed). Falls back to raw when there isn't enough history or the
market proxy is degenerate. Set `momentum_method: raw` to revert. Only the live
`services/pipeline` factor math is changed (the `_archive` copies are dead).

## Alpha-validation harness (backtester)

"Does the system generate alpha?" is an EVIDENCE question, not a construction one
— a factor-ranked, greedily-selected, capped book always produces a plausible
equity curve. `services/backtester/app/validation.py` provides the statistics that
separate skill from selection luck, exposed at `POST /validate`:

```text
deflated_sharpe_ratio   — PSR vs an N-trials-inflated null (Bailey & López de Prado).
                          Gate: DSR > 0.95. Needs an HONEST n_trials (every factor
                          weight / cap / threshold / universe variant ever tried) and
                          the variance of trial Sharpes; punishes negative skew + fat
                          tails. Without n_trials the backtest Sharpe is uninterpretable.
probability_of_backtest_overfitting — CSCV: how often the in-sample-best config lands
                          below the OOS median. ≈0.5+ = overfit, low = generalizes.
min_track_record_length — observations needed to prove true Sharpe > benchmark; blows
                          up as the edge shrinks (months won't do at modest Sharpe).
min_backtest_length     — years below which an in-sample Sharpe is expected from
                          n_trials alone (Bailey-Borwein-LdP-Zhu).
factor_alpha            — OLS attribution: regress strategy EXCESS returns on FF5 +
                          momentum (+ sector). If the alpha intercept is not positive
                          AND significant (t ≥ 3, Harvey-Liu-Zhu) net of costs, the
                          book is a cheap-to-replicate factor TILT, not stock-picking
                          alpha. load_factor_returns_csv() ingests a Ken-French file
                          (pass scale=0.01 for percent→decimal).
```

The bar to claim alpha: DSR > 0.95 AND FF5+momentum alpha t ≥ 3 net of realistic
costs, established out-of-sample with low PBO, stable across regimes, then paper
(≥ MinTRL) then small live. Pre-register the thresholds before looking at results.

## Design Decision: backtester as a trustworthy evaluator tool (G1–G6)

The backtester will be a TOOL the evaluator LLM calls (Phase 2 below), so its
numbers must be faithful — an optimistic or config-blind backtest would launder
an overfit config into a "recommend" verdict. Two backtest MODES now exist, both
scored by the same de-biased simulator and the same validation verdict:

```text
persisted_replay  (POST /jobs/backtest)         — re-scores portfolio_runs that
                    were ALREADY built (under whatever config produced them).
                    Answers "how did what we actually held do?".
config_replay     (POST /jobs/backtest-config)  — G1. Re-RANKS and re-SELECTS
                    every historical rebalance date under a CANDIDATE config
                    (inline `config` or a `config_path`), using the live chain's
                    OWN deterministic code. Answers "what would THIS config have
                    done?" — the question the evaluator needs to test a thesis.
```

**Faithfulness (config_replay / G1).** The re-rank uses the SAME `rank_universe`
(pipeline) and the SAME builder `select.py` composition (covariance → correlation
clusters → greedy_select → compute_weights → position/cluster/sector caps →
optional beta-target / vol-target / cash_reserve). Those modules are vendored
BYTE-IDENTICAL into `services/backtester/app/_vendor/` (a re-implementation would
drift); `tests/backtester/test_vendor_sync.py` fails CI on any divergence. No
look-ahead by construction: factor values are the PERSISTED point-in-time
`factor_scores` for each date; covariance / regime / beta for date D use only
prices ≤ D; the simulator fills at D+1 (G3). Deliberately NOT modelled (surfaced
as `config_replay_caveats` on the result): vetter exclusions (a run-time signal,
not a config knob), turnover-penalty continuity (replay is holdings-agnostic,
matching the builder's default), and per-date as-of sector labels (near-static;
latest-as-of is used for the sector cap).

**No-bias simulation (G3/G5).** Entry = first close STRICTLY AFTER the rebalance
date (removes the same-close look-ahead); a delisted/halted name exits at its own
last real price, not renormalized away; a held name with no usable price stays in
the FULL-WEIGHT denominator at 0% return (no survivor boost); 10 bps default
round-trip cost. The summary carries the DISTRIBUTION (percentiles, skew, excess
kurtosis, pct_positive), not just the mean, so a right-tail sleeve isn't judged on
its (poor) average alone.

**Honest multiple-testing (G2/G4).** Every run — either mode — records a
`backtest_trials` row first, so the DSR/PBO in `build_validation` deflate the best
Sharpe by the HONEST `COUNT(DISTINCT config_hash)` actually tried (running 20
configs and citing the best carries the full multiple-testing penalty). Short
samples (< 24 rebalances / < 2y / below MinTRL) are flagged DIRECTIONAL-not-
conclusive. `backtest_runs` gains `summary`/`validation`/`sim_mode`/`config_json`
(migration 0039) so a result is self-describing. Config is reloaded per job (G6)
so a deployed YAML edit takes effect with no restart.

## Design Decision: weekly LLM evaluator loop (Phase 1 — read-only)

The `evaluator` service closes the improvement loop: every week a frontier model
reviews what the system actually did and (a) recommends strategy-config tweaks,
(b) surfaces STRUCTURAL gaps the knobs cannot fix — missing factors (and the data
they'd need), un-ingested data sources, and selection/exit/vetting logic that
systematically leaves winners on the table. To critique structure honestly the
packet carries a hand-maintained SYSTEM-ARCHITECTURE BRIEF (pipeline stages +
known non-features; update it when the pipeline changes materially) and a
SELECTION AUDIT of the latest build: every candidate classified
selected / cap_blocked / vetter_excluded / out_ranked with per-class forward
returns — the spread that separates "the rank missed winners" (factor problem)
from "the builder's caps rejected winners the rank found" (construction problem).
Structural findings are a separate schema-validated output channel
(category ∈ missing_factor, missing_data_source, selection_logic, exit_logic,
vetting, risk_logic, process, other) rendered as amber cards on the Review tab.
**Objective function (design decision 2026-07-10, explicit by owner instruction):
maximize long-run compounded ABSOLUTE return (terminal wealth).** SPY is the
hurdle, not the target — beating it at half the return is failure. The
risk-service limits and drawdown guards are CONSTRAINTS, not goals: the evaluator
must not recommend de-risking to flatter Sharpe unless it protects compounding
(i.e. avoids deep drawdowns arithmetic can't recover from). When expected return
and risk-adjusted return conflict, prefer expected return within the constraints.
"Picks more winners" means winners compounding ABSOLUTE dollars — not hit-rate,
not benchmark-hugging, not Sharpe for its own sake. (Before this was explicit,
the evaluator's metric diet — Sharpe/DSR/excess-vs-SPY — silently biased its
recommendations toward defensive, risk-adjusted choices.) Three phases:

```text
Phase 1 (BUILT)   — read-only weekly report in the dashboard's Review tab
Phase 2 (BUILT)   — the LLM calls read-only TOOLS mid-review (backtester, SQL,
                    source/docs read, web search) to test a thesis before
                    recommending it — see "Phase 2: evaluator tools" below
Phase 3 (REMOVED) — one-click HUMAN-APPROVED apply of a recommendation. Deleted
                    in 2026-07; the ONLY path to the live config is now the
                    wind-tunnel gate — see "ONE path to the live config" below.
                    The section is kept for history, not as current behavior.
```

## Design Decision: evaluator Phase 3 — one-click apply (REMOVED 2026-07)

> **HISTORICAL.** `POST /config/apply`, the Review-tab Apply buttons and the
> single-field `queue_experiment` tool no longer exist. A config change reaches
> the live strategy only by winning the deterministic promotion gate — see
> "ONE path to the live config". Kept because the transactional ordering and
> archive/audit mechanics below were inherited verbatim by the promotion
> watcher.

The Review tab's actionable recommendation cards carry an **Apply** button. The
click is the human approval — the LLM boundary is unchanged (the evaluator
service stays read-only/advisory; the LLM never touches the file; a
deterministic, human-triggered endpoint does).

Flow (api service, `POST /config/apply`, single writer via an in-process lock):

```text
dashboard Apply click (confirm dialog)
  → api parses the recommendation's suggested_value to a literal
      (shared/stock_strategy_shared/config_values.py — same parser the
       experiment queue uses; prose values are rejected, never guessed)
  → applies the SINGLE dotted-path diff to the active YAML
  → validates the ENTIRE new config through the strategy-validator SERVICE
      (HTTP /validate; unreachable or invalid → HTTP error, NO write —
       fail-closed, honoring "no config reaches the trading system unless it
       passes validation")
  → archives: pre-change file → artifacts/config/history/<ts>_<oldhash>.yaml,
              exact new bytes  → artifacts/config/applied/<ts>_<newhash>.yaml
  → atomically replaces the active YAML (tmp + rename)
  → INSERT config_changes row (migration 0042): field, old/new value,
      config_hash before/after, source report run_id + recommendation index
```

Consequences, deliberate:
- **Takes effect next chain run** (services reload config per run); a mid-chain
  apply is safe — the delta step's config-skew detector surfaces it non-fatally
  and the next run converges.
- **The written YAML is NORMALIZED** (PyYAML re-dump: comments stripped,
  canonical key order). config_hash is a hash of raw file bytes, so the archived
  `applied/` copy IS the canonical new version — mirroring it into git verbatim
  reproduces the same hash. The pre-change file (with comments) is preserved in
  `history/`.
- **Git reconciliation is a follow-up, not a blocker**: after an apply, the NAS
  working tree differs from origin (the dashboard shows the applied badge; the
  repo is still the source of truth). Mirror the applied file into git before
  the next `git pull` deploy (`git checkout -- strategies/ && git pull` AFTER
  committing the mirrored change upstream, or commit from the NAS).
- The experiment queue (Phase 6b) and one-click apply compose: test in the wind
  tunnel first, apply what survives.

## Design Decision: evaluator tools (Phase 2)

The packet is NOT replaced — it stays the deterministic opening brief every
review sees (reproducible, comparable week-over-week). Tools are for what the
packet cannot do: drill into anomalies and TEST a thesis before recommending it.
Packet = opening evidence; tools = investigation.

**Where the pieces live.** The llm-gateway already carries tool-use end-to-end
(ToolDef pass-through, tool_use/tool_result content blocks, stop_reason) — it
stays a pure provider abstraction and is unchanged. The TOOL IMPLEMENTATIONS and
the agentic loop live in the evaluator (deterministic Python owns execution; the
LLM only chooses which tool to call): `services/evaluator/app/tools.py` +
`agent.py`. The loop: send packet + tool defs → while stop_reason == tool_use →
execute each call → append tool_result → continue; on end_turn parse the same
report JSON contract as Phase 1. Hard caps force a final answer when exhausted.

**The tools (read-only except the ledger, which writes ONLY its own table):**

```text
run_backtest   — config-replay a CANDIDATE config expressed as a DIFF
                 ({dotted.path: value} applied to the ACTIVE config, validated
                 through StrategyConfig; invalid → the validation error is
                 returned to the LLM, nothing runs). POSTs the backtester's
                 /jobs/backtest-config, polls to completion, returns
                 summary + validation (DSR/PBO verdict) + caveats read from
                 backtest_runs. Every run auto-registers a backtest_trials row,
                 so the DSR the LLM sees deflates by ITS OWN search breadth —
                 it cannot run N configs and cite the best unpenalized.
sql_query      — read-only Postgres: single statement, must start SELECT/WITH,
                 executed inside SET TRANSACTION READ ONLY (the hard guarantee —
                 any write fails at the DB) with statement_timeout and a row cap.
read_file      — repo source/docs/config read, rooted at /repo (docker-compose
                 mounts services/, shared/, docs/, strategies/, db/ READ-ONLY —
                 deliberately NOT the repo root, so .env/secrets are never
                 mounted); path-traversal guarded, size-capped; a directory path
                 returns a listing.
web_search     — Tavily (same key as the vetter), results logged verbatim in the
                 transcript; absent when TAVILY_API_KEY is unset.
preview_ranking— FAST thesis triage (seconds): re-rank the latest scored universe
                 under a config diff with the VENDORED production rank_universe
                 (services/evaluator/app/_vendor/rank.py, byte-identical to the
                 pipeline's, sync-guarded in CI) and diff vs the active ranking —
                 top-N membership changes, biggest movers, rank correlation.
                 Rank-level only (no builder caps / vetter); a promising preview
                 still needs run_backtest. Budget EVALUATOR_MAX_PREVIEWS (8).
                 Cannot see a factor_engine change — see below.
preview_factor_recompute
               — RECOMPUTES every factor for the latest scored date under a
                 candidate config, then diffs the ranking against a freshly
                 recomputed baseline. Same output shape as preview_ranking plus
                 per-factor coverage, per-factor rank correlation, and
                 `baseline_fidelity`. HTTP POST to the pipeline's read-only
                 /preview/factors. Budget EVALUATOR_MAX_FACTOR_PREVIEWS (4).
                 See "factor-recompute preview" below.
hypothesis_ledger — the evaluator's durable CROSS-WEEK MEMORY and its ONE write
                 tool, scoped to the evaluator_hypotheses table (migration 0041)
                 and nothing else: thesis → planned test → status/outcome.
                 The read side is a deterministic PACKET section
                 (hypothesis_ledger: open + recently-resolved entries), so every
                 review starts from the same ledger state without a tool call.
                 Closes the gap prior_reviews leaves: past CONCLUSIONS were
                 remembered, open EXPERIMENTS were not — a "watch momentum IC two
                 more weeks" thesis now persists instead of being re-derived.
                 Budget EVALUATOR_MAX_LEDGER_WRITES (6); status ∈ open/confirmed/
                 refuted/abandoned; text capped. Still advisory-only: the ledger
                 never touches config or the trading path.
```

**Budgets (env-tunable):** `EVALUATOR_MAX_TOOL_TURNS` (default 24 gateway calls)
and `EVALUATOR_MAX_BACKTESTS` (default 3 per review — each takes minutes and
each is a trial that deflates DSR). On budget exhaustion the loop strips the
tools and demands the final report JSON. `EVALUATOR_TOOLS_ENABLED=false` reverts
to the Phase-1 packet-only call (also the automatic fallback if the tool loop
fails hard — a review is never lost to a tool bug).

**Audit.** Every tool call (name, arguments, truncated result, elapsed ms,
error) is persisted verbatim in `evaluator_reports.tool_transcript` (migration
0040), so any number the narrative cites can be traced to the exact query or
backtest that produced it.

### Design Decision: the factor-recompute preview

**The gap.** Every cheap evaluation path the evaluator had RE-WEIGHTED factor
scores that were already persisted: `preview_ranking` loads one frame of
`factor_scores` and ranks it under two configs, and the backtester's
`config_replay` replays the persisted point-in-time scores per date. So a change
to how a factor is COMPUTED — `momentum_blend_windows`, `momentum_method`,
`volatility_window`, `pe_pb_cap`, `sue_method`, `industry_neutral_factors` —
scored IDENTICALLY to the active config in both, silently and with no error.
`factor_construction` was the one entry in the tool's own `MECHANISMS` vocabulary
with no cheap test at all; the only real route was a multi-hour wind-tunnel run.
One such candidate (`residual_riskadj`, a55598f6) spent 3h31m and a full
experiment-lane slot to return −1.18pp.

**Where the recompute runs, and why not in the evaluator.** `compute_all_factors`
lives in `services/pipeline/app/factors.py` and is NOT importable from the
evaluator (its Dockerfile copies only `services/evaluator/app/`; `shared/` has no
`factors.py`). Two options existed:

```text
promote factors.py to shared/   a NEW shared module file ⇒ forced stocker-base
                                rebuild for every dependent image (the
                                factor_registry crash-loop trap), AND the
                                evaluator would have to re-implement ~200 lines
                                of loader SQL (investability prefilter,
                                last-known-good fundamentals, drop_fundamentalless).
                                A preview that assembles its inputs differently
                                from production scores a different universe and
                                reports the difference as a config effect.
read-only endpoint on the       CHOSEN. Reuses the real loaders. Universe-scale
pipeline + thin HTTP tool       pandas stays in the container already mem_limited
                                for it. No base rebuild; bt-engine untouched.
```

`factors.py` is already shared-by-copy with bt-engine (COPYed at image build), so
a third consumer over HTTP is consistent with that.

**`POST /preview/factors` (pipeline).** Deliberately NOT under `/jobs/` — every
path there persists a run row; this one writes nothing. It:

```text
- refuses (422) any candidate whose `universe.*` differs from the active config.
  The preview reuses the SURVIVING TICKERS of the run it diffs against and skips
  the investability prefilter entirely — that is what makes the comparison
  apples-to-apples, and a factor_engine diff cannot change investability anyway.
  Honouring a universe change would break the guarantee silently, so it refuses
  and names the wind tunnel instead.
- acquires _job_lock with a SHORT timeout (PREVIEW_LOCK_TIMEOUT_SECS, default 5)
  and returns 409 on contention. A memory guard, not a correctness one: the
  preview holds a universe-scale price frame and the factor step already sits
  close to PIPELINE_MEM_LIMIT.
- RECOMPUTES THE ACTIVE SIDE TOO rather than reading persisted scores. A
  persisted run may carry a different price vintage (the restatement fix) or
  universe snapshot; comparing recompute-against-persisted would mix a data diff
  into the config diff. Both computes pass copy_input=False on the SAME frame —
  safe because compute_all_factors' in-place mutations (to_datetime on datetimes,
  sorting an already-sorted frame, astype(float) on floats) are all IDEMPOTENT,
  so the second compute costs no extra peak memory. That is what makes
  recomputing our own baseline affordable.
- reports `baseline_fidelity`: Spearman of the recomputed active ranking against
  the ranking the chain actually PERSISTED for that date. Below ~1.0 the baseline
  has drifted and every conclusion off it is contaminated — surfaced on every
  call so the model can see it, rather than asserted in a test where nobody would.
```

**No DSR trial registration.** A rank diff is not a performance estimate: it
produces no returns, no equity curve, and covers one date. Registering it as a
`backtest_trials` row would deflate the DSR of runs that actually measure
something. The tool's description says so and the prompt repeats it: the preview
answers "does this move the book", never "does this pay".

**Loader extraction (`services/pipeline/app/factor_inputs.py`).** Steps 1-5b of
`_do_calculate` moved verbatim into `load_factor_inputs`, which both callers use.
Audit logging and progress are INJECTED (`log` / `progress`) so the READ path
cannot diverge while only the chain writes `execution_steps`. `universe_override`
is the single behavioural seam. Guarded by `tests/pipeline/test_factor_inputs_extraction.py`
(the caller must not re-query the loader's tables) and
`tests/integration/test_preview_factors_read_only.py` (row counts unchanged
across a live call against a real, fully-migrated Postgres — mutation-verified).

**Boundary unchanged:** tools are read-only over already-ingested point-in-time
data (web search is the one documented exception — external context, logged);
the evaluator still never writes config, never creates trade intents, never
touches the broker path, and reaches the LLM only through the llm-gateway.

**Boundary (per docs/llm-boundaries.md).** The evaluator is advisory-only: it
never writes config, never creates trade intents, never touches the broker path.
It calls the LLM exclusively through the llm-gateway (the system's single LLM
interface), with `EVALUATOR_PROVIDER`/`EVALUATOR_MODEL` (default
anthropic / claude-opus-5) — deliberately independent of the vetter's
`LLM_PROVIDER`, so the nightly vetting can run on a cheap/local model while the
weekly review uses a frontier model with adaptive thinking.

**Deterministic packet (services/evaluator/app/packet.py).** Python assembles
the evidence; the LLM only interprets. Sections: the active strategy YAML
verbatim + config_hash; the accumulated `evaluator_weekly` factor evidence
(realized IC, MARGINAL IC — the standard for factor changes — and factor
correlations); realized account equity vs SPY (1w/4w/12w/inception); per-trade
realized P&L (average-cost); counterfactual decision audits (what
vetter-excluded names and exited names did AFTERWARD — the "did the veto/exit
add value?" ground truth); the current target book with weighted beta and
sector weights; config-hash change history (attribute behavior changes to
config changes); and system-health caveats so an ops outage is not misread as
alpha decay. Every section is best-effort (degrades to an error marker), and
the packet is persisted verbatim on the report row so every recommendation is
auditable against exactly what the model saw.

**Structured output contract.** The report is JSON: `narrative_markdown`,
`overall_assessment` (healthy/mixed/concerning/insufficient_data), and
`recommendations[]` with `{observation, evidence[], config_field,
suggested_value, direction, expected_effect, confidence}`. Each
`config_field` is validated against the REAL StrategyConfig schema
(dotted-path whitelist); an unknown field is flagged
`config_field_valid=false` and rendered non-actionable — a hallucinated knob
can never flow into Phase 3. Parse failures degrade to a narrative-only report
(raw text preserved), never a crash.

**Persistence + trigger.** One row per run in `evaluator_reports` (migration
0037) with packet, narrative, recommendations, model, prompt_hash, and token
counts. The scheduler is the trigger authority: on weekend days (ET) it POSTs
`/jobs/evaluate` hourly; the evaluator dedupes to ONE report per ISO week
(`already_done`), so retries are free and a Saturday outage self-heals on
Sunday. The dashboard's Review tab shows the verdict, recommendation cards,
narrative, and history, with a manual RUN REVIEW button (force=true re-runs
the week).

**Gateway change this required.** The Anthropic provider used to pass
`temperature` on every request; the Opus 4.7+/Sonnet 5/Fable families REJECT
sampling parameters (HTTP 400), so the provider now omits them for those
models and supports `thinking: true` → adaptive thinking (the only supported
on-mode there). Guarded by tests/llm_gateway/test_sampling_params.py.

## Design Decision: vetter runs deterministic (drawdown-only) — no LLM in the daily chain

`vetter.mode: drawdown_only` (schema default, set explicitly in the active config)
makes the vet step pure Python: the beta-adjusted, vol-scaled falling-knife veto is
the SOLE entry block, and no LLM/Tavily/AV-news calls happen in the daily trading
chain. `mode: llm` restores the per-ticker LLM judgment layer; the
`VETTER_LLM_ENABLED` env var remains as a deploy-level kill switch (BOTH must
allow the LLM for it to run — either alone forces drawdown-only).

**Why.** The LLM-in-the-chain was judged a poor architectural fit in hindsight:
it violated the system's core boundary (deterministic Python decides; LLM
interprets), it was the slowest and least reliable MANDATORY chain step, its
judgments required hallucination guards, and — decisively — it cannot be
backtested, while the falling-knife veto (the demonstrably load-bearing part of
the vetter) is already deterministic. Removing the LLM makes the entire daily
decision path deterministic, reproducible, and backtestable. LLMs remain where
they fit the boundary: the weekly evaluator (interpretation) and strategy config
generation.

**What is unchanged.** The chain contract is identical in both modes: the vet
step still runs, a vetter_runs row is still written, exclusions still bind the
portfolio-builder, and the drawdown veto still applies to held names via the
orphan-exit path. The mode lives in the strategy YAML, so a flip is
config_hash-tracked and visible in evaluator packets.

**The empirical check.** The evaluator's `vetter_outcomes` counterfactuals keep
measuring what excluded names did afterward. If future evidence shows the LLM's
exclusions (beyond the drawdown rule) systematically preceded declines, the flip
back is one line (`mode: llm`).

## Design Decision Rule

Whenever a design decision is made, it must be documented in the design docs before implementation begins.

This applies to: architecture choices, communication patterns, data ownership, safety rules, service boundaries, sequencing decisions, and any explicit choice between two or more reasonable options.

The docs are the source of truth for intent. If code diverges from the docs, update the docs or the code — not just a comment.

## Design Decision: canonical market date for all market-coupled decisions (2026-07)

External audit findings #1/#2/#9/#10: containers run in UTC, so `date.today()` /
`datetime.now(timezone.utc).date()` flip to the NEXT calendar day at 20:00 ET —
splitting one US trading evening (chain at 22:30 ET, auto-approve, ingest
rotation, submit-lock day keys) across two "days", and letting services disagree
about "today".

Rule: any market-coupled decision date comes from
`stock_strategy_shared.trading_tz.market_today()` (STOCKER_TZ → service
override envs → America/New_York, failing fast on a broken tz database), never
from a service's own clock. Chain lineage was already data-session anchored
(the DateAnchor consolidation); this extends the same discipline to the leaf
uses: trade-executor's submit-lock trading-day fallback and stale-price check,
llm-vetter's vet date + news/earnings windows, av-ingestor's fetch/probation
rotation and universe snapshot_date. UTC remains correct for audit TIMESTAMPS
(started_at/completed_at etc.) — this rule is about calendar DATES that select
market behavior.

Price-freshness ages are measured in WEEKDAY SESSIONS
(`weekday_sessions_between`), not calendar days — Friday's close checked on
Monday is 1 session old, not 3 days — so thresholds don't mis-fire over
weekends. Holidays are not modeled (no exchange calendar); thresholds keep
margin for them (MAX_PRICE_AGE_DAYS default 7).

## Design Decision: chain-level config pinning (2026-07, audit finding #5)

Per-run config reload (the seam fix) left ONE race: a one-click apply landing
MID-CHAIN made later steps run under a different config than the ranking —
detected after the fact by the delta step's skew detector, but the chain still
mixed two configs.

The scheduler now PINS the active strategy hash at the first strategy-consuming
trigger of each chain (`_chain_status.config_hash`, computed from the same
read-only /strategies mount and identical to the shared loader's config_hash)
and passes `expected_config_hash` on every pipeline/vet/build/delta trigger.
Each of those services re-reads its file and REFUSES the job (HTTP 409
`config_mismatch`) when the live hash differs — before reserving any run row.
On a mismatch the supervisor re-pins to the new file and force-re-runs the
whole strategy segment (pipeline → vet → build → delta), so the chain
CONVERGES on the new config instead of wedging or mixing. Pinning degrades to
off when the strategies mount is absent (services skip the check); the delta
skew detector remains as the residual net. fetch-data is not pinned — it does
not consume strategy config. Session rollover and run-now clear the pin so
every new chain pins the then-current config.

## Design Decision: one canonical strategy_engine (2026-07, audit finding #3)

`rank.py` (ranking) and `select.py` (portfolio selection) existed as
byte-identical copies in pipeline, portfolio-builder, backtester `_vendor/`,
and evaluator `_vendor/`, held together by CI byte-equality tests. The copies
are now re-export shims onto `shared/stock_strategy_shared/strategy_engine/`
— each shim replaces its own sys.modules entry with the canonical module, so
every import path (`app.rank`, `app.select`, `app._vendor.rank`, bt-engine's
`app.live` loader) yields the SAME module object. A bug fix lands everywhere
by construction; the sync tests now assert module identity (stronger than
byte equality). regime.py remains a real vendored copy in the backtester
(byte-sync still enforced) — next candidate to move. This is also the first
concrete step toward the planned modular-monolith restructuring: the
duplicated strategy math now has a single import path that a merged codebase
inherits unchanged.

Deploy caveat: strategy_engine is a NEW module directory under shared/ — the
stale-base trap applies. Rebuild the base BEFORE pipeline, portfolio-builder,
backtester, evaluator (and the bt stack next time it is rebuilt):
`docker build --network host -t stocker-base:latest -f Dockerfile.base .`
(`make build-base` is the same command, but make is not installed on the NAS.)

## Design Decision: closed-loop evaluation upgrades (2026-07, optimizer-essay adoption)

Four measurement/feedback features adopted from the external "closed-loop
optimizer" analysis. All four are READ-side: they change what the system can
*see about itself*, never what it trades. No new write path to orders or
config; the human-approved apply flow remains the only config mutation.

### 1. Decision ledger + multi-horizon outcome labeling (BUILT)

Problem: the system makes discrete decisions daily (enter, exit, defer-to-watch,
orphan-flag, trim, vetter-exclude) but only ad-hoc counterfactuals existed
(packet `_vetter_outcomes` / `_exit_outcomes` — one open-ended horizon, computed
on the fly, never persisted). There was no durable, uniformly-labeled record
answering "what happened AFTER each decision, at fixed horizons".

Design:

```text
decision_outcomes (migration 0045) — one row per harvested decision:
  source        'delta_intent' | 'vetter_exclusion'  (+ source_id UUID, UNIQUE pair)
  decision_date session date of the decision (delta_runs.run_date /
                ranking_runs.rank_date via the vetter run's source ranking)
  ticker, action  entry/exit/buy_add/sell_trim/at_risk/watch/vetter_exclude
                  ('hold' intents are NOT harvested — pure position-keeping,
                   volume without information; realized P&L already covers held names)
  base_price    ticker adjusted close at the decision session (last price ≤ that
                session within a small staleness window)
  fwd_1d/5d/20d/60d   forward returns at 1/5/20/60 TRADING SESSIONS
  spy_fwd_*           SPY over the same session spans (excess = fwd − spy_fwd)
  mfe_20d/mae_20d     max favorable / adverse excursion over the 20-session window
  complete      TRUE once the 60-session horizon has elapsed and labeling ran
                (also TRUE with null labels when no price data exists by then —
                 give-up rule so unpriceable rows don't retry forever)
```

The session grid is the SPY date series from daily_prices (same convention as
the factor stack). Forward prices use last-available-≤-session (delisted/halted
names hold at last real price — consistent with the backtester's de-bias rules).
Labeling is IDEMPOTENT and RETROACTIVE: `POST pipeline /jobs/label-outcomes`
harvests any not-yet-ledgered decisions (INSERT … ON CONFLICT DO NOTHING over
the full history), then (re)labels incomplete rows whose horizons have newly
elapsed. Pure math lives in `services/pipeline/app/outcomes.py`; the endpoint
holds its OWN lock (never the pipeline `_job_lock` — labeling must not block
the chain, and vice versa). The scheduler fires it once per day as a
best-effort side job (`_maybe_label_outcomes`, same pattern as the weekly
universe refresh; OUTCOME_LABELING_ENABLED=false disables).

Consumers: evaluator packet section `decision_outcomes` (per-action aggregates:
n, avg 20d/60d excess vs SPY, hit rate, avg MAE). Read it as: positive excess
on `exit`/`vetter_exclude` rows means the names we shed OUTPERFORMED — the
decision cost money; `watch` (capacity-deferred entries) beating `entry` means
the capacity gate defers the wrong names.

### 3. Score calibration diagnostics (Item 3)

Does a better composite score actually predict a better forward return, and is
the relationship monotone? Two views, same math: (a) bt-engine simulations
record decile-of-score → forward-20-session-return on sampled rebalance dates
(`summary["score_calibration"]`); (b) the evaluator packet computes the same
decile curve from PERSISTED ranking runs old enough to have forward data
(21–90 days), per current regime, vs SPY. A flat or non-monotone curve says
the model's ordering carries no information in that band — evidence for
factor-weight or construction changes; top-decile-only lift with a flat middle
supports concentrated books.

#### Design Decision: the calibration instrument had to be fixed before it could be believed (2026-08)

An external review recomputed a price-only reconstruction of the active ranking
over 48 monthly dates and reported a top-minus-bottom spread of +0.40pp with a
bootstrap 95% interval of −1.13 to +1.86. Its headline ("the ranking is not
monotonic") over-reached — it tested 0.56 of the composite weight, on a 505-name
large-cap panel rather than the ~2000-name investable universe, and judged a
35-name book by whether decile 6 beat decile 2 — but its critique of OUR OWN
measurement was correct on every point. Six defects, all confirmed:

```text
CALIB_MAX_RUNS = 6      sampled from a 21-90d window against a 20-session
                        horizon, so the anchors OVERLAPPED almost entirely.
                        Six such observations are closer to two.
no config filter        ranking_runs selected on status + date only, so runs
                        produced by DIFFERENT factor weights were averaged into
                        one curve. This repo added _detect_config_skew because
                        mixing configs across one chain was a bug; averaging
                        them across a diagnostic is the same bug.
regimes pooled          recorded per sampled run, then averaged away. A factor
                        can be monotone in bull_calm and inverted in bear_stress.
unbounded fwd price     the forward CTE took the last close <= d1 with NO lower
                        bound, so a name that stopped printing after d0 resolved
                        to its OWN baseline — a delisted position scored as
                        exactly FLAT. Delisting for cause concentrates in
                        low-ranked names, so this INFLATED the bottom deciles and
                        SHRANK top-minus-bottom: the bias ran against us.
no uncertainty          a point estimate and a monotone fraction, nothing else.
CALIB_MAX_DATES = 12    in the tunnel, on a corpus supporting ~250 independent
                        anchors.
```

**Root cause: two implementations.** `services/bt-engine/app/calibration.py` and
an inline copy in the evaluator's `packet.py`. They drifted, and the live one is
where every defect landed. The math is now canonical in
`shared/stock_strategy_shared/calibration.py` (NEW shared module ⇒ deploys need
`docker build --network host -t stocker-base:latest -f Dockerfile.base .` FIRST);
bt-engine's module is a re-export shim, the same treatment `rank`/`select` got.

**What the section now reports, and why each one is load-bearing:**

```text
n_dates                 INDEPENDENT anchors, spaced >= one horizon apart via
                        `space_out`. Newest-first, so spacing thins the past.
per_date_ic             mean / median / share_positive / CI of the per-date rank
                        IC. Orientation follows the published convention
                        (positive = the ranking predicts returns) so it can be
                        compared against literature. NOTE a mean IC near 0.02 is
                        NORMAL for equity factors and does NOT imply decile-by-
                        decile monotonicity — the prompt says so explicitly,
                        because demanding 9/9 adjacent monotonicity from IC 0.02
                        asks for something no real factor model delivers.
spread_ci               percentile bootstrap over the per-date spreads, with
                        prob_positive. Deterministic seed: a CI that moves
                        between runs is not quotable.
missing_endpoint_rate   share of ranked names dropped for want of a price at
                        either end — the delisting exposure, now visible.
by_regime               per-regime curves, suppressed below 2 dates in a regime
                        (one observation restated as a regime finding is the
                        most misleading thing this section could emit).
rank_dates_excluded_    how many dates were left out for belonging to another
  other_config          config. A small sample must READ as a small sample
                        rather than be padded.
```

Live: `CALIB_MAX_RUNS` 6 → 24 over `CALIB_LOOKBACK_DAYS` 730 (both env-tunable).
Tunnel: `CALIB_MAX_DATES` 12 → 60 (`BT_CALIB_MAX_DATES`), spaced before sampling.

Not fixed here, and worth stating: the review's surviving *substantive* findings
— that 126-day momentum alone may beat the `[252,126]` blend, and that liquidity
belongs as an investability gate rather than a weighted alpha — are now
corroborated by three and four independent sources respectively. Those are
config questions for the wind tunnel, not measurement bugs, and they go through
`queue_strategy_experiment` like anything else.

### 4. Shadow champion/challenger (Item 4)

An optional CHALLENGER config (`CHALLENGER_CONFIG_PATH`, e.g.
`strategies/challenger.yaml`) is built into a THEORETICAL daily target by the
pipeline right after each successful delta step — fire-and-forget background
task, reusing the pipeline's own persisted factor scores plus the shared
canonical rank/select (no second factor computation, no vetter, no orders,
no risk checks — shadow_runs rows only, migration 0046). The evaluator packet
compares champion vs challenger theoretical forward returns over the
accumulated shadow history. Promotion stays HUMAN: the packet is evidence; the
Apply click (or a config swap) is the only way a challenger becomes champion.
Absent CHALLENGER_CONFIG_PATH the feature is fully inert.

(Item 2 of the same adoption batch — rolling multi-window walk-forward +
untouched holdout — lives in the backtest stack; see
docs/backtester-v2-plan.md.)

### Audit-3 refinements (2026-07, measurement-correctness fixes)

Three fixes applied before trusting what the closed-loop layer measures:

1. **Shadow comparison is FIXED-HORIZON** (packet `shadow_vs_champion`): each
   day's challenger and champion targets are scored over the SAME 20-session
   span from the same anchor session; days whose horizon hasn't elapsed are
   excluded (`n_pending_horizon`), never averaged in at a shorter horizon.
   The section's wording is honest about scope: the shadow is an *alternative
   theoretical construction using the champion's factor inputs* (no vetter /
   falling-knife / beta overlay on the shadow side), daily spans overlap
   (trend, not t-stat), and the full turnover/cost-aware comparison is a
   wind-tunnel run of the challenger config.
2. **Outcome labels carry per-horizon staleness** (migration 0047,
   `stale_1d/5d/20d/60d` = sessions between the print a label used and its
   horizon session). Hold-at-last-price is correct for acquisitions but
   optimistic for bankruptcy delistings; rather than pretending AV provides
   delisting returns, stale labels are visible and the packet's headline
   averages EXCLUDE labels > 5 sessions stale (reported as `n_stale_20d`).
3. **Shadow lineage is pinned**: the delta step passes its own
   `source_ranking_run_id` into `_run_shadow_build`, so the async shadow task
   can no longer attach to a newer ranking that completed in between.

## Design Decision: auto-promotion of strategy configs (Phase 6d, PAPER mode — 2026-07)

Owner decision: the evaluator is a COMPONENT of the money-maximizing system,
not an auditor of it. Config changes no longer require a human click; human
approval remains ONLY for structural changes (code, new data sources, risk-env
changes, going live). Justification: the account is PAPER — the blast radius
of a bad auto-applied config is paper losses and wasted signal-weeks — while
every hard rail is unchanged (strategy-validator schema+safety gate on every
apply, risk-service on every order, kill switch, LLM never touches the order
path or the file write — deterministic code does).

Pipeline (all deterministic; the LLM only AUTHORS candidates):

```text
evaluator queue_strategy_experiment(config, hypothesis)      [LLM authors]
  → bt-scheduler daily lane runs it over the RECENT window   [deterministic]
      (EXPERIMENT_RECENT_YEARS, default 3 — "current era" relevance;
       full-history floor deferred until bt-engine's memory-lean loader,
       full-universe 20y does not fit the 4g cap)
  → promotion gate promotion_eligible(candidate, baseline):  [deterministic]
      CAGR edge ≥ PROMOTE_MARGIN (default +1pp) vs the recent-window BASELINE
      (active config, auto-run first), max_drawdown not worse than baseline by
      more than PROMOTE_DD_TOLERANCE (default 5pp)
  → pass → artifacts/bt/promotion.json (config + evidence)   [file bridge]
  → live api promotion watcher (AUTO_PROMOTION_ENABLED):     [deterministic]
      validates the WHOLE config through the strategy-validator service
      (fail-closed), archives before/after, writes a config_changes audit row
      (config_field '__full_config__', applied_by 'auto_promotion'), atomically
      replaces the active YAML; next chain run picks it up (per-run reload;
      mid-chain applies surface via the config-pin skew detector)
  → the promoted-from candidate stays in experiments.json; the shadow
      challenger + decision ledger keep measuring it live-forward
```

Dedup/idempotency: the watcher records the last-processed promotion hash in
artifacts/config/promotion_state.json — a promotion applies once; a REJECTED
promotion (validator) is recorded so it never loops; validator-unreachable is
NOT recorded (retries next poll, fail-closed).

Revert path: every apply archives the prior YAML under
artifacts/config/history/ — revert = copy it back over the active file (next
run reloads) and git-commit; the config_changes row + evidence say exactly
what was applied and why.

Review findings applied (2026-07, post-6d code review):
- YARDSTICK INTEGRITY. Two defects made auto-promotion unsound and are fixed:
  (a) WINDOW DRIFT — the baseline ran once on [T−3y, T] while candidates ran
      days later on [T+Δ−3y, T+Δ]; the shift alone hands a candidate free CAGR
      and could promote noise. Candidates now run on the baseline's PINNED
      window, and the gate refuses a window mismatch outright.
  (b) STALE YARDSTICK — the baseline was re-run only if missing, so after a
      promotion every later candidate was still gated against an ANCESTOR
      config. Each promotion drifted the yardstick further from what is really
      live, and could promote a config WORSE than the running one. The lane now
      invalidates the baseline whenever a promotion has been APPLIED live
      (logic.baseline_is_valid, keyed on the api's promotion_state.json) and
      re-runs it before gating anything else.
- SHADOW COHERENCE. The shadow re-ranks the CHAMPION's persisted factor scores,
  so a challenger whose factor_engine differs needs different inputs entirely;
  it is now SKIPPED with a loud log instead of publishing an incoherent
  comparison (such candidates belong in the wind tunnel, which recomputes
  factors).

LIVE-MONEY PRECONDITIONS (must be revisited before ALPACA_BASE_URL points at
real money): raise PROMOTE_MARGIN, add the full-history floor + minimum-trades
+ regime-diversity gates, require a shadow live-forward edge over N weeks, and
restore human approval or a bounded-knob whitelist. Recorded here so going
live forces this review.

## Design Decision: period_a/period_b, not tune/validate (2026-07)

The names oversold the rigour. NOTHING is tuned: the baseline is the active
config measured as-is, and a candidate is authored by the evaluator from
reasoning and the packet — never fitted to the first window. Nor is the second
span a true hold-out; the model has read all of market history, so nothing it
authors is genuinely out-of-sample (the shadow challenger is the honest verdict,
this is the cheap pre-filter).

What the split actually buys is STABILITY: the edge must appear in TWO different
spans rather than one. For a stress regime the two spans are crash/recovery
halves, where "tune/validate" was actively wrong.

So the lane and everything a human or the evaluator reads now say `period_a`
(earlier) / `period_b` (later hold-out).

SCOPE, deliberately narrow. bt-engine's request schema still speaks
`tune_start`/`validate_start` and its results `in_sample`/`out_sample`; those are
the engine's own API. `_engine_window_keys()` in bt-scheduler is the ONE
translation point. Renaming across that service boundary would widen the blast
radius on a seam that has already produced a dead-loop bug from a key mismatch
(`window` vs `windows`), for no gain — the engine's field names are not read by
anyone the naming was misleading.

The rename also caught a live trap: `derive_windows` (the legacy grid path) is
splatted STRAIGHT into the /sweeps/run payload, so renaming its keys silently
broke that path while every lane test stayed green. It keeps the engine
vocabulary, and a test now pins that it must.

## Design Decision: terminal-wealth distributions in the promotion gate (2026-07)

The gate compared two configs on CAGR and one realised `max_drawdown` — one
number from one run through history. History ran once, so that answers "what
happened", not "what is likely". Two consequences, both material now that
promotion is automatic:

  * it could not separate BETTER from LUCKIER. A +1pp CAGR edge over ~100
    rebalances can come from two positions that happened to land well.
  * it was blind to the left tail. A candidate carrying a fat tail that simply
    did not fire looked identical to a genuinely safe one — while the stated
    objective is compounded WEALTH, whose enemy is precisely the drawdown
    arithmetic cannot recover from.

bt-engine now resamples each run's realised daily returns (circular block
bootstrap, `app/bootstrap.py`) into a distribution of terminal wealth, reported
on every summary as `terminal_wealth`: median, p5/p25/p75/p95, `prob_loss`, and
— paired with the SPY leg — `prob_beat_benchmark`.

Design choices, each load-bearing and each test-pinned:
  CIRCULAR blocks so every observation has equal draw probability; a
    non-circular bootstrap under-samples both ends, biasing the very tail being
    measured.
  BLOCKS not IID draws, because equity returns cluster; IID resampling destroys
    that and understates the tail.
  PAIRED benchmark resampling (same index draw) so "probability of beating SPY"
    preserves co-movement instead of comparing two independently shuffled
    worlds.
  SEEDED, because reproducibility is a system-wide contract.
  REFUSES to answer below two blocks of data rather than fabricating a
    distribution from five points.

`promotion_eligible_2w` gains a fourth condition: the candidate's 5th-percentile
terminal wealth, as a MULTIPLE of starting capital, may not sit more than
`BT_PROMOTE_TAIL_TOLERANCE` (default 0.05) below the baseline's. The rule lives
in `shared/stock_strategy_shared/wealth.py` because bt-engine PRODUCES the
distribution and bt-scheduler CONSUMES it — two copies of a promotion criterion
is exactly the drift that has bitten this system before.

It is INERT when either side lacks a distribution (older rows, stress-regime
runs). A newly added gate condition must never silently block every promotion
because a historical row lacks a field, and it cannot rescue a candidate that
fails an earlier condition — a spectacular tail does not paper over a missing
edge.

HONEST LIMIT, stated in the module and worth repeating: a 2-year window at
weekly rebalancing is ~100 observations, and a bootstrap of 100 observations is
itself noisy. This makes the uncertainty visible and correctly signed; it does
not manufacture information. The expected effect is that the gate promotes LESS
often, refusing marginal candidates it previously waved through — a brake, not
an accelerator.

DEPLOY NOTE: `wealth.py` is a NEW module under shared/, so `stocker-base` must
be rebuilt before the services that import it.

## Design Decision: score the evaluator's own predictions (2026-07)

The evaluator writes an `expected_effect` on every recommendation and nobody
ever checked. There was therefore no way to answer the only question that
matters about it: does the weekly review beat "change nothing"? It holds the
strategy to account with forward-return ledgers and calibration curves while
being itself unmeasured.

`queue_strategy_experiment` now takes an optional `predicted_tune_cagr_edge` —
a committed number for how much the candidate should beat the BASELINE's
tune-window CAGR (0.02 = +2pp). Validated at queue time to [-1, 1] so a model
passing "2" (percent) cannot poison the record. When the lane completes,
`score_prediction` (pure, in bt-scheduler/app/logic.py) computes the actual edge
on the SAME windows the gate used and stores predicted / actual / signed error /
direction. The packet's `prediction_scorecard` section is the running tally.

**The headline is BIAS, not accuracy.** `mean_signed_error` is reported
alongside `mean_absolute_error` precisely because they answer different
questions: an evaluator that is right about direction every time but inflates
every magnitude by 3pp has the SAME absolute error as an unbiased noisy one, and
needs a completely different correction. The prompt tells it to subtract its own
measured bias from the next prediction.

Deliberate choices:
- Scoring is INDEPENDENT of promotion. Most candidates are refused, and those
  forecasts are exactly the ones worth learning from — a test asserts the
  scoring call sits outside the promotion branch.
- Candidates queued WITHOUT a prediction are counted and named in the scorecard
  rather than silently shrinking the sample.
- Regime runs have no comparable baseline, so they score to None rather than
  fabricating an edge.
- Inflating a prediction to justify a candidate is self-defeating by
  construction: it only makes the model measurably over-optimistic. That is the
  incentive property the design rests on.

Sample sizes will be tiny for a long time; the section says so, and it is a
running tally rather than a verdict.

## Design Decision: the shadow challenger is the only uncontaminated evidence (2026-07)

Every backtest is scored on history the model has already read, so nothing the
evaluator authors is truly out-of-sample — and the held-out validate window is
drawn from the same era as the tune window, which is why it is a weak filter.
The shadow challenger is the one measurement immune to that: the target for day
D is composed from data <= D and scored on days that had not yet happened.

It had never produced a single row, and the reason was a trap. The shadow
re-ranks the champion's PERSISTED factor scores, so a challenger whose
`factor_engine` differs is refused — and EVERY strategy YAML in the repo except
the active one differs there. "Just set CHALLENGER_CONFIG_PATH" would have
yielded zero rows and one stdout line: indistinguishable from the feature being
switched off. Same failure class as the day's other bugs (a path that looks
enabled, does nothing, and reports it only where nobody looks).

Three changes:

1. `strategies/challenger_lowvol_v1.yaml` — a SHADOW-COMPATIBLE challenger
   (identical factor_engine, changed weights). The change under test is the
   evaluator's own standing recommendation, which the experiment lane has never
   managed to validate: momentum 0.36 -> 0.28 into low_volatility (0.14 ->
   0.18) and quality (0.20 -> 0.24), on the evidence that momentum's marginal
   IC has averaged ~0 over seven live weeks while the other two stayed
   positive. So the cleanest evidence channel is pointed at the most contested
   open question.
2. The factor_engine refusal is PERSISTED to `shadow_runs` (status='skipped'
   with the reason), not merely printed.
3. `_shadow_vs_champion` distinguishes "nothing configured" from "configured
   but refused every day" — the old note asserted the first for both, which
   would send the reader to fix something that is not broken while a silent
   challenger accumulated nothing. A refusal now reports as a TOOLING GAP.

`tests/pipeline/test_shadow_challenger.py` asserts the configured challenger is
shadow-compatible, that it actually differs from the champion, that the refusal
is persisted, and that the packet can tell the two causes apart.

Promotion is unaffected: the gate reads `experiment_lane`, never `shadow_runs`.
Wiring shadow evidence into the gate would push a config change from ~2 days to
~2-3 months (20 sessions per data point, overlapping spans) — a real trade-off,
deliberately not taken.

## Design Decision: named stress regimes + evaluator read access to the wind tunnel (2026-07)

Two related gaps, both exposed the day the simulator's `-96%` bug was found by
hand:

1. The wind tunnel holds Sharadar prices back to **2004**, but the experiment
   lane hardcoded a rolling `recent 3y tune + 12mo hold-out`. Nothing in the
   loop could ask the data about 2008. A config tuned only on a recent window
   has never been shown a crisis — precisely the overfitting the hold-out
   cannot catch, because the hold-out is drawn from the same era.
2. The evaluator flagged "the experiment lane is non-functional" for four
   consecutive weeks but could not diagnose it: it saw only `error_message`
   strings crossing the artifact bridge. It could not query `bt_sweeps` for
   run durations, nor `bt_positions`/`bt_trades` — the artifact that actually
   cracked the bug.

### Named stress regimes (diagnostic only)

`STRESS_REGIMES` in `bt-scheduler/app/logic.py` is a FIXED, pre-registered set.
The evaluator requests a regime by NAME; it can never supply raw dates.

```text
gfc_2008          2007-10-01 → 2009-06-30  (split 2008-10-01)
covid_2020        2020-01-02 → 2020-09-30  (split 2020-04-01)
bear_2022         2022-01-03 → 2023-01-31  (split 2022-07-01)
energy_shock_2015 2015-06-01 → 2016-03-31  (split 2015-12-01)
volmageddon_2018  2018-01-02 → 2019-01-31  (split 2018-10-01)
```

Each is chosen for a DISTINCT failure mode, not for being an interesting year:
GFC carries the March-2009 momentum crash (the worst episode in history for a
momentum-tilted book); COVID is the maximally adverse case for a drawdown veto
(it sells the bottom and blocks re-entry through the V); 2022 is a slow
rotation rather than a crash; 2015 is a sector blowup, directly relevant to a
book running ~23% energy; 2018 tests `low_volatility` and the vol-scaled knife.

**Why NAMES and not a date range.** The DSR/`backtest_trials` machinery deflates
for how many CONFIGS were tried, not how many PERIODS. A model free to choose
both is searching two dimensions while being penalised on one, and the
promotion gate compares candidate-vs-baseline on identical windows — so a free
range would let it find the period where its candidate happens to win. A fixed
enumerable set keeps the search space countable.

**The split.** Each regime is cut at a meaningful date into two NON-overlapping
spans carried as the existing `tune`/`validate` fields (crash then recovery for
GFC and COVID; first leg then second for 2022). This reuses
`run_config_both_windows` unchanged and the two numbers are genuinely
informative — but they are NOT a tune/hold-out pair and must never be read as
one.

**Hard rule: a regime run can never promote.** `_experiment_lane` skips the
promotion gate entirely for any entry carrying `regime`. Stress results feed
structural findings and the hypothesis ledger; promotion stays gated on the
standard rolling window alone. Regime fires DO count against
`BT_EXPERIMENTS_PER_WEEK` — engine time is the scarce resource and the model
chooses how to spend it.

**Coverage guard.** A regime whose window predates usable factor history (the
12-1 momentum lookback plus the 200-day regime SMA) or whose fundamentals are
too thin is refused at queue time with a reason, rather than silently
producing a momentum-only composite that measures something other than the
strategy.

### Evaluator read-only access to bt-postgres

A `bt_sql_query` tool, scoped by a Python-side ALLOWLIST to the RESULTS tables:
`bt_sweeps`, `bt_sweep_results`, `bt_sweep_aggregates`, `bt_runs`, `bt_equity`,
`bt_positions`, `bt_trades`. Same guards as the live `sql_query` (single
SELECT/WITH, `SET TRANSACTION READ ONLY`, statement timeout, row cap).

**The raw corpus is deliberately NOT reachable** — `bt_prices` (35M rows) and
`bt_fundamentals` are excluded. Two reasons: an unbounded query can contend
with a running sweep (bt-engine is memory-capped at 4g and pegs a core during a
run), and more importantly ad-hoc SQL over 20 years of history is a
data-dredging path that bypasses the trials accounting entirely. The model
could "find" a pattern in-sample and author a config from it with no trial ever
registered.

**Transport.** bt-postgres already publishes host port 5434, so the evaluator
reaches it via `host.docker.internal` (`extra_hosts: host-gateway`). No shared
docker network and no change to the backtest stack — the isolation decision
(separate compose projects, no lifecycle coupling) is unaffected: a read-only
connection cannot trigger runs or recreate containers. The tool is BEST-EFFORT
and degrades to "unavailable" when bt-postgres is unreachable, exactly like
`web_search` without a Tavily key, so a review never fails because the backtest
machine is down.

Hardening follow-up (not done): a real `READ ONLY` postgres ROLE rather than
relying on the read-only transaction plus allowlist.

## Design Decision: ONE path to the live config (2026-07, owner decision)

The human one-click apply is REMOVED — endpoint (`POST /config/apply`), the
Review-tab Apply buttons, the single-field `queue_experiment` tool, and the
recommendation→single-field harvest. Rationale: two paths to the live config
(a click that skipped the wind tunnel, and a gated backtest) meant the
un-validated one could silently win, and single-field diffs made "what was
tested" differ from "what goes live".

Now: **a complete StrategyConfig is the only currency, and winning the
wind-tunnel gate is the only path.**

```text
evaluator authors a WHOLE candidate config   (queue_strategy_experiment)
  → daily lane scores it vs the current champion on TUNE + HELD-OUT VALIDATE
  → promotion_eligible_2w (deterministic)
  → api promotion watcher: validator-gated, archived, audited, atomic replace
```

To change one field the evaluator sends the whole YAML with that field changed
— so the artifact that was tested IS the artifact that goes live, byte for
byte. `recommendations[]` stay advisory (reasoning, structural findings, things
no config can express) and no longer auto-queue anything.

**Loop integrity — the two links that make this path real.** With one path,
either link failing silently disables strategy evolution entirely while the
system still *looks* busy. Both are now regression-tested:

1. *The lane must reach the candidate.* It only tests a candidate once its
   BASELINE yardstick is valid (`baseline_is_valid`), and validity includes a
   pinned comparison window. That check read `baseline["window"]["start"]`
   while the lane writes `baseline["windows"] = {tune_start, tune_end,
   validate_start, validate_end}` — so every real baseline read "unpinned", the
   lane re-fired the YARDSTICK on every daily slot, and no evaluator candidate
   was ever run. The unit test passed because it asserted against the invented
   shape. Tests now build the entry the way the lane does
   (`test_a_real_lane_baseline_entry_is_accepted`, and the composed seam test
   `test_a_queued_candidate_actually_gets_a_slot`).
2. *The candidate must be COMPARABLE to the yardstick.* The gate refuses to
   compare across windows ("window mismatch vs baseline — not comparable"), but
   `experiment_windows` is derived from `today` and the lane recomputed it on
   every fire. Only one experiment runs per day, so a candidate fired the day
   after its baseline always landed on a different window — auto-promotion was
   structurally unreachable. Candidates now INHERIT the baseline's exact
   windows; because that pins the comparison in time, `baseline_is_valid`
   retires the yardstick once its `validate_end` is older than
   `BT_BASELINE_MAX_AGE_DAYS` (default 30) and the lane re-measures it.
   `BT_EXPERIMENTS_PER_WEEK` counts CANDIDATE fires only: the cap bounds
   multiple testing against our one shared history, and a baseline re-measures
   the config already live — no new hypothesis, no DSR to deflate. Counting it
   meant every yardstick re-run silently ate a candidate slot (and while the
   lane was re-firing the baseline daily it burned the whole weekly budget on
   runs that tested nothing). `/experiments` reports `baselines_this_week`
   separately so a busy lane never reads as "0/5 fired".
3. *The next review must see the outcome.* The gate's verdict
   (`promotion.eligible` / `.reason`), the tune/validate `windows`, and the
   `config_hash` are surfaced in the `experiment_lane` packet section, and
   `experiment_queue` is a TOP-LEVEL packet section (it used to live only
   inside `backtest_lab`, whose own note tells the model that section is
   retired). Without these the evaluator re-proposes theses whose results it
   cannot read.

**Candidate staleness.** A candidate is a whole config frozen at queue time. If
a promotion lands while it is pending, promoting it later would silently REVERT
the newer champion, and its stored diff was computed against a config that is
no longer active. Queue entries therefore record
`queued_against_config_hash`, and the packet flags pending entries whose stamp
no longer matches the live config as `stale_vs_active_config` so the evaluator
re-authors instead of waiting on them.

Escape hatches (unchanged, deliberately manual): override = edit the YAML and
deploy; revert = copy an `artifacts/config/history/` archive back over the
active file. Both leave the git mirror as the audit trail.

## Design Decision: factor-coverage contract between live and the wind tunnel (2026-07)

### The bug this closes

`momentum_rotation_v2` weights `earnings_surprise` at 0.12. The live pipeline
loads the `earnings` table and passes it to `compute_all_factors(earnings=...)`.
**bt-engine never passed the argument, and bt-data never ingested earnings at
all.** Both stacks run the *same* factor code — `sim.py` calls
`live.compute_all_factors(...)`, and `tests/backtester/test_vendor_sync.py`
asserts module identity — so this was never a logic divergence. It was an input
that one side supplied and the other silently omitted.

The failure mode is what makes it dangerous. `composite_scores` renormalizes per
row over the NON-NULL factors, so a missing factor does not score as zero — it
redistributes its weight across the others:

| factor | live | wind tunnel | drift |
|---|---|---|---|
| momentum | 0.360 | 0.409 | +13.6% |
| earnings_surprise | 0.120 | 0.000 | dropped |
| quality / low_vol / value / liquidity / growth | — | — | +13.6% each |

Every wind-tunnel run of `momentum_rotation_v2` scored a config that was not
`momentum_rotation_v2`: no PEAD signal, momentum over-weighted by a seventh. The
renormalization is correct behaviour for a *transiently* null factor on a few
tickers (that is why it exists) and exactly wrong for a factor that is
structurally absent — it produces a plausible number instead of an error.

Worse, the artifact is *weight-sensitive*: a candidate that moves
`earnings_surprise` from 0.12 to 0.06 renormalizes over 0.94 instead of 0.88, so
the tunnel reports a difference that is pure arithmetic. With auto-promotion
enabled (Phase 6d), the loop could act on it.

Two smaller instances of the same class: `bt_fundamentals` carried no
`market_cap` and no shares outstanding, so `small_cap` and `issuance` were null
too. Both are weight-0 in the active config so they never moved a score — but
availability counts weight-0 factors toward `min_non_null_factors` (6), so live
saw ~12 available factors per ticker and the tunnel ~9. Thin-coverage names that
rank live were *unrankable* in backtest: a universe skew affecting every run
regardless of weights.

### The rule

> The wind tunnel may not score a config that puts nonzero weight on a factor it
> cannot compute.

Enforcement is fail-closed and lives in `services/bt-engine/app/coverage.py`:

```text
SUPPORTED_FACTORS   declared per factor WITH the input it needs, so the
                    declaration reads as a contract rather than a list
check_config_coverage(cfg)  static, at request time. Checks every weight vector
                    the config could actually USE — via effective_factor_weights()
                    over all four regimes, so it honours regime_weighting_enabled
                    instead of re-deriving that rule (which would drift)
check_frame_coverage(...)   empirical backstop. Tracks, across the whole run,
                    whether each weighted factor was EVER observed non-null. A
                    factor declared supported but absent from the corpus fails
                    the run instead of renormalizing away
```

`/jobs/run` rejects with 422. `/sweeps/run` rejects a violating BASE config with
422, but routes violating candidate diffs into the existing `extra_dropped`
channel — one bad evaluator proposal must not kill the standing sweep, and
bt-scheduler already marks exactly those proposals `invalid` rather than
`testing` (audit F2). `BT_COVERAGE_ENFORCE=false` disables, default on.

The static check fails fast and cheap; the empirical check cannot lie. Both are
needed: the declaration is hand-maintained and could go stale, and an ingest
outage can empty a column the declaration honestly believes is populated.

### Why teach the tunnel rather than drop the factor from live

Deleting a factor because the test rig cannot see it lets the measuring
instrument dictate the strategy. The resolution is always to close the coverage
gap; removing the factor is the fallback only when the data genuinely cannot be
obtained.

The distinction that matters is **vendor divergence vs definitional
divergence**. Live prices come from Alpha Vantage and wind-tunnel prices from
Sharadar; that is accepted on every factor already. What cannot be accepted is
the same factor NAME computed two different ways — or, as here, existing on one
side only.

### Coverage closed (bt-data)

Sharadar SF1 rows were already being fetched with the needed fields; the mapper
took six and discarded the rest. Now also mapped:

```text
market_cap              ← SF1 marketcap                → small_cap
shares_outstanding      ← SF1 sharesbas (fallback shareswa)
shares_outstanding_prior← the ~year-ago filing (rows[i-4]), the same
                          successive-filing pattern revenue_growth/eps_growth
                          already use                  → issuance
bt_earnings             ← SF1 eps + calendardate + datekey (known-as-of)
```

`bt_earnings` is populated now but NOT yet consumed — it is the raw material for
the SUE definitional-parity work, kept separate so the coverage fix can land and
be verified on its own.

`init_bt.sql` is applied idempotently by bt-data's `_ensure_schema()` on every
startup, so the new columns and table reach an existing bt-postgres without a
manual migration. The SF1 stage must be re-backfilled to populate them; the SEP
price corpus (~35M rows) is untouched.

A stale caveat in `run_simulation` claimed `volume_surge` was uncomputable. It
never was — `compute_volume_surge` reads only `prices_long` volume, which
bt_prices has always carried. Corrected rather than propagated.

### Consequences, stated plainly

* Until SUE parity lands, `earnings_surprise` is uncomputable in the tunnel, so
  the active config fails the coverage check and **auto-promotion is paused**.
  That is the intended state: the alternative is promoting on evidence now known
  to be wrong.
* Every pre-existing `bt_sweeps` / `bt_sweep_results` / `bt_runs` row is void —
  for the `-96%` simulator bleed AND for this. The evaluator has read access to
  those tables, so they must be purged or marked before the next weekly review
  or it will reason over them.
* Adding `market_cap` / issuance coverage CHANGES backtest results even for
  configs that weight neither, by changing which tickers clear
  `min_non_null_factors`. This is a correction, not a regression: the tunnel's
  rankable universe now matches live's.

### The blind spot the contract shared with itself: silent fallbacks (2026-08)

Both checks above ask the same question — **is the factor non-null?** A factor
with a graceful degradation path answers *yes* while computing something else
entirely, so neither check can see it. That is not a gap in the implementation;
it is a gap in the question.

The instance: `quality_use_gross_profitability: true` — set by **every strategy
config in the repo**, including the live `momentum_core_v3` — makes the quality
factor gross-profits-to-assets (Novy-Marx). `compute_quality` falls back to ROE
**per ticker** when `gross_profit`/`total_assets` are missing, which is exactly
right for one filing's vendor blip and was added deliberately (the PBR incident).
But bt-data never mapped SF1's `gp`/`assets`, `bt_fundamentals` had no such
columns, and `bt-engine/app/data.py` never selected them. So the tunnel took that
fallback for every ticker on every date and scored **ROE-quality under a GPA
config, at 25% of the live composite** — while `quality` came out fully
populated, the static gate passed, and `CoverageObserver` recorded it as
observed. Every wind-tunnel number touching quality measured a factor live does
not compute.

Note what the parity manifest said: `factor_engine` was declared HONOURED because
"compute_all_factors is the SAME module live runs". True, and insufficient — the
same module with a different **input column** computes a different factor. Module
identity is a necessary condition for parity, never a sufficient one.

The fix has two halves, and the second is the one that generalizes:

```text
data      SF1 gp/assets → bt_fundamentals.gross_profit/total_assets, through the
          existing sharadar_adapter. Both are LEVEL fields (_level(), not _f()):
          a large bank's assets are legitimately ~$4e12, so the 1e12 RATIO guard
          would have nulled the denominator for exactly the largest names — the
          market_cap trap, one field over.
guard     coverage.DEFINITION_INPUTS + check_definition_coverage(config, frame).
          It asks the OTHER question: did the corpus carry the inputs for the
          factor DEFINITIONS this config selected? Judged on the whole corpus,
          never per ticker (one missing filing is what the fallback is FOR).
          Raised UP FRONT, before any compute — unlike a null factor there is no
          warm-up story that could make an early answer a false positive.
```

Add an entry to `DEFINITION_INPUTS` whenever a factor gains a fallback. A
fallback with no entry is this bug again. And when declaring a config field
HONOURED in a parity manifest, the test is not "same code" — it is "same code
**and** same inputs".

Consequence: the tunnel now REFUSES every config in the repo until the SF1 stage
is re-backfilled to populate the two columns (the ~35M-row price corpus is
untouched). That refusal is the correct state — the alternative is continuing to
score a quality factor nobody configured. Sweep results from before the
re-backfill that touch quality are void.

## Design Decision: container healthchecks probe LIVENESS, never dependencies (2026-07)

### The failure

A cold `docker compose up -d --build` intermittently ends with:

```text
✗ Container stocker-llm-gateway-1     Error      132.8s
dependency failed to start: container stocker-llm-gateway-1 is unhealthy
!! live stack FAILED (rc=1)
```

Running `docker compose up -d` a second time fixes it. That "fixed by retrying"
signature is the tell: nothing is broken, a probe is losing a race.

### Root cause

`llm-gateway`'s `/health` looped over every registered provider and `await`ed
`provider.health_check()`. The Ollama provider is registered UNCONDITIONALLY at
startup — but `ollama` lives behind `--profile ollama`, so on a normal deploy the
hostname `ollama` does not resolve at all. Every probe therefore made a real
network call to a host that does not exist.

The timeouts made that fatal rather than merely wasteful:

```text
ollama health client timeout   5.0s   (_HEALTH_TIMEOUT)
docker healthcheck timeout     5s     (compose)
```

They are EQUAL, so the probe can never win: the moment DNS resolution for the
absent `ollama` service takes the full inner timeout, the outer healthcheck has
already expired — and the probe command (`python -c "import urllib.request…"`)
spends several hundred ms on interpreter startup before the request even begins.
Five consecutive expiries past `start_period` mark the container unhealthy,
`llm-vetter` declares `condition: service_healthy` on it, and the whole live
stack exits rc=1.

Why intermittent, and why a second `up` works: on a cold deploy the compose
network is being created while 17 containers attach and images are still
building, and a lookup for a non-existent name can block. Once warm, Docker's
embedded DNS returns NXDOMAIN immediately, `health_check()` fails in
milliseconds, and the endpoint answers well inside the budget. The 30s
`_HEALTH_CACHE_TTL` then keeps it fast. Nothing about the gateway was ever
actually wrong — including during the failure, since `/health` returns
`{"status": "ok"}` whether or not a provider answers. It was only ever too SLOW.

### The rule

> A container healthcheck answers "is this process serving?" — never "are my
> dependencies up?". A liveness probe that performs external I/O reports someone
> else's outage as its own death, and its failure mode is a deploy that dies
> rather than a service that degrades.

Applied:

```text
llm-gateway  GET /health            liveness only: no I/O, no provider probing
             GET /health/providers  live probe of each provider (humans/UI)
llm-vetter   GET /health            liveness only; no longer calls the gateway
             GET /health/gateway    the gateway round-trip, on request
```

`llm-vetter`'s `/health` was the same bug one level up — its Docker healthcheck
made an HTTP call to the gateway's `/health`, which then probed ollama. A chain
of liveness probes is a chain of shared fate.

### Amplifier: the dependency edge

`llm-vetter` declared `llm-gateway: condition: service_healthy`, which is what
turned one slow probe into `live stack FAILED (rc=1)`. That coupling was never
justified: the vetter runs `mode: drawdown_only` by default and makes NO LLM
calls at all, and even in `llm` mode a gateway that is briefly unavailable should
degrade one chain step, not block the deploy of the trading stack. Changed to
`service_started`, matching what `evaluator` already declares for the same
dependency.

Note this is strictly weaker coupling than it looks: `depends_on` only orders
STARTUP. Neither service can rely on the other being reachable at any later
moment anyway, so ordering-plus-retry is the only honest contract.

### What was deliberately NOT changed

`api`'s `/health` was checked and is already I/O-free (its database reads live in
`/data-freshness`). The healthcheck interval/timeout/retry values are untouched:
with the I/O removed, the existing 5s/5s/5/20s budget has orders of magnitude of
headroom, and widening timeouts to accommodate a probe that should not have been
doing I/O would have hidden the bug rather than fixed it.

## Design Decision: wind-tunnel fidelity batch — cache identity, fill realism, parity manifest (2026-07)

An external audit found eleven defects in the backtest simulator, all verified at
the cited lines. They share one root: the tunnel silently SUBSTITUTES something
plausible where it cannot model the real thing — a renormalized weight, a stale
price, a modern sector label, an emergent eligibility rule. Each substitution
produces a number, and a number is indistinguishable from an answer.

The generalized rule, extending the factor-coverage contract to every config
field:

> Every parameter that can change live behaviour needs an explicit wind-tunnel
> parity declaration and an empirical "was actually exercised" observer.
> Where the tunnel cannot model a parameter, it REFUSES the config rather than
> scoring it as if the parameter were absent.

### 1. Factor-cache identity: version, not shape

`data_fingerprint()` hashed row counts, ticker count and the price date span.
Nothing in that changes when data is CORRECTED IN PLACE. This is not
hypothetical: the SF1 re-backfill that populates `market_cap` /
`shares_outstanding` writes those values onto EXISTING rows — same primary keys,
same counts, same span — so the fingerprint is byte-identical and a surviving
cache would serve factor frames computed without the new columns. The coverage
observer would not catch it either, because both factors are weight-0 in the
active config and therefore never observed.

Replaced with an explicit corpus version: bt-data maintains a single-row
`bt_data_version` table and bumps a fresh UUID at the end of EVERY successful
write stage. bt-engine reads it and keys the cache on it.

FAIL-CLOSED: if the version cannot be read, the cache is DISABLED rather than
falling back to the shape hash. A weak identity is worse than no cache — the
cache is a pure optimization, and correctness must not depend on it.

The shape components are retained ALONGSIDE the version, so a corpus mutated by
something that forgets to bump the version is still likely to invalidate.

### 2. Turnover penalty: implemented, not rejected

An AST diff of the two `greedy_select` call sites (live
`portfolio-builder/app/main.py` vs `bt-engine/app/sim.py`) found exactly two
live-only kwargs — `current_holdings` and `turnover_penalty` — and zero
divergence in `compute_weights`. So a config with `turnover_penalty > 0` was
simulated as though it were 0: the same class as earnings_surprise, one layer up.

The simulator already tracks `qty`, so current holdings are available at
`build_target` time. Implemented rather than gated, on the same principle: teach
the tunnel, do not forbid the strategy. The `turnover_penalty > 0` guard mirrors
live exactly, so a zero penalty passes `current_holdings=None` and the
holdings-agnostic behaviour is bit-identical to before.

### 3. No fill without a print

`_fill` fell back to `last_px` when the fill date had no price, so a pending
trade could execute against a security with no market that day — a halt, a
delisting, a vendor gap. That is not conservative: on a buy it purchases at a
frozen (often lower) price, on a sell it exits a position that could not have
been exited.

It also compounded with the stale-price fix from the `-96%` bleed. That change
made every fill stamp `last_seen` (a fill is proof of a print) — correct for real
fills, but for a PHANTOM fill it reset the delisting countdown, so a dead name
could have its timer refreshed indefinitely by fills at a frozen price.

Now: no print, no fill. The order is dropped (not queued — the next rebalance
re-decides from current state, which is what live does) and recorded in
`unfilled_orders` on the summary with a reason. NOT in `bt_trades`: that table's
`price` is NOT NULL and it means "a trade happened", which is precisely what did
not happen here.

### 4. Delisting: a configurable recovery rate

`cash += qty[t] * last_px[t]` recovered 100% of the last mark, with `tx_cost: 0.0`
written literally into the trade row. A company that stops printing at $2 is
frequently worth a fraction of that; full recovery flatters exactly the
speculative/distressed strategies the evaluator is most likely to propose.

`SimParams.delist_recovery_pct` (default **0.70**) — the proceeds fraction of the
last mark, with the normal transaction cost now applied. The 30% haircut follows
the delisting-return literature (Shumway 1997 finds ≈ −30% for NYSE/AMEX
performance-related delistings; Shumway & Warther 1999 finds worse for NASDAQ),
rounded to one blunt number.

Stated honestly: this is a FLAT rate applied to every delist exit, including
mergers and acquisitions where recovery is typically at or above the last mark.
It is a bias correction, not a model. Set it to 1.0 to restore the previous
behaviour. Distinguishing acquisition from failure requires the delisting REASON,
which becomes available with the point-in-time universe work below and is the
natural follow-up.

### 5. Delist gap measured in real sessions

`DELIST_GAP_DAYS = 7` was documented as trading days but compared as
`(D - last_seen).days > DELIST_GAP_DAYS * 2` — a calendar approximation that
lands nearer 10 sessions than 7, and drifts with holidays. The simulator walks an
explicit list of sessions, so the exact count is available: staleness is now
measured in SESSION INDICES against `all_days`. No approximation, no holiday
drift, and the constant now means what its name says.

### 6/7. Point-in-time sector and universe

`load_universe` read `WHERE snapshot_date = (SELECT MAX(...))`, so a 2011
portfolio was built with 2026 sector labels — future information feeding
sector-neutral scoring, sector group sizes and sector caps. The single snapshot
also meant historical eligibility was inferred from price presence rather than
reconstructed.

Sharadar's TICKERS rows already carry `firstpricedate`, `lastpricedate`,
`isdelisted` and `sicsector`/`sector`; `map_tickers_row` kept ticker, name and
sector and discarded the rest — the same "already fetched, then thrown away"
shape as the SF1 gap. Those fields are now persisted, and the universe is
reconstructed AS OF each simulated date: a ticker is eligible on D when
`firstpricedate <= D <= COALESCE(lastpricedate, ∞)`.

HONEST LIMIT, stated because it would otherwise be mistaken for a full fix:
Sharadar TICKERS is CURRENT-STATE metadata with historical DATE columns. It gives
correct listing/delisting windows; it does NOT give the sector a company was
classified under in 2011. The sector label remains current-state and stays in
`caveats`. Removing that requires a vendor with point-in-time classifications.

### 8. Eligibility scope made explicit — behaviour NOT changed silently

`composite_scores` counts a factor as "available" whenever it is non-null,
regardless of weight, so a weight-0 factor can decide whether a security is
rankable. A data-engineering change (populating a new unused factor) can
therefore move CAGR. Real, and shared with live.

The obvious fix — count only nonzero-weight factors — is NOT applied as a silent
default, because it is a large live strategy change, not a cleanup. Under
`momentum_rotation_v2` it would turn `min_non_null_factors: 6` from "6 of 12
available" into "6 of the 7 weighted", which would sharply shrink the rankable
universe and change what the live book buys.

So the SEMANTICS become explicit and the CHOICE stays with the owner:
`min_non_null_factors_scope: "all" | "weighted"`, defaulting to `"all"` (today's
behaviour, bit-identical). The field is in the parity manifest, so the tunnel and
live can never diverge on it, and flipping it can be backtested first.

### 9. Target status is explicit, not dictionary truthiness

`if target:` conflated "the builder failed / produced nothing usable" with "the
strategy deliberately wants zero exposure". Both mean "hold what we have" today
only because the builder never intentionally returns an empty book — an
assumption a future evaluator-authored config could invalidate silently.

`build_target` now returns a `TargetStatus` alongside the weights:
`SUCCESS_WITH_TARGET` / `SUCCESS_EMPTY_TARGET` / `DEGRADED` / `FAILED`. Only
DEGRADED and FAILED hold the book; SUCCESS_EMPTY_TARGET is honoured as a real
risk-off instruction. The simulator counts each status so a run that spent half
its life DEGRADED is visible rather than merely flat.

### 10/11. Turnover and rebalance counts measure what they claim

One root cause: `turnover_samples` doubled as the turnover series AND the
rebalance counter, and was appended only when trades existed — so
`n_rebalances` meant "rebalance dates that produced trades", and turnover was
computed from DECISION-time intended notional at `last_px`, before fills, and so
could never reconcile with the costs that actually hit equity.

Now `_fill` accumulates REALIZED filled notional, turnover is that over realized
equity, and the counters are separate and named for what they are:
`n_rebalances` (evaluations), `n_rebalances_with_trades`, `total_turnover`,
`avg_turnover` (= total over evaluations, so zero-turnover cycles count).

### The parity manifest

`services/bt-engine/app/parity.py` declares, for every StrategyConfig field,
whether the wind tunnel HONOURS it, IGNORES it, or honours it PARTIALLY, plus a
reason. `check_config_parity(cfg)` refuses (422) a config that sets an IGNORED
field to a non-default value — the coverage contract generalized from factors to
the whole config surface.

Two tests keep it honest: every schema field must be classified (a new field
fails CI until someone decides), and an AST diff asserts the live and tunnel
`greedy_select` / `compute_weights` call sites agree on kwargs — the check that
would have caught the turnover-penalty gap the day it appeared.

## Design Decision: the parity manifest covers BOTH simulators, and is checked against behaviour (2026-07)

### The gap the manifest left

The wind tunnel's manifest shipped the same day an external review pointed out
that there are TWO systems answering "what would this config have done?" — and
only one of them had a gate. Worse, the evaluator's interactive tool posts to the
UNGATED one:

```text
services/evaluator/app/tools.py   run_backtest → BACKTESTER_URL/jobs/backtest-config
                                                 (config-replay)
                                  queue_strategy_experiment → the wind tunnel lane
```

`grep -c "parity\|coverage" services/backtester/app/*.py` returned **0**. So an
evaluator sending `{"factor_engine.momentum_long_window": 500}` to `run_backtest`
got back a clean summary with a Sharpe — computed by re-ranking factor_scores
that production had calculated under the OLD momentum window. The parameter was
silently dropped and a number was returned, which is the earnings-surprise
failure exactly, in the service the LLM queries most.

### Two declarations, one mechanism

`shared/stock_strategy_shared/parity.py` now holds the ENGINE (verdicts,
flattening, defaults, the check); each service holds only its DECLARATION.
Two copies of an interpreting rule is the drift this system keeps hitting, and
the two simulators genuinely model different subsets — config-replay's IGNORED
set is much larger.

**Baseline differs by design**, and this is the subtle part:

```text
wind tunnel    baseline = SCHEMA DEFAULTS. It recomputes everything from raw
               data, so a field it ignores is unmodelled regardless of what
               production was running.
config-replay  baseline = the ACTIVE CONFIG. It re-ranks factor_scores that
               PRODUCTION computed, so a candidate whose factor_engine matches
               production IS correctly served by those stored values — only a
               CHANGE to factor construction is unmodellable.
```

Comparing config-replay against schema defaults refuses the active config itself
(its `momentum_method`, `pe_pb_cap` etc. all differ from defaults) — wrong, and
the fastest way to get a gate switched off.

`run_backtest` now maps the 422 to a message that names the wind tunnel, and does
NOT burn a backtest budget slot — no run happened, and the model must not read a
refusal as "this idea failed". Its tool description was also rewritten: it
previously claimed to use "the live chain's own deterministic code", which is
what steered the model into sending factor-construction diffs.

### Checking the manifest against behaviour

A manifest is a CLAIM. So was the old cache fingerprint ("this identifies the
dataset"), and it was wrong for a long time because nothing checked it.

`tests/parity/` runs config-replay's composer on one frozen, seeded point-in-time
fixture and asserts, per declared field:

```text
HONOURED → changing it CHANGES the target
IGNORED  → changing it leaves the target BIT-IDENTICAL
```

The second direction is the load-bearing one: an IGNORED declaration that is
secretly honoured is merely over-cautious, while an HONOURED one that is secretly
ignored is the original bug.

**It found a real error on its first run.** `min_score_percentile` was declared
IGNORED in BOTH manifests; it is applied inside `rank_universe`
(`strategy_engine/rank.py:98`), the shared module both engines call, and moving
it moved the target. Corrected to HONOURED in both.

It also exposed a lesson about the harness itself: three of the first HONOURED
probes passed for the wrong reason — the values chosen sat outside the binding
range (a 0.15 position cap when every weight was already below it), so they tested
the probe rather than the manifest. The fixture is now calibrated so each probe
demonstrably binds, and `test_the_fixture_produces_a_real_target` asserts the
base target fills the position cap so the comparisons cannot go vacuous.

### What is deliberately NOT claimed

This harness proves each simulator matches its OWN declaration. It does NOT yet
prove the wind tunnel's target equals the LIVE builder's on identical inputs —
that needs live's `_do_build` composition extracted from its DB coupling into a
shared function both call, which is the same treatment `rank`/`select` already
received. Until then live/tunnel parity rests on shared module identity plus the
AST call-site diff, which is strong but not an output-equality proof.

## Design Decision: SUE definition — parity by definition, not by subtraction (2026-07)

The wind tunnel refused every config weighting `earnings_surprise` because live's
SUE is `(reported − estimated) ÷ stdev(surprises)` and Sharadar carries no analyst
estimates. Three ways out: buy an estimates history, drop the factor from live, or
**move BOTH sides to a definition both corpora can compute**. Chosen: the third.

`FactorEngineConfig.sue_method`:

```text
analyst               (reported − estimated), standardized. Live's original.
                      Needs analyst estimates ⇒ the wind tunnel cannot compute it.
seasonal_random_walk  (eps_q − eps_{q-4}), standardized by the ticker's own
                      history of those differences. Foster-Olsen-Shevlin (1984),
                      the classic SUE. Needs only REPORTED eps, which both AV and
                      Sharadar have.
```

Set to `seasonal_random_walk` in the active config, so live and the tunnel now
compute the same number from different vendors — the situation every other factor
is already in, and the one form of divergence this system accepts.

HONEST COST, stated because it is a real downgrade: analyst-based SUE produces
somewhat stronger drift than SRW (Livnat-Mendenhall 2006). We are trading signal
strength for measurability. The reasoning: an evolution loop that CANNOT SEE a
factor will drift the config away from it, and with auto-promotion running that
is a worse failure than a slightly weaker signal. A factor the loop can measure
and tune beats a stronger one it is blind to. Reversible — set `sue_method:
analyst` on both sides if an estimates history is ever bought for the corpus.

Implementation notes:
  - ONE function, `compute_earnings_surprise(..., method=...)`, in the module both
    stacks import. Two implementations of a factor is the drift this system keeps
    paying for.
  - SRW aligns the year-ago quarter by `fiscal_date_ending`, not by row position:
    a missing or restated quarter would silently shift a positional lookup onto
    the wrong period.
  - Point-in-time and the drift window are unchanged and apply to both methods:
    only quarters with `reported_date <= as_of` are visible, and a report older
    than `earnings_drift_window_days` gives a neutral (null) signal.
  - The coverage contract now reads `sue_method`: `earnings_surprise` is SUPPORTED
    under `seasonal_random_walk` and still REFUSED under `analyst`. The gate did
    not become weaker — it became method-aware.

## Design Decision: drift-rebalance thresholds calibrated to book granularity (2026-07)

### The observation

The live account sat at ~8.9% cash for a week in a calm market with the book at
its 35-name capacity, target exposure 0.975, and vol targeting NOT binding
(book vol ~9% vs the 0.18 target). Order-flow forensics showed a healthy
executor (every intent eventually submitted at the open and filled), so the gap
was not a leak — it decomposed as: 2.5% designed `cash_reserve` + ~1.2pp
in-flight rotation + **~5pp of aggregate drift the rebalancer is structurally
blind to**.

### Root cause

`delta_engine.rebalance_drift_threshold` defaulted to 0.02 ABSOLUTE (2pp). With
35 positions the per-name target weight is 0.975/35 ≈ 2.79%, so a buy_add fires
only when a position drifts from 2.79% to below 0.79% — a ~70% relative loss of
weight. The threshold was calibrated for chunky books (10% positions, where 2pp
is a meaningful wobble) and is effectively unreachable at this granularity.
Meanwhile winners lift total equity, mechanically shrinking every other
position's weight by ~0.1–0.2pp each; no single name ever trips the gate, and
the aggregate accumulates as permanent idle cash (~0.5%/yr of expected-return
drag at a 10% hurdle).

### The rule

Drift thresholds must be reachable at the book's actual position granularity: a
position that has lost a MATERIAL fraction (~20%) of its target weight must be
able to trip the gate. The active config (momentum_rotation_v2) now sets:

```yaml
delta_engine:
  rebalance_drift_threshold: 0.005    # 0.5pp absolute (was default 0.02)
  rebalance_min_relative_drift: 0.15  # AND >= 15% of target weight
  rebalance_min_trade_value: 250      # AND >= $250 of correction
```

The three gates compose: the absolute floor stops noise-trading on tiny drifts,
the relative floor stops the 0.5pp absolute from churning LARGE positions
(a 8% position needs 1.2pp, not 0.5pp), and the dollar floor stops economically
meaningless orders regardless of weights. For the current book the absolute
gate binds (0.5pp > 15% x 2.79pp = 0.42pp); the relative gate takes over as
position weights grow.

Trade-off accepted: a few more small orders per week (spread cost, and
sell_trims count against MAX_DAILY_TURNOVER_PCT). Both simulators are safe:
bt-engine HONOURS all three fields (drift trims are modelled, so the lane can
score this config), and config-replay's `delta_engine: IGNORED-but-inert`
declaration never refuses it. A regression test pins the reachability
arithmetic to the active config so a future max_positions or threshold change
that re-creates the unreachable-gate state fails CI instead of silently
re-accumulating cash.

## Design Decision: audit windows measured in SESSIONS, and pooled across builds (2026-07)

### Two defects in the same evidence path

The W30 review reported "selection/gate audits are still 2026-07-17 — identical
to last review, so no streak was extended and cap_blocked>selected remains a
single window". Investigating why exposed two problems in how the packet builds
its outcome evidence.

**1. Calendar days masquerading as sessions.** `_selection_audit` / `_gate_audit`
deliberately anchor on a build old enough to HAVE a forward window (auditing
yesterday's build returns `fwd_return == 0.0` for every name — the W27 report
correctly read that as no signal). But the cutoff subtracted
`timedelta(days=FWD_MIN_DAYS)` — CALENDAR days — while the docstring promised
"`>= FWD_MIN_DAYS` of prices". On a weekend review the two coincide by luck; a
mid-week review lands the cutoff on the prior Friday and gets ~3 sessions of
forward window while the packet reports `fwd_window_days: 7`. A section whose
entire job is honest evidence was overstating its own sample.

**2. Single-window by construction.** The audit anchored ONE build and started
over every week, so the selected / cap_blocked / out_ranked comparison could
never accumulate. That is why the evaluator kept writing "single window" and
could never justify a change to the builder's caps: the question "do the
diversification caps reject winners?" needs many windows, and the design threw
each one away.

### The rule

```text
A forward window is measured in TRADING SESSIONS, never calendar days.
An outcome comparison pools MANY builds at a FIXED horizon, never one build
  measured to 'now'.
```

Both halves matter and the second depends on the first. Pooling builds that are
each measured "from build date to the latest close" would be invalid: the oldest
build gets the longest window, so it dominates the average and the pooled number
measures elapsed time as much as selection quality. Every pooled build is
therefore scored over EXACTLY `EVALUATOR_FWD_SESSIONS` sessions — the same
fixed-horizon discipline already adopted for the shadow comparison and the
decision ledger.

**The horizon is 21 sessions (2026-08). It was 5.** The selection and gate audits
answer "did the ranker miss winners / did the caps reject winners / did the vetter
exclude winners"; the owner objective is roughly one-month continuation. At 5 they
judged a WEEK, and their conclusions were read into reviews as if they answered the
month — one of them ("cap_blocked beat selected in 6 of 8 windows") drove a queued
candidate. Meanwhile `SHADOW_HORIZON_SESSIONS` and `CALIB_HORIZON_SESSIONS` were
already 20 and the wind tunnel promotes on multi-year compounded return, so the loop
ran three horizons against one objective and could improve any of them without
improving the goal.

The cost is real and was the original reason for 5: a build cannot be scored until
21 sessions of forward data exist, so each review pools fewer builds. A fast answer
to the wrong question is not a cheaper answer.

Implementation:

```text
_session_dates()      the SPY trading calendar (the same source the rest of the
                      packet keys on), read once per audit.
_fixed_horizon_returns()  base = last close <= build date; end = exactly H
                      sessions later. Delisted names take their last available
                      close (no phantom recovery).
_selection_audit()    pools the newest EVALUATOR_SELECTION_AUDIT_BUILDS (default
                      8) authoritative builds (superseded_at IS NULL, one per
                      portfolio_date) that have a full H-session window.
```

The pooled output reports, per outcome class, the mean forward return AND the
number of observations — plus the statistic that actually decides the question:
`windows_cap_blocked_beat_selected` out of `n_builds`. "cap_blocked beat
selected in 6 of 8 windows" is evidence; one window is an anecdote. Ticker-level
detail (`candidates`) stays scoped to the single most recent qualifying build so
the packet does not grow by 8x.

`fwd_window_days` is replaced by `fwd_window_sessions` (the honest unit) with
`fwd_window_calendar_days` kept alongside for context — the mislabel is not
preserved for compatibility, because the whole point is that the evaluator was
being told a number that was not true.

## Design Decision: search breadth — fill the lane with INDEPENDENT hypotheses (2026-07)

### The bottleneck was neither the gate nor the lane

The concern was "the safeguards are too strict, nothing will ever promote".
Measurement says otherwise: the per-review cap is
`EVALUATOR_MAX_QUEUED_EXPERIMENTS` (4) and the lane's weekly candidate cap is
`BT_EXPERIMENTS_PER_WEEK` (5) — and the W30 review queued ONE candidate. Four
lane slots sat idle. The system was not rejecting ideas; it was not generating
them.

At 1 candidate/week and a plausible 10-20% gate pass rate, a promotion arrives
every 5-10 weeks. At 4-5/week, every 1.5-2.5 weeks — a 4x speedup with NO
change to the acceptance criteria. Search throughput and evaluation rigour are
separate dials and must be turned separately; loosening a gate to compensate
for an idle searcher is the wrong trade.

### Why the evaluator under-generated

Nothing was broken. An LLM told "queue an experiment if you believe one is
warranted" optimises for PRECISION — avoid bad ideas — when what the loop needs
is RECALL, expected information gain per week. The prompt now asks for up to
`MAX_QUEUED_EXPERIMENTS` independent hypotheses AND requires the model to
account for every unused slot. That last part matters more than the raise: the
model may still queue one, but it must say why the other four had lower expected
information value. Idle capacity becomes visible and intentional instead of
silent.

### Independence is enforced, not requested

Four variants of one parameter are ONE hypothesis:

```text
momentum threshold 0.72 / 0.74 / 0.76 / 0.78   → one hypothesis, four slots burnt
factor weight / exit hysteresis / sector cap / vol target
                                               → four assumptions probed
```

Relying on instruction alone for the property the whole change depends on
repeats the mistake that caused the under-generation. `queue_strategy_experiment`
therefore requires a structured `mechanism` label from a fixed vocabulary, and
`experiment_diversity_conflict()` (pure) rejects a candidate that either:

```text
duplicates a PENDING candidate's mechanism   (same assumption, second draw)
duplicates a PENDING candidate's field set   (same knobs, different values)
```

Config topology is not a perfect proxy for economic hypothesis — two candidates
can share a field while testing different mechanisms, or touch different fields
within one mechanism. So the MECHANISM label is authoritative and the field-set
check is the backstop, not the reverse. Overlap short of equality is reported to
the model, not refused.

The label also fixes a real gap in what a FAILURE teaches. Results were
attributable only per config_hash, so "exit-hysteresis changes have now failed
4 for 4" was not computable. The packet's experiment_lane now aggregates
outcomes BY MECHANISM, which is what turns a pile of individual rejections into
"this class of intervention does not work here" — the sharpest thing a failed
experiment can say.

### Deliberately NOT done

Gate thresholds are untouched. The first valid baseline completed 2026-07-26;
there is no track record of the gate refusing good candidates, and re-tuning
`BT_PROMOTE_MARGIN` / `BT_PROMOTE_VALIDATE_TOL` now would be fitting to zero
observations. Fill the lane first, measure the real pass rate, then decide.

Expect the deflated Sharpe the evaluator reads to FALL as the trial count
climbs. That is the multiple-testing correction working, not strategy decay,
and it must not be "fixed" by weakening the correction.

## Design Decision: a promotion is a REVERSIBLE experiment — displaced-champion shadow + auto-revert (2026-07)

### The gap

Auto-promotion was a one-way door. A candidate that cleared the gate became the
live config and stayed there until some LATER candidate displaced it, and
NOTHING measured whether the switch actually helped. Two consequences:

```text
1. no feedback on the switching POLICY. The wind tunnel scores each candidate
   in isolation; nobody ever asked "does promoting beat freezing the config?".
   Every promotion is locally justified while the sequence can still lose —
   the classic factor-timing failure, and structurally invisible here.
2. the gate had to carry all the weight. When being wrong is unbounded and
   permanent, the acceptance criteria must be strict, which is what makes the
   loop slow. Rigour was substituting for reversibility.
```

"Fail fast and cheap" means lowering the COST of being wrong, not the evidence
bar. That is this change; the gate is untouched.

### The rule

```text
When a promotion is applied, the DISPLACED champion keeps running as a shadow.
If it beats the new champion by a material margin over a full evaluation
window, deterministic code reverts.
```

The comparison is TARGET vs TARGET, both theoretical, over the SAME fixed
session horizon: the new champion's real target book (portfolio_holdings) and
the displaced champion's shadow target (shadow_runs), each scored as a weighted
forward return. Comparing REALIZED equity against a theoretical shadow would be
biased — realized carries costs, slippage and execution timing the shadow does
not — so the honest test holds construction constant and varies only the config.

Flow:

```text
promotion applied ──▶ api writes artifacts/config/displaced_champion.yaml
                      + promotion_state{promoted_hash, displaced_hash, at}
                            │
      each successful delta ▼
                      pipeline runs a SECOND shadow build for that file
                      (same machinery as CHALLENGER_CONFIG_PATH, role tagged)
                            │
        daily, in the api   ▼
                      revert_decision(champion_r, displaced_r, ...)  ← PURE
                            │ displaced ahead by >= margin over >= min sessions
                            ▼
                      revert: validate → archive → audit(applied_by=
                      'auto_revert') → atomic replace → BLOCKLIST the hash
```

### Guards, and why each exists

```text
ping-pong        A reverted promotion hash is recorded in promotion_state's
                 `reverted_hashes`; _check_promotion REFUSES to re-apply it.
                 Without this the lane re-promotes the same winning candidate
                 the next evening and the config oscillates forever.
one shot         Only the MOST RECENT promotion is revertible, and reverting
                 clears the displaced file. Chained reverts would walk the
                 config backwards through history on accumulated noise.
sample floor     REVERT_MIN_SESSIONS (default 20) of FULLY ELAPSED horizons.
                 Consecutive daily spans overlap heavily, so 20 days is far
                 fewer than 20 independent observations — the floor is a
                 minimum, not a sufficiency claim, and the margin does the
                 real work.
margin           REVERT_MARGIN (default 0.02 = 2pp annualised-equivalent
                 spread). Deliberately material: a revert is itself a config
                 change with its own turnover cost, so it must clear noise,
                 not merely register it.
fail-closed      No shadow data, unparseable file, or validator unreachable →
                 NO revert. Absence of evidence never triggers a config change.
inert by default REVERT_ENABLED gates the whole path; with no promotion having
                 happened there is no displaced file and nothing runs.
```

### What this does NOT claim

The shadow inherits the champion's persisted factor scores, so a displaced
config differing in `factor_engine` cannot be shadowed — the same coherence
guard the challenger path already applies, for the same reason. Such a
promotion is simply not revertible-by-measurement, and the log says so rather
than silently comparing incoherent inputs.

It also does not make the promotion gate safe to loosen on its own evidence:
this measures the LAST promotion, not the policy. Enough reverts (or their
absence) accumulating in `config_changes` is what will eventually justify
moving `BT_PROMOTE_MARGIN` — and that decision stays manual.

## Design Decision: deterministic market context — explain the environment, do not chase it (2026-07)

### The gap

The evaluator was asked to adapt the strategy while seeing the portfolio's
results but not the environment producing them. It knew the book returned X and
SPY returned Y; it did not know whether that happened in a vol spike, a breadth
collapse, a mega-cap melt-up or a broad rotation. That makes a whole class of
finding uninterpretable: a −17% excess against SPY reads as "the factor model is
broken" when the measurable truth may be "SPY's return was concentrated in seven
names and a 35-name diversified book structurally cannot track that".

### Why NOT a news/sentiment feed

The obvious fix — have the review search the web for wars, tariffs, macro
headlines — was considered and deliberately rejected for now:

```text
the boundary does not hold  The evaluator's only lever is a config change. Put
                            a narrative in its context and the sole way to ACT
                            on it is to change the strategy — regime chasing
                            arriving through the back door with a diagnostic
                            label on it. Intent in a prompt does not bind; the
                            model acts through the lever it was given.
least reliable input        Every other packet section is measured (IC, forward
                            returns, gate verdicts). Sentiment is unverifiable,
                            already priced in by construction, and SALIENT — it
                            can dominate the reasoning precisely because it is
                            the most vivid item among numbers.
injection surface           Arbitrary web text entering a context that authors
                            live config candidates.
reproducibility             Two reviews on identical data would diverge because
                            the web moved, adding noise to the prediction
                            scorecard and to week-over-week comparison.
```

The decisive observation: the diagnostic value wanted here is QUANTITATIVE. A
narrow mega-cap rally IS "top-25 median 21d return minus universe median". A
tariff shock IS a vol regime change plus sector dispersion. The headline is a
label on a pattern the price data already contains — so measure the pattern.

### What the section carries

`market_context` (packet, deterministic, no LLM, no external calls):

```text
regime      current label, CONSECUTIVE sessions held, SPY vs its slow SMA,
            realized vol, and that vol's percentile against its own 2y history
            (a level means nothing without its own distribution).
breadth     share of the ranked universe above its 200d / 50d average, and share
            with a positive 21d / 63d return. A rally the book cannot join looks
            exactly like a broken factor model until breadth is on the page.
leadership  cap-weighted MINUS equal-weighted return over the same names —
            the direct narrowness measure, and the one that separates "we
            picked badly" from "the index was seven stocks". The SPY-top-25
            median comparison is kept as a fallback proxy for when market-cap
            coverage is thin, and is named for what it is: a median cannot
            measure contribution, because it treats a $3T name and a $200B name
            identically.
dispersion  cross-sectional stdev of 21d returns (is stock selection even being
            rewarded this month?) plus the best-minus-worst sector spread.
```

Sourced from `regime_snapshots` (already carries SPY/vol state) and one bounded
aggregate over `daily_prices` for the tickers in the latest ranking — the
investable pool, not the raw universe, and capped at 200 sessions per ticker so
this never becomes another full-table scan on a hot path.

Two corrections from review, both worth recording because each was a way of
reporting a number that was not what it claimed:

```text
one row per SESSION   regime_snapshots has NO unique constraint on
                      snapshot_date and the pipeline plain-INSERTs, so a manual
                      chain re-run writes a second row for the same session.
                      Counting rows made `sessions_held` and the vol percentile
                      partly measure how often someone pressed Run. Fixed with
                      DISTINCT ON (snapshot_date) ... ORDER BY snapshot_date
                      DESC, calculated_at DESC.
name the POOL         breadth is over the RANKED universe, which has already
                      passed the investability floors and factor gates. Calling
                      that "market breadth" overstates it, and the bias has a
                      direction: in a small-cap selloff the weak tail is already
                      excluded, so it reads healthier than the market. The keys
                      are `ranked_universe_*` and the section carries a `pool`
                      field saying so.
```

### The rule it must not break

The section's own note states it plainly: this is CONTEXT FOR DIAGNOSIS. Market
context may explain a result and must not by itself justify a candidate, and
there is deliberately no `macro` entry in the experiment mechanism vocabulary —
no config-shaped lever for this input to map onto.

The regime-static choice is stated to the model as a FINDING, not doctrine —
"a previous broad regime-weight rotation did not validate out of sample" — which
it may argue to overturn on new cross-regime, held-out evidence. The earlier
wording ("on the evidence that regime timing overfits") asserted a contested
empirical claim as settled, to the one agent in the system whose job is to
question assumptions, in a system whose philosophy is measure-don't-assume.
Note the evidence to overturn it cannot come from live history: ~9 weeks spans
essentially one regime, so regime-conditioned evidence is a wind-tunnel project
(20 years, regime labels per date), not a packet query.

## Design Decision: the packet is an index, not the database — schema discovery (2026-07)

An audit of the packet found seven material evidence gaps. Several turned out
not to be gaps at all: the data was recorded and simply never surfaced. The
builder persists `portfolio_estimated_vol`, `avg_pairwise_correlation` and
`risk_estimate_degraded` on every run and `_current_book` selects three columns
from that row. `alpaca_orders` records the full order lifecycle and the packet
projects six fields of it. This is the same write-only-column pattern as
`bt_runs.live_stats` (persisted, never SELECTed, found the same week).

The reflex fix is to widen the packet. That trades one failure for another: the
last review consumed 572k input tokens, and more context is not monotonically
better — a decisive number diluted among a hundred others is a number the model
does not act on. The same salience argument used to keep a news feed OUT applies
to numbers.

```text
Data needed EVERY review        → packet section.
Data needed when something      → sql_query, with a schema the model can
looks wrong                       DISCOVER rather than guess.
```

The second half was missing. `sql_query`'s description carried a hand-maintained
partial column list — which had already drifted, and whose partiality was
actively misleading: `alpaca_orders (status, notional, filled_at)` reads as the
column list, so the model had no way to know `submitted_at` or `filled_qty`
exist, and would report execution-latency evidence as unavailable.

So the description now carries a TABLE INDEX grouped by the question each table
answers, and an explicit `information_schema.columns` recipe for columns. The
guard already permits it (a plain SELECT; verified against `sql_guard`), so this
is a prompt change, not a capability change. The system prompt states the rule
directly: the packet is not the database, and a structural finding of the form
"we do not measure X" must be preceded by a query that came back empty — naming
the query.

Consequence for the packet-gap audit: items become "must be a section" only if a
review needs them EVERY time (target-vs-live divergence, builder risk state).
Drill-down evidence (execution latency percentiles, per-ticker attribution) is
better reached on demand than paid for weekly.

## Design Decision: a result must carry the provenance of the gates that made it (2026-07)

### The hole

`BT_PARITY_ENFORCE=false` and `BT_COVERAGE_ENFORCE=false` exist so a safety gate
can be flipped without an image rebuild. But a run produced with a gate DISABLED
was byte-indistinguishable from one produced with it enforcing: the summary
recorded returns, not the conditions under which they were computed. So the
promotion gate — deterministic code that rewrites the live strategy — could
accept a candidate scored under no parity check at all, which is precisely the
class of result those gates exist to refuse.

The same hole in the data layer: `bt-data` treated a MISSING `SHARADAR_API_KEY`
as a request for mock mode (`return BT_MOCK_DATA or not SHARADAR_API_KEY`). A
secret failing to load therefore substituted a tiny synthetic corpus, silently,
and every downstream number remained shaped like a real backtest.

Both are the same failure: **the artifact does not record the conditions of its
own production**, so a degraded run and a sound one are indistinguishable
downstream.

### The rule

```text
Every backtest summary carries a `provenance` block stating which gates were
enforcing and which data source produced it. The promotion gate REFUSES any
result whose provenance is missing or shows a gate disabled.
```

Missing provenance is treated as NOT enforced, not as "assume fine" — an older
row without the block is exactly the case that cannot be vouched for. That makes
the pre-existing rows non-promotable rather than silently trusted, which is the
correct direction for a rule that rewrites the live config.

```text
bt-engine   `run_provenance()` stamps parity_enforced / coverage_enforced into
            every summary, on BOTH the single-run and sweep paths.
bt-data     BT_DATA_MODE is explicit ('sharadar' | 'frozen' | 'mock').
            Configured for sharadar with no key is a STARTUP FAILURE, not a
            silent downgrade. The mode is stamped on every data run so a corpus
            built from mock data is identifiable after the fact.
gate        promotion_eligible_2w refuses on missing/false provenance, with the
            reason naming which gate was off — a refusal nobody can read is
            another silent failure.
```

The cost is deliberate: turning a gate off now makes results NON-PROMOTABLE
rather than merely unverified. That is the point. A gate you can disable while
its output still steers the live config is decorative.

### Follow-up: provenance must include WHICH CONFIG, not just which gates

The first cut stamped gate state and stopped. Days later a baseline re-ran and
its period-A excess vs SPY moved from -17.4% to -14.9%. Two things had changed
at once — the active config (drift-rebalance gates) and the window phase (every
rebalance date shifted a day, because windows are derived from `today`) — and
the database could not distinguish them, because the sweep spec recorded
`base_strategy`: the strategy NAME, which is invariant under every config
change. Attribution came down to the `mtime` of the YAML on the NAS, evidence a
`git checkout` or a redeploy would have erased.

```text
config_identity(cfg)   {config_hash, strategy_id}, hashed from CONTENT (sorted
                       JSON of the validated model) with the SAME algorithm the
                       evaluator uses for candidates — so a baseline hash and a
                       candidate hash are directly comparable and "which config
                       was this measured against?" is answered by equality.
run_provenance(cfg)    carries it alongside the gate state into every summary.
bt_sweeps.spec         records the identity, not just the name.
/sweeps/run response   returns it, so bt-scheduler can stamp the lane entry at
                       fire time (only when absent — a candidate keeps the hash
                       it was authored with).
```

Note what remains true even with this fix: a re-baseline changes the config AND
the window phase together, so a yardstick that moves is still not attributable
to one cause. That is inherent — windows are derived from `today` and pinned per
baseline. The practical consequence is that "the baseline improved" is never an
interpretable statement; only candidate-vs-baseline on the SAME pinned windows
is. Worth remembering before reading a re-baselined number as progress.


### The third mode: a cancelled subscription must not brick a paid-for corpus

The first cut of this had two modes and was wrong. "Can FETCH new data" and
"can RUN backtests" are different capabilities, and collapsing them meant that
cancelling the Sharadar subscription — a perfectly reasonable decision once ~20
years of history is downloaded — would stop bt-data from starting at all, and
with it the topup checks and coverage gate the lane polls.

```text
sharadar   fetch from Nasdaq Data Link; requires SHARADAR_API_KEY
frozen     NO fetching; the corpus already in bt-postgres is REAL and
           research-grade. Backtests, sweeps and promotion are unaffected —
           only NEW data stops. Needs no key.
mock       synthetic, explicitly requested, NOT research-grade
```

`corpus_is_real()` is true for BOTH sharadar and frozen, and is the predicate a
research result should carry — a lapsed subscription does not retroactively
make history synthetic. Only `is_mock()` marks data that cannot support a
conclusion.

Two supporting details, each preventing a nuisance that trains an operator to
ignore signals: bt-scheduler SKIPS the daily topup when bt-data reports
`frozen` (rather than POSTing it forever and logging a refusal), and the
sharadar-without-a-key error names `frozen` as the answer — the operator meets
that error exactly when the key stops working, which is precisely when they
need to know the option exists.

---

## Design Decision: trailing-stop exit rule (config-flagged, default OFF)

Today the live book's only discretionary exit is the **orphan timer**. The
portfolio-builder rebuilds a holdings-agnostic target every evening, and a held
name is sold once it has been absent from that target for
`orphan_confirmation_days` consecutive builds. Exit is therefore coupled to the
ranking: a position leaves because the ranker stopped liking it, relative to
whatever else scored well that day.

The trailing stop tests a different split of responsibilities:

```text
the ranker      answers "what should I buy next?"
a trailing stop answers "has this trend objectively ended?"
```

Those are different questions, and for a momentum book (`momentum_rotation_v2`
runs momentum 0.36 / quality 0.20 / low_vol 0.14 / value 0.08) the second one is
arguably the better exit criterion. A winner should not be sold because something
else out-ranked it slightly; it should be sold when its own trend breaks.

Rule: per position, track the highest close since entry. When the close falls
`stop_pct` below that peak, sell the whole position. Re-entry is blocked until the
close exceeds the peak that triggered the stop — a price-based condition, so no
cooldown parameter and no timer.

### It is ADDITIVE in v1, not a replacement

The original intent was for the stop to be the *only* discretionary exit, with the
orphan timer suppressed. That does not work, for a structural reason:
`engine.py` Loop 3 begins `if ticker not in target_portfolio: continue`, so
out-of-target holdings never receive `buy_add`/`sell_trim`, and
`_allocate_capacity` never force-exits. With orphan exits off, the book fills to
`max_positions` with stale out-of-target names, new entries queue as `watch`
indefinitely, and nothing can trim the winners. "The stop is the only exit" and
"drift rebalancing stays" cannot both hold.

So v1 ships both exits. Whether suppression pays is a wind-tunnel A/B — the
harness already exists in `tests/simulation/trailing_stop_ab_sim.py`, which counts
`stop_exits` against `delta_exits`. Note the consequence: with two exit routes,
turnover may go UP before it goes down. The turnover reduction this design is
aiming for only arrives in the suppressed variant.

### The planner sits BESIDE the engine, not inside it

`plan_trailing_stops` is a pure function in `services/pipeline/app/engine.py`;
`evaluate_target_vs_live`'s signature is unchanged. Each caller computes stop
states, calls the planner, then:

```text
strips stopped + re-entry-blocked tickers from BOTH live_positions AND target
  (stripping from live_positions alone makes Loop 1 see an in-target un-held
   ticker and emit an entry — buying back the name it just stopped out of)
passes stopped tickers via the EXISTING inflight_exits parameter
  (frees a capacity slot in _allocate_capacity, but does NOT credit their cash
   in _cap_buys — only action=="exit" does, which is the conservative half)
merges its own exit decisions into the engine's result
```

Four reasons this beats new engine parameters: live is bit-identical when the
feature is off *by construction* rather than by a flag; the caller knows whether
the build was DEGRADED, which the engine cannot distinguish from a genuinely empty
target (`engine.py:549`) — so a bad-data day can hold the book without disarming
the stop; check cadence becomes the caller's choice, which the parity problem
below requires; and the existing A/B sim already has this shape.

### Top-level config block, and why placement is a correctness question

`trailing_stop` is TOP-LEVEL, not nested under `delta_engine`. The parity
manifests' `flatten_config` is two levels deep, so `delta_engine.trailing_stop.*`
would be invisible to the CI classification guard. Worse, config-replay's
`_is_inert` treats every `delta_engine.*` path as provably harmless — nesting
there would let it **silently score a stop-enabled candidate as though the stop
did not exist**, and return a Sharpe for it.

```text
bt-engine    PARTIAL  the stop IS simulated, with two real limits (below)
backtester   IGNORED  holdings-agnostic by construction — cannot model a
                      path-dependent exit at all, so it must 422 and name the
                      wind tunnel instead
```

`tests/parity/` pins both halves of that contract: setting `trailing_stop.*`
leaves config-replay's target bit-identical (the IGNORED claim is true) AND the
gate refuses it (so the evaluator gets a 422, not a number).

### Two parity limits, declared rather than assumed

**Cadence.** `sim.py:616` gates the whole decision block on
`(i % rebalance_every) == 0`. Live evaluates the stop every chain run (daily); a
sweep at `rebalance_every=5` would check it every fifth session, so a swept
`stop_pct` carries that latency baked in and would not transfer. The stop must run
in the sim's daily loop, independent of the rebalance gate. Until it does, the
verdict stays PARTIAL — declaring HONOURED with cadence drift is exactly the class
of claim the manifest exists to prevent, and nothing enforces HONOURED
behaviourally.

**Vintage.** Live peaks come from AV adjusted closes; the tunnel's corpus is
Sharadar SEP, uniformly restated end to end. See the restatement fix below — the
tunnel structurally cannot reproduce a live vintage split.

### Prerequisite: `adjusted_close` was never restated

`adjusted_close` is a VINTAGE, not a fact — AV re-derives a ticker's whole
adjusted series on every split and dividend. The ingestor filtered every fetch to
strictly-newer bars, so the `ON CONFLICT ... adjusted_close=EXCLUDED.adjusted_close`
in `_upsert_prices` never saw an old row and each bar stayed frozen at the vintage
of the day it landed. Any measure spanning a corporate action read a phantom move:
a 2:1 split reads as a ~50% crash to a peak-to-now measure, which for a trailing
stop means **liquidating a position that did not move**.

Nothing could have caught this. The wind tunnel scores a uniformly-restated
corpus, and the simulator's truncation-invariance property removes ROWS, not
VALUES — so a peak over a frozen window is perfectly truncation-invariant while
being wrong in live. Both existing safety nets were structurally blind to it.

`select_rows_to_upsert` now compares the stored adjusted close for our newest bar
against what AV serves for that same date; a mismatch means the series was
restated, so the whole returned window is re-upserted. Detection rather than
blanket re-upsert: the blanket version is ~590k rows a night across the universe
on a fetch that already runs for hours, whereas this is one float comparison per
ticker and a ~100-row write only on a ticker's actual action day. Degraded inputs
fall back to the old newer-only behaviour, never to a spurious full re-upsert.

Side effect, and it is not small: this corrects `momentum`, `low_volatility` and
`near_high` for every ticker that has had an action, so **it changes rankings**.
The first chain run after it deploys is not comparable to the last one before it.

### Stop math is deliberately NOT `recent_drawdown`

`peak_to_now` and `trailing_stop_hit` live beside `recent_drawdown` in
`shared/stock_strategy_shared/drawdown.py` but are not built on it.
`recent_drawdown` applies `baseline_window` give-back suppression, so a name that
ran 100 → 150 and gave it all back nets to ~0. That is correct for the
falling-knife ENTRY veto — a round trip is volatility, not a knife — and exactly
backwards for a trailing stop, whose entire purpose is to act when a run-up is
given back. Routing the stop through it would silently disarm it on the names it
most needs to catch. A test pins the divergence so the two cannot be merged later.

A second, quieter reason: `recent_drawdown` also understates a collapse whose
start falls inside its own 3-close baseline window.

### The LLM-tunable partition

`trailing_stop.enabled` is PROTECTED (human-only). It flips an entire exit regime,
which is the same class of control as the entry-side `vetter.falling_knife`
thresholds — not an alpha knob. `is_protected_path` is subtree-prefix matched, so
`stop_pct`, arming, staleness and the circuit breaker stay tunable; freezing the
whole subtree would also freeze the one number the tunnel is meant to sweep.

The wind tunnel can still turn it on: `bt-engine/app/sweep.py` deliberately does
not enforce `PROTECTED_PATHS` ("human-launched offline research"). So a candidate
gets SCORED with the stop enabled, and a human decides whether it goes live.

### Safety rules, and why each exists

```text
arm_after_sessions  (5)  a 2-day-old position's peak IS its entry price, so any
                         downtick reads as a drawdown from peak
max_stale_sessions  (2)  a halted / vendor-gapped / delisting name whose last
                         print is frozen below its peak would otherwise emit an
                         unfillable exit every single run
max_stops_per_run   (5)  exits are EXEMPT from the risk-service turnover cap
                         (MAX_DAILY_TURNOVER_PCT counts only sell_trims), so
                         nothing downstream throttles a market-wide drawdown
                         liquidating the whole book at one open. There is no
                         "unlimited" setting.
no fresh close ⇒ no stop state ⇒ no stop, preserving the existing data-gap rule
empty or degraded target ⇒ no stop pass, so a builder failure never liquidates
```

Also accepted and documented rather than fixed: a `buy_add` inherits the episode
peak, so shares added after a run can be stopped out on a drawdown they never
participated in; the re-entry block is keyed per ticker, so it leaks across share
classes (blocking GOOG does not block GOOGL); and deriving the peak from
`daily_prices` rather than ratcheting it means the peak sees every session while a
ratchet only sees sessions the chain ran — the derived form is strictly tighter,
and makes stop behaviour mildly dependent on chain uptime in a way the tunnel
(which never skips a session) cannot express.

### Correction: exclusions must reach the BUILDER, not filter a finished target

The first cut of the trailing stop removed re-entry-blocked names from the target
the builder had already composed:

```python
target = {k: v for k, v in target.items() if k not in excluded}   # WRONG
```

That removes names and puts nothing in their place. Two things follow, and the
second is worse than the first: the book shrinks below `max_positions`, AND the
removed name's weight is not reallocated, so it falls to cash. In a drawdown the
effect compounds — more names stop out, most stay blocked (recovery requires
exceeding the pre-stop peak), the target keeps shrinking, and the book drifts to
cash. Observed in the wind tunnel as 35 names → 26.

The consequence is not a sizing detail. It makes the stop an implicit
**market-timing overlay** that nobody configured, and it means the experiment
measuring a 10% stop was actually measuring "10% stop + automatic de-risking".
Those are different strategies, and a win would not have said which one won.

**Only the builder can backfill**, because only the builder knows the next-best
candidate and the caps that govern it. So the block is now an ordinary exclusion,
applied at the builder's existing seam — selection, AFTER clustering — for the same
reason vetter exclusions are: a blocked name must still act as a single-linkage
cluster bridge, or removing it fragments a real correlated theme and lets the
survivors escape `max_cluster_weight` during the very drawdown the cap exists to
contain.

Asymmetry worth stating: the builder's block query is deliberately **fail-open**,
the opposite of the vetter-exclusion load, which is fail-closed. An unreadable
vetter means we do not know a name is dangerous, so we must not buy it. An
unreadable episode table means we do not know a name is blocked, and the cost of
buying it anyway is one premature re-entry that the stop will handle again —
whereas refusing to build a portfolio over a telemetry read is far worse.

Two residual strips remain in the delta step, both correct:

```text
stopped THIS run   the target was composed before the stop was known, so no build
                   could have avoided it. Stripped from target AND live_positions
                   (leaving it in the target with the position gone makes Loop 1
                   read an in-target un-held ticker as an ENTRY and buy back the
                   name the stop just sold). One-cycle gap; the next build fills it.
leaked blocks      defence in depth for the fail-open path. Drops the ENTRY
                   decision, never the target entry — dropping the target entry is
                   the bug this whole change removes.
```

**The generalisable lesson**, and the reason this is recorded rather than quietly
fixed: *post-hoc filtering of a composed portfolio silently changes exposure.* Any
future mechanism that wants to remove a name has to reach the component that can
choose a replacement. The invariant that would have caught it — "the realised book
holds `max_positions` unless the eligible pool is exhausted, and target weights sum
to `1 − cash_reserve` unless a named cap binds" — was true, assumed, and written
down nowhere, so nothing could check it.

### Sweep legs persist their equity curve (bt_sweep_equity)

A sweep used to persist only SUMMARIES. `run_config_both_windows` discarded the
`SimResult` and kept `.summary`, so four numbers per window survived and the SHAPE
of a run did not. The dashboard's `live_stats` is transient — overwritten each poll,
gone at completion.

The cost was concrete. An owner watched several candidates track SPY through most
of period A and then collapse in the final month, ending 15-17pp behind. Two
explanations were available — a shared drawdown across correlated configs (all four
candidates are perturbations of one model, so a common decline is *expected*), or an
end-of-window artifact such as a wave of delist exits at `delist_recovery_pct` —
and **neither could be tested**, because the data no longer existed. `bt_equity`
holds only INTERACTIVE `/jobs/run` results; its `run_id` REFERENCES `bt_runs`, which
sweep legs deliberately never write.

A wind tunnel that decides what goes live should not return an exit code and throw
away the execution.

`bt_sweep_equity` is keyed `(sweep_id, config_idx, window_idx, phase, date)` and
carries `portfolio_value / spy_value / drawdown` — enough to answer the question
that matters: *did the book fall while the market held up, and when?* It is written
per config as each leg completes, best-effort (a failed diagnostic write never fails
a sweep), and popped BEFORE `_json_sanitize` so thousands of rows never land in
`bt_sweep_results`' JSONB where nothing could query them by date.

Added to the evaluator's `bt_sql_query` allowlist, so a review can ask *when* a
candidate diverged rather than only by how much. That is the smallest useful piece
of the trace/forest-map work: the summary says a candidate lost; the curve says
where to look.

`bt_sweep_trades` followed immediately, for the reason the equity table alone was
not enough: a wave of delist exits at `delist_recovery_pct` and an ordinary drawdown
are **indistinguishable in the curve**. The `reason` string is what separates them —
it names the mechanism that produced each fill (orphan exit, trailing stop, delist
sweep, drift trim), which is the attribution no summary can express. Idempotency
there is delete-then-insert scoped to the leg rather than ON CONFLICT, because a
ticker can legitimately trade twice on one date and there is no natural key.

So the shape of the diagnosis is now: `bt_sweep_equity` says WHEN a candidate
diverged, `bt_sweep_trades` says WHY. Both are on the evaluator's SQL allowlist and
both are purged by `purge-void-bt-results.sh` — a readable table that survives a
purge is a permanent island of void evidence, which is the failure the purge
cross-check test exists to prevent.

`bt_sweep_positions` completes the trace: what the book HELD on each date, which is
the only way to see BREADTH (how many names) and DEPLOYMENT (how much capital) over
time. The 35-names-drifting-to-26 defect was invisible in the summary AND in the
trade log, and obvious here.

### The forest map

`services/bt-engine/app/forest.py` turns that trace into a run's SHAPE. It is PURE,
computed where the data is already in memory, and attached to each leg's summary —
so it reaches the evaluator through the existing `result` plumbing with no new
packet section and no extra query. Small by construction: chapters and aggregates,
never rows.

The organising idea is that the strategy is a moving FOOTPRINT over the opportunity
set, with an area (how many names, how much capital each) that changes every
session. Wealth lost then decomposes into separately-fixable reasons the footprint
failed to cover growth:

```text
footprint too SMALL    deployment: mean_fill_ratio, mean_invested_weight,
                       share_of_sessions_below_90pct_of_cap
footprint MOVES a lot  churn: repeat entries per name
footprint LEFT early   by_mechanism: fills grouped by the RULE that caused them
                       (trailing_stop / delist_sweep / orphan_exit / floor_exit /
                       drift_*), so "this class of intervention costs" is
                       computable rather than re-derived from prose
footprint WRONG place  NOT COMPUTED — see below
```

`chapters` splits the run into ~8 slices, each carrying book vs SPY return, worst
drawdown, mean positions and fill count, plus `worst_chapter_idx`. A single average
over three years destroys exactly the signal worth seeing: "breadth collapsed in
chapter 4 and deployment collapsed with it" is a sentence about a mechanism failing
at a moment, which no run-level mean can express.

**What it deliberately does NOT compute**, declared in the returned `missing` field
rather than silently omitted: growth CAPTURE — of the growth available in the
opportunity set, how much fell inside the footprint, and why the rest did not. That
needs the ranked universe per date (what we did *not* hold and how it performed),
which is not derivable from a run's own trace. Omitting it silently would read as
"nothing else was available", which is the more dangerous error.

Two disciplines carry over from the rest of the loop. Everything here is
DESCRIPTIVE — it says where to look, never what is wrong. And a diagnosis drawn from
one run is one sample: a mechanism finding is only evidence once it reproduces
across the rolling windows, exactly as a config edge must.

---

## Design Decision: rank picks entries, price manages exits (2026-08 exit-model batch)

A brief proposed re-splitting the two questions the system currently answers
together. The evidence behind it is weak in a specific, stated way — a 2014-2018
panel of 505 large caps whose only stress was Aug-2015 and Feb-2018 — so
everything below ships as a WIND-TUNNEL CHALLENGER with defaults preserving
today's behaviour exactly. The live book (`momentum_rotation_v2`, 35 names,
target-diff exits) is untouched.

The organising idea:

```text
ranking            -> which names to BUY next
trailing stop      -> has THIS position's trend objectively ended
crash brake        -> is the whole market breaking (book-level, not per-name)
drawdown guard     -> when we are down, down HOW (report only)
```

### `strategies/momentum_stop_v1.yaml`

Raw 6-1 momentum as the sole alpha factor, 25 names, a 30% trailing stop,
stop-only exits, no drift rebalancing. Two consequences that were not in the
brief and matter more than most of what was:

**It clears the wind tunnel's factor-coverage gate, which the champion cannot.**
Auto-promotion is paused today because `earnings_surprise` (weight 0.12) has no
Sharadar equivalent, so `check_config_coverage` refuses the active config. At
weight 0 that gate passes — the challenger is scoreable where the incumbent is
not.

**`universe.require_fundamentals: true` is mandatory here.** With
quality/value/growth at weight 0 the composite is price-and-volume only, which a
leveraged ETF satisfies trivially and then TOPS on momentum. The champion is
shielded because its `required_factors` need fundamentals; this config has no
such shield, and without the flag the top of the book fills with SOXL and TQQQ.

### `delta_engine.exit_policy` — the piece that was said to be impossible

CLAUDE.md recorded that suppressing orphan exits wedges the book: `engine.py`
Loop 3 opens `if ticker not in target_portfolio: continue`, and
`_allocate_capacity` never force-exits, so the book fills to `max_positions` with
stale names while entries queue as `watch` forever.

The missing piece was vacancy refill — and it needed no new code.
`select_entries_within_capacity` already admits best-rank-first up to
`max_positions`, so a stop that frees a slot is filled by the best eligible name
on the next build. §3 is therefore SUPPRESSION plus tests pinning the refill,
which is only true until someone edits the allocator.

The engine gained two primitives (`suppress_target_exits`, `drift_rebalance`).
The stop itself still plans OUTSIDE the engine and arrives via `inflight_exits`,
so no peak, `stop_pct` or episode state crosses that boundary — asserted directly
now, not merely implied by pinning the parameter list.

**The safety exits survive the policy.** Below-floor, delisted and data-gap holds
are untouched. Suppressing those too is how "let winners run" quietly becomes
"never sell anything", stranding a sub-floor holding forever.

A config setting `trailing_stop_only` without `trailing_stop.enabled` is REFUSED:
it would have no ordinary exit at all.

### `trailing_stop.reentry_policy` — reversing a documented decision

The shipped rule blocks re-entry until the close exceeds the peak that triggered
the stop: no timer, self-clearing, strictly stronger than any fixed wait. That
reasoning holds at 15% and does not scale, because the rally needed to clear the
block is `stop_pct / (1 - stop_pct)`:

```text
stop 15%  ->  17.6% rally
stop 30%  ->  42.9% rally
```

At 30% that is not hysteresis, it is near-permanent exclusion of a name the ranker
keeps nominating. Both policies are kept so the tunnel can score them at matched
widths. One asymmetry is deliberate: under `peak` a name with no fresh close is
NOT blocked (nothing can buy it anyway); under `cooldown` it stays blocked while
the timer runs, because that rule needs no price and requiring one would unblock
a halted name early.

### `crash_brake` — book-level, and rare by construction

Two conditions, both required: benchmark window return at or below threshold AND
breadth below threshold. An index drop alone is routinely a few mega-caps; thin
breadth alone is normal in a narrow bull market.

**Fail-safe on missing data**, deliberately the opposite of the falling-knife
veto's fail-closed load: refusing to buy on missing data costs an opportunity,
selling half the book on missing data is an unforced loss.

**Applied after `book_volatility` measures the book.** Not "after vol-targeting" —
two scalars commute, so that framing is empty. Brake first and vol-targeting sees
a halved book, concludes it can lever back up, and partly undoes the brake.

`delta_intents.action` was `VARCHAR(10)`; `risk_reduce` and `risk_restore` are 11
and 12 characters, so both were unstorable and the first INSERT would have raised
at the exact moment the brake engaged. Migration 0049 widens it.

CALIBRATION CAVEAT, recorded in the module and the config: this is the change
with the largest claimed effect resting on a sample containing no crash. Score it
against the named stress regimes (`gfc_2008`, `covid_2020`, `bear_2022`) before
believing it.

### `portfolio_drawdown_guard` — observe-only, and that is a finding

Acting on it HURT in the source evidence: culprit-selling and blanket stop-
tightening cut CAGR badly. It reports, and an AST scan asserts no order/intent
vocabulary reaches the module. `action_mode` is a `Literal` with one member
rather than a bool, so adding an acting mode is a schema change somebody reviews.

### `portfolio_builder.cluster_method`

Single-linkage CHAINS: A~B and B~C fuse A, B, C even when corr(A,C) is near zero.
`complete` requires every pairwise link. Default unchanged — tightening the cap
under single-linkage already measured as costly (~26.1% -> 18.1% CAGR, no
drawdown improvement), and momentum winners are often legitimately clustered.

`cluster_cap_applies_to_new_entries_only` from the brief was NOT built: the cap is
already selection-only (nothing re-trims a held position when its cluster weight
grows), so the flag would be a no-op describing existing behaviour.

### ATR (§8) was declined

Neither compute path loads high/low, and live's are UNADJUSTED while every
peak/stop/drawdown computation runs on `adjusted_close` — so it means two loader
changes, a raw-to-adjusted conversion, and a fresh vintage-consistency problem of
the kind the restatement fix just closed. The reported gain (26.1% -> 26.7%, with
higher turnover) is inside noise, and `atr_multiple: 14.0` clamped to [0.20, 0.30]
barely moves the line anyway.

### Deploy

This batch added two NEW `shared/` modules (`crash_brake.py`, `drawdown_guard.py`)
on top of `calibration.py`. The backtest stack has no bind mount, so bt-engine
imports the copy baked into `stocker-base`: use `scripts/deploy-all.sh`, or force
`docker build --network host -t stocker-base:latest -f Dockerfile.base .` before
rebuilding bt-engine.

### Design Decision: recording what the model SAW, not only what it held (2026-08)

An oracle-forensics study (46 months, 505 survivor-biased large caps) asked how
often the ranking's top 25 contained the next month's actual top 25. Recall was
10.7% against 5.1% random — a real edge, roughly 2x, but three quarters of the
next month's winners sat outside the top 100.

**The findings worth keeping were the NEGATIVE ones.** Every static blend tested
— breakout, trend-quality, acceleration — scored BELOW plain momentum (16.19-
18.16% vs 18.74% CAGR). And a gradient-boosted classifier RAISED recall (9.7% ->
17.3%) while LOWERING realised return (1.82% -> 1.21%): it found more hindsight
winners and worse false positives. That is the argument against optimising recall
at all, and it generalises further than the study applied it — oracle regret is
measured against an unachievable benchmark (the oracle's +14.78%/month is ~430%
annualised), so it is a diagnostic, never an objective.

**What was NOT adopted, and why.** The study's headline recommendation was a
regime-conditioned rebound sleeve (+2pp CAGR). Three reasons to wait: it was
fitted on 2014-2016 and did not activate at all in 2017, so there is no
out-of-sample evidence; it carries ~10 free parameters over ~34 months for a
+2pp effect from 3 of 25 slots; and it is the strategy most flattered by the
panel's survivorship bias — "beaten down, high vol, below its old high" selects
names that came back, in a dataset containing only names that came back.

**What WAS built** is the instrumentation, which has no fitting risk and closes a
gap the system had already declared. See CLAUDE.md "the ranked universe per
rebalance". The point is the selected / cap_blocked / out_ranked split: it is the
difference between a factor-model problem and a construction problem, and
answering one with the other's fix is the failure mode this prevents.

Live changes from the same batch went into `momentum_core_v3` — a RANKING-layer
rebuild only (liquidity to 0, momentum window shortened, composite simplified,
book concentrated 35 -> 25). The exit regime was deliberately untouched.

## Design Decision: the vendor shadow — measure the AV→Sharadar diff, do not argue about it (2026-08)

### The question

An analyst report recommends moving the live quantitative chain from Alpha
Vantage to Sharadar, so live and the wind tunnel share one vendor's fields,
adjustment rules and point-in-time semantics. The argument is sound and the
end state is right. The disagreement is about what to do FIRST.

The report treats corporate-action normalization as one validation bullet among
five. It is the whole risk, and it is the reason a cutover cannot be a data
swap:

```text
live       adjusted_close is AV-VINTAGE. Rows are written once and only
           re-based when AV restates them (the S0 vintage-drift fix).
Sharadar   closeadj is UNIFORMLY restated across the whole history.
```

Replacing one with the other silently re-bases every price in `daily_prices`.
That moves momentum, low_volatility, near_high, every drawdown, and every peak
the trailing stop reads — on a book that is now `exit_policy:
trailing_stop_only`, where the peak IS the exit rule. A vendor migration would
arrive as an unannounced strategy change, and the first evidence of it would be
sales.

The honest response to "how different are these two datasets?" is not an
estimate. It is a measurement.

### What is built: a read-only daily diff, no live writer

The report's Phase 2 is "generalize bt-data into a live writer populating
daily_prices/fundamentals/universe_snapshots". That is a large build whose
output cannot be trusted until the diff it is supposed to justify has been
measured — so it is deliberately SKIPPED for now and Phase 3 (shadow) is done
first, in a form that needs no live writer at all:

```text
POST /jobs/vendor-shadow    on the PIPELINE, read-only on both sides.

  live side      the pipeline's own persisted factor_scores / rankings
  Sharadar side  bt_prices / bt_fundamentals / bt_universe, read over
                 BT_DATABASE_URL (the published host port the evaluator's
                 bt_sql_query already uses), then run through the pipeline's
                 OWN compute_all_factors + rank_universe
```

**Both sides are computed by literally the same code objects in one process.**
That is the property that makes the diff interpretable: whatever it reports is a
DATA difference, because there is no code difference left for it to be. Splitting
the computation across pipeline and bt-engine would have reintroduced exactly the
ambiguity the exercise exists to remove.

It is hosted on the pipeline rather than bt-engine for the same reason
`/preview/factors` is: the loaders, the factor module and the live rankings are
all there.

It takes `_job_lock` with a short timeout and 409s rather than waiting, which is
the same choice `/preview/factors` makes and for the same reason — **memory, not
correctness**. This job holds TWO universe-scale price frames, and the factor
step already sits close to `PIPELINE_MEM_LIMIT`. Running a diagnostic beside it
could OOM the pipeline, and the crash-loop breaker would then read that as a
deterministic failure and SUSPEND the chain. A diagnostic that can halt trading
is a worse bug than the one it measures, so it yields instead.

**Both sides are RECOMPUTED, including live's.** Reading live's persisted
`rankings` for the baseline would mix a vintage difference into what is supposed
to be a pure vendor difference. `baseline_fidelity` reports the recompute against
what the chain actually persisted, so that assumption is visible rather than
assumed — the same treatment `/preview/factors` gives it.

**Both sides are ranked over the SAME ticker set** — the intersection. Factors
are cross-sectional percentiles, so ranking each vendor over its own universe
would contaminate every factor diff with a population diff and make none of it
attributable. The universe difference is a separate, first-class measurement
rather than a confound folded into the others.

### What it measures

Every measurement answers a specific question a cutover would otherwise answer
in production:

```text
universe          membership diff both ways        — would the book see a
                                                     different investable set?
price_adjustment  per-ticker correlation of live
                  vs Sharadar RETURNS over the
                  window, plus the drift of the
                  adjusted_close RATIO             — THE corporate-action probe.
                                                     A split/spinoff handled
                                                     differently shows up here as
                                                     a ratio step, and nowhere
                                                     else until it moves a rank.
factor_*          per-factor Spearman + coverage   — which FACTOR the difference
                                                     lands in
ranking           full-universe Spearman rank IC,
                  top-25 / top-100 overlap         — does any of it reach the
                                                     decision?
target            selected-set diff under the
                  live config's own caps           — does it reach the BOOK?
```

Rank correlation alone is the wrong headline. A vendor diff that leaves the rank
IC at 0.99 but moves three names in and out of the top 25 changes the portfolio;
one that perturbs ranks 400-2000 and nothing else does not. So the overlap and
target-set diffs are reported alongside, and the target diff is the one to read
first.

### Deliberate non-features

* **It never writes to `daily_prices` / `fundamentals`.** No shadow ingestion
  tables either. The Sharadar side is computed from the corpus in place and
  discarded; only the diff SUMMARY is persisted (`vendor_shadow_runs`). Anything
  else would be a live writer built before the evidence justifying one.
* **It does not gate, promote, or veto anything.** No auto-cutover, no
  threshold that flips a source. `universe.source` remains a PROTECTED path.
  The output is evidence for a human decision.
* **It does not compare news or the earnings calendar.** Those are a separate
  migration, and the vetter runs `drawdown_only` — deterministic, no news in the
  daily chain — so that dependency is close to inert already.
* **A missing bt-postgres is not an error.** BT_DATABASE_URL unset or
  unreachable ⇒ the job reports unavailable and returns. The backtest stack is a
  separate compose project that is legitimately down during a live-only deploy,
  and a diagnostic that fails the chain's health when its optional peer is
  absent would be a worse bug than the one it is measuring.

### What would justify a cutover

Stated in advance, so the decision is not made by whoever reads the numbers
last:

```text
enough sessions to include a split, a distribution, a new listing, a delisting
  and a fundamentals refresh — the events the two vendors handle differently
target-set diff small and EXPLAINED, not merely small
every price_adjustment outlier attributed to a named corporate action
gross-profitability parity holding (needs the SF1 re-backfill first)
```

Until then the recommendation stands as: migrate, eventually, on this evidence —
and do not point the live chain at bt-postgres in the meantime.
