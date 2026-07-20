# Backtester v2 — Time-Stepping Strategy Simulator

Status: Phases 1 (bt-data), 2 (bt-engine), 5 (walk-forward sweep) BUILT;
Phase 3 (bt-ui) pending. Phase 4 compose wiring done for bt-postgres+bt-data+bt-engine.
Phase 5 implementation decisions: lives INSIDE bt-engine (drives run_simulation
in-process; one shared data load serves both windows — safe because the sim is
truncation-proven to never read past its end); sweep legs write bt_sweep_results
only (bt_runs stays the interactive-run history); grid overflow beyond max_configs
is a SEEDED random sample (reproducible); PROTECTED_PATHS are NOT enforced in the
wind tunnel (human-launched offline research — the plan's own example grids sweep
drawdown thresholds); validate_start >= tune_end is REJECTED otherwise (walk-forward
mandatory). Endpoints: POST /sweeps/run, GET /sweeps/latest,
GET /sweeps/{id}/leaderboard (ranked by OOS Sharpe, overfit_gap = IS−OOS alongside).
Supersedes the existing `backtester` service (which only replays already-built
`portfolio_runs` forward). v2 re-runs the pipeline logic **day by day** from a past
start date, builds portfolios as the live system would have, and compares the
equity curve to SPY.

## Decisions locked (from review)

1. **Vetter** — NO LLM/news. Only the **deterministic falling-knife drawdown
   backstop**, applied at **portfolio-builder selection** (excluded from the target,
   exactly as live). Fully point-in-time: drawdown computed from `daily_prices ≤ D`.
   The exclude/keep DECISION is the shared `stock_strategy_shared.drawdown.
   falling_knife_verdict` — the SAME function the live vetter calls (2026-07
   consolidation, audit-pattern): the two-trigger logic (vol-scaled beta-adjusted
   excess OR absolute floor) used to be duplicated in bt-engine `sim.py` and
   llm-vetter `main.py`; both now call one function, so the wind-tunnel veto is
   provably the live veto. Only the LLM-mode judgment (news/earnings/Tavily) is
   un-modelled — it is run-time, not config-deterministic.
2. **Isolation** — runs on a **SEPARATE MACHINE with its OWN database**. Not a
   docker-compose profile in the live stack. The live trading system is never
   reachable or mutated by the backtester. (See "Deployment" below.)
3. **Data** — backtester has its **own data**, fetched by a dedicated **`bt-data`
   service** from **Sharadar SF1** (Nasdaq Data Link): TRUE point-in-time
   fundamentals + deep daily prices + delisted coverage. This eliminates the
   look-ahead bias that Alpha Vantage's current-only fundamentals would introduce.
4. **Same GitHub repo** — the backtester machine clones the SAME repo and tracks
   `origin/main`. One codebase, two deploy targets; develop/pull/push from either.

## Deployment model: separate machine, own stack, same repo

```
┌─ LIVE MACHINE ─────────────┐     ┌─ BACKTEST MACHINE ──────────────┐
│ docker-compose.yml         │     │ docker-compose.backtest.yml     │
│  postgres (live trading)   │     │  bt-postgres (own DB)           │
│  pipeline, scheduler, …    │     │  bt-data     (Sharadar fetch)   │
│  trade-executor (Alpaca)   │     │  bt-engine   (replay sim)       │
│                            │     │  bt-ui       (own dashboard)    │
└────────────────────────────┘     └─────────────────────────────────┘
        ▲ git pull/push                        ▲ git pull/push
        └──────────── same origin/main ────────┘
```

- The backtest machine runs **only** `docker compose -f docker-compose.backtest.yml up`.
  It never has the live compose file's services running.
- The live machine never runs the backtest compose file.
- **No network path, no shared DB, no shared container** between them. "Absolutely
  no disruption to the running pipeline" is guaranteed by physical separation.
- Both clone the repo; the backtester code lives in the same repo under
  `services/bt-*` + `docker-compose.backtest.yml`. You work on the backtester from
  its own machine (or the live one — code is shared, deploy targets are not).
- **Q: same GitHub repo? → YES.** **Q: docker compose profile? → NO** — it's a
  separate compose FILE on a separate machine, which is stronger than a profile.

## Services (backtest stack)

