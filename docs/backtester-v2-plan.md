# Backtester v2 — Time-Stepping Strategy Simulator

Status: APPROVED ARCHITECTURE — Phase 1 (bt-data) BUILT, Phase 2 (bt-engine) BUILT;
Phases 3 (bt-ui) / 5 (sweep) pending. Phase 4 compose wiring done for bt-postgres+bt-data+bt-engine.
Supersedes the existing `backtester` service (which only replays already-built
`portfolio_runs` forward). v2 re-runs the pipeline logic **day by day** from a past
start date, builds portfolios as the live system would have, and compares the
equity curve to SPY.

## Decisions locked (from review)

1. **Vetter** — NO LLM/news. Only the **deterministic falling-knife drawdown
   backstop**, applied at **portfolio-builder selection** (excluded from the target,
   exactly as live). Fully point-in-time: drawdown computed from `daily_prices ≤ D`.
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

