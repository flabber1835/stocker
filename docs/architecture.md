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
Phase 3 (planned) — human-approved application of recommendations to the
                    strategy YAML (via strategy-validator, never direct)
```

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

**Boundary unchanged:** tools are read-only over already-ingested point-in-time
data (web search is the one documented exception — external context, logged);
the evaluator still never writes config, never creates trade intents, never
touches the broker path, and reaches the LLM only through the llm-gateway.

**Boundary (per docs/llm-boundaries.md).** The evaluator is advisory-only: it
never writes config, never creates trade intents, never touches the broker path.
It calls the LLM exclusively through the llm-gateway (the system's single LLM
interface), with `EVALUATOR_PROVIDER`/`EVALUATOR_MODEL` (default
anthropic / claude-opus-4-8) — deliberately independent of the vetter's
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