### bt-data (new) — Sharadar fetcher
- Fetches from Sharadar SF1 (Nasdaq Data Link API) into `bt-postgres`:
  - `SEP`/`SFP` daily prices (deep history, incl. delisted — survivorship-bias-free)
  - `SF1` point-in-time fundamentals (`dimension=ARQ`/`ART`, `datekey` = the date
    the data became known — this is what makes value/quality/growth honest)
  - ticker metadata / actions
- One-time **backfill** + incremental top-up. Stores into bt_* price/fundamental
  tables mirroring the SHAPE the pipeline functions expect (so the reused logic
  needs no changes).
- Needs `SHARADAR_API_KEY` (Nasdaq Data Link). No Alpaca, no AV.

### bt-engine (new) — the replay simulator
Per simulated trading day D (point-in-time, no look-ahead — every query `≤ D`):
```
regime  = detect_regime(spy_prices ≤ D)
factors = compute_all_factors(prices ≤ D, fundamentals known-as-of ≤ D)
ranks   = rank_universe(factors, regime, strategy)
# Falling-knife backstop at selection: drop tickers whose drawdown ≤ -threshold
candidates = ranks minus drawdown_backstop(prices ≤ D)
target = greedy_select + compute_weights(candidates, covariance ≤ D)
intents = evaluate_target_vs_live(target, sim_positions, universe ≤ D, ...)
apply intents to sim_positions at modeled fill price (+ tx cost)
mark-to-market at D close; append portfolio + SPY to equity curve
```
Reuses the SAME functions as live: `compute_all_factors`, `detect_regime`,
`rank_universe`, `greedy_select`/`compute_weights`/`build_covariance`,
`evaluate_target_vs_live`. (Imported from the service paths; a later refactor can
move them to a shared package — decision deferred, low priority given separation.)

### bt-ui (new) — own interface
Separate FastAPI app + static UI (NOT the live dashboard):
- **Configure**: start/end date, strategy YAML, drawdown-backstop threshold,
  tx cost bps, fill timing (close-D vs open-D+1), starting capital.
- **Run**: background job, progress bar as it steps through days.
- **View**: equity curve vs SPY, drawdown chart, summary (total/annualized return,
  Sharpe, max DD, alpha vs SPY, turnover, win rate), day-by-day holdings/trades
  explorer.

## Schema (bt-postgres — entirely separate DB)

```
bt_prices        (ticker, date, open, high, low, close, adj_close, volume)
bt_fundamentals  (ticker, datekey, <P/E, P/B, ROE, D/E, rev_growth, eps_growth, …>)
                 -- datekey = point-in-time "known as of" date (no look-ahead)
bt_universe      (snapshot_date, ticker, …)
bt_runs          (run_id, config JSONB, start_date, end_date, drawdown_threshold,
                  tx_cost_bps, fill_timing, status, total_return, annualized_return,
                  sharpe, max_drawdown, benchmark_return, alpha, turnover, created_at)
bt_equity        (run_id, date, portfolio_value, spy_value, drawdown)
bt_positions     (run_id, date, ticker, qty, weight, market_value)
bt_trades        (run_id, date, ticker, action, qty, price, tx_cost)
```

## Phasing (each independently shippable)

1. **bt-data + Sharadar backfill** — BUILT (services/bt-data; mock mode for tests;
   /jobs/backfill, /jobs/topup, /data/coverage GO/NO-GO report).
2. **bt-engine (headless)** — BUILT (services/bt-engine). Day-stepping replay; the
   LIVE modules (pipeline factors/rank/regime/engine + builder select) are loaded
   via app/live: the Dockerfile COPYs the real source files at build time (zero
   drift, no vendoring); tests fall back to repo paths. Deterministic + truncation
   no-look-ahead + falling-knife + fill-timing + tx-cost + delist tests
   (tests/bt_engine). Fills in ADJUSTED price space: next_open = open(D+1) ×
   adj_close(D+1)/close(D+1); close = adj_close(D). rebalance_every param
   (default 1 = live-faithful) for tractable long runs.
3. **bt-ui** — separate configure/run/view interface; equity-vs-SPY; explorer.
4. **bt-compose** — `docker-compose.backtest.yml` wiring bt-postgres + bt-data +
   bt-engine + bt-ui for the separate machine.
5. **(optional)** parameter sweeps (compare N configs side by side).

## Testing

- Determinism: same config + same bt-data snapshot ⇒ identical equity curve.
- No look-ahead: assert day-D computations never read `date > D` (incl. fundamentals
  `datekey ≤ D`).
- Parity: backtester factors/ranks/target for one rebalance MATCH the live pipeline
  for identical inputs (shared functions guarantee this; a test pins it).
- Survivorship: delisted tickers present in bt-data so the backtest can hold names
  that later disappeared (Sharadar SF1 covers this).
- Isolation: backtest compose file shares NO service/DB/port with the live compose;
  asserted in a compose test.

## Phase 6 — automation + results bridge (BUILT)

bt-scheduler (backtest stack only): daily Sharadar TOPUP on weekdays after
BT_TOPUP_HOUR (23 ET) — POSTs bt-data /jobs/topup, which resumes from
MAX(bt_prices.date) minus a small restatement overlap and 409s while the DB is
empty (topup extends a backfill, never substitutes for one); ONE standing sweep
per ISO week (default Friday 19:00 ET = Saturday 02:00 Helsinki, so the export
lands before the Saturday ~00–01 ET weekend evaluator review) from the VERSIONED
spec sweeps/standing_sweep.json — grid + RELATIVE windows
(tune_years/validate_years anchored to run day, clamped to bt-data's
earliest_viable_start) so the spec never goes stale; gated on /data/coverage go.
A failed weekly sweep is NOT auto-retried (deterministic failures would loop —
human looks).

## Phase 6b — experiment queue + skip-if-unchanged (BUILT)

Design decision (2026-07): the weekly sweep is only re-fired when it can learn
something new, and the evaluator's recommendations feed it AUTOMATICALLY as
extra experiments. Automation boundary: proposals are EXPERIMENTS (backtests),
not config changes — running one is harmless, so the queue needs no human gate.
Human approval remains exactly where it was: deploying a config change to the
live book.

EXPERIMENT QUEUE (live → bt direction of the same one-way-per-file bridge;
still zero network path between the stacks):

```text
1. After every successful review the evaluator DETERMINISTICALLY harvests its
   own recommendations (config_field_valid, != 'none', suggested_value parses,
   and the single-field diff validates through StrategyConfig against the
   active config) into artifacts/bt/proposals.json — status 'pending', deduped
   by (field, value) against every entry still in the file, pending capped.
   Harvesting is pure Python from the already-validated report. A
   recommendation the schema rejects never reaches the file.
1b. queue_experiment TOOL (design revision 2026-07, supersedes "the LLM gets
   no write tool for the queue"): the evaluator may ALSO queue EXPLORATORY
   experiments mid-review — theses it wants tested WITHOUT recommending them
   (refuting its own hunches, knob-sensitivity probes). Previously the only
   way to get a wind-tunnel test was to emit a recommendation, which put every
   half-baked thesis in front of the human. The tool is ENQUEUE-ONLY: same
   single-field diff shape, same shared literal parser, same StrategyConfig
   validation against the active config, same (field,value) dedupe (any
   status — a tested thesis must be argued from its results, not re-queued)
   and the same PENDING_CAP, executed under the same cross-container file
   lock. Entries carry origin='exploratory' + the stated hypothesis (the
   harvest path's entries are recommendation-origin). Per-review budget
   EVALUATOR_MAX_QUEUED_EXPERIMENTS (default 4). The automation boundary is
   unchanged: queueing a BACKTEST is harmless, so no human gate; the tool
   cannot run anything, alter existing entries, or touch config.
2. bt-scheduler includes pending proposals in the next weekly sweep as
   extra_configs — each a SINGLE-FIELD diff appended AFTER grid enumeration
   (never cross-multiplied with the standing grid, so proposals can't explode
   the config count), marks them 'testing' (with sweep_id) at fire time and
   'tested' when that sweep's leaderboard exports.
3. The exported leaderboard tags rows whose diff came from the queue
   ("proposal": true), and the evaluator's backtest_lab packet section carries
   the queue state — so next week's review scores its own past proposals
   against out-of-sample evidence instead of re-arguing them.
```

EXPECTED LATENCY (not a defect): a recommendation harvested at Saturday's
review rides the FOLLOWING Friday's sweep, whose leaderboard reaches the review
after that — hypothesis → deep out-of-sample verdict is ~2 weeks end-to-end.
The mid-review run_backtest tool (short live history) is the fast path when a
thesis can't wait.

SKIP-IF-UNCHANGED: on the weekly due-day the sweep actually fires only if
(a) the spec file hash changed since the last fired sweep, OR (b) pending
proposals exist, OR (c) the last successful sweep is older than
BT_SWEEP_FORCE_REFRESH_DAYS (default 28 — the monthly refresh that keeps the
windows sliding and catches regime drift). Otherwise it skips with a once-a-day
note. Fire-state (spec hash, sweep id) persists in artifacts/bt/sweep_state.json
so a restart doesn't re-fire. Decision logic stays pure in app/logic.py.

RUNTIME CAVEAT (verify on the first real run): the standing grid is ~27 configs
× 8 years × ~1500 names on NAS-class hardware. If a full sweep takes longer than
Friday 19:00 ET → Saturday ~00:00 ET (~5h), the export lands AFTER that week's
review and the evaluator consumes the PREVIOUS week's leaderboard — a one-week
evidence latency (not wrong, just stale; the packet's staleness flag only trips
at >21d). Time the first Sharadar-backed sweep; if it overruns, either move
BT_SWEEP_WEEKDAY earlier (e.g. 3 = Thursday) or trim the spec's universe_limit /
grid.

RESULTS BRIDGE (one-way file, preserving isolation): after a sweep completes,
bt-scheduler exports the leaderboard to artifacts/bt/latest_sweep.json. The LIVE
evaluator's packet reads it as the `backtest_lab` section (top-15 by OOS sharpe,
overfit_gap alongside, >21d staleness flagged) — so every weekly review opens
with decision-grade wind-tunnel evidence and the loop closes with the human
approval as the only manual step. Co-located deploys share ./artifacts; separate
machines copy the single file by any transport (rsync/scp) — still no network
path between the stacks.

## Out of scope (v1)

- Intraday simulation (daily bars only). LLM/news vetting (excluded by decision).
- Tax lots, margin, shorting (long-only, matching live).
- Any modification to live-stack behavior.

## Open items before Phase 1

- Sharadar/Nasdaq Data Link subscription + `SHARADAR_API_KEY` provisioned.
- Confirm the backtest machine spec (Sharadar bulk tables are large; the SF1 +
  SEP backfill is multi-GB — size bt-postgres storage accordingly).
- Map Sharadar field names → the column names the pipeline factor functions expect
  (a thin adapter in bt-data, so the reused logic needs no edits).

## Phase 5 — self-running parameter sweep (NO AI in the loop)  [DECISION LOCKED]

Decision: the optimizer is a DETERMINISTIC parameter sweep, not an LLM-in-the-loop
tuner. Reasons: reproducible (same grid + same data → same leaderboard), no API
cost, and — critically — far less prone to overfitting than "ask a model for the
next config", which curve-fits to the specific history. The LLM's role is reserved
for INTERPRETING a result (optional, manual export), never for picking numbers.

How it works (built on top of bt-engine, after Phases 1-4):
- A sweep spec lists parameters + value grids to vary, e.g.:
    max_positions:        [15, 20, 25, 30, 40, 50]
    factor_weights:       a few named regime-weight presets
    drawdown_backstop_pct:[0.10, 0.15, 0.25]
    entry_rank/exit_rank: [(20,35),(25,40),(30,50)]
- The sweeper enumerates the grid (or random-samples it), runs bt-engine for each
  config, and writes one bt_runs row per config.
- WALK-FORWARD / OUT-OF-SAMPLE is mandatory, not optional: each config is scored on
  a held-out period it was NOT selected on (e.g. tune on 2015-2021, validate on
  2022-2026, and/or rolling windows). The leaderboard ranks by OUT-OF-SAMPLE
  risk-adjusted return (Sharpe / Calmar), with in-sample shown alongside so a large
  in-vs-out gap flags overfitting. A config that only wins in-sample is rejected.
- Output: a ranked leaderboard (bt_sweeps / bt_sweep_results tables) viewable in
  bt-ui — "here are the N best configs by out-of-sample Sharpe, with the in-sample
  gap so you can see which are robust vs fit."
- Determinism + anti-overfit are TESTED: same grid/data → identical leaderboard;
  a synthetic overfit case must show the in/out gap the report relies on.

Optional later: an "analyst export" (JSON/CSV of a run or the leaderboard) that a
human pastes into a Claude session for INTERPRETATION — strictly separate from the
sweep, never driving config selection.

