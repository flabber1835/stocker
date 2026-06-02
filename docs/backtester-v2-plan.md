# Backtester v2 — Time-Stepping Strategy Simulator

Status: PROPOSED (design doc — implementation gated on approval)
Supersedes: the existing `backtester` service replays already-built
`portfolio_runs` forward against prices. v2 instead **re-runs the pipeline logic
day by day from a past start date**, building portfolios as the live system would
have, and compares the resulting equity curve to SPY.

## Goal

Duplicate the live pipeline's stock-selection + portfolio-construction + rebalance
logic, start at a configurable date in the past, advance one trading day at a
time, and observe how the system would have picked and traded stocks through time
— with portfolio performance measured against SPY. Configurable and viewable
through its **own separate UI**.

## Hard constraint: ZERO interference with the live stack

The regular `docker compose up` stack must keep running uninterrupted. The
backtester v2:

- Runs as **its own opt-in compose profile** (`--profile backtest`), NOT in the
  default `docker compose up` set. A plain deploy never starts it.
- **Reads** `daily_prices` / `fundamentals` / `universe_snapshots` from the shared
  Postgres (read-only on those tables), but **writes only to its own
  `bt_*` tables** — never to `rankings`, `portfolio_runs`, `delta_runs`,
  `alpaca_orders`, etc. No shared mutable state.
- Has its **own service container, own port, own UI** — does not touch the live
  `dashboard`, `api`, `scheduler`, `pipeline`, or any trading service.
- Submits **no orders** — simulation only; never imports Alpaca credentials.
- Optionally points at a **separate read-replica / its own DB** via
  `BT_DATABASE_URL` if you want total isolation (default: shared DB, bt_* tables).

## Reuse the real logic (don't re-implement)

The pipeline's core math is already pure, deterministic, frame-in/frame-out —
ideal for replay. The backtester imports and calls the SAME functions the live
system uses, so results reflect real behavior, not a parallel approximation:

| Step | Live function | Module |
|------|--------------|--------|
| Factors | `compute_all_factors(prices_long, fundamentals, cfg)` | pipeline/app/factors.py |
| Regime | `detect_regime(spy_prices, config)` | pipeline/app/regime.py |
| Ranking | `rank_universe(factor_scores, regime, strategy)` | pipeline/app/rank.py |
| Covariance | `build_covariance(...)` | portfolio-builder/app/select.py |
| Selection | `greedy_select(...)` | portfolio-builder/app/select.py |
| Weights | `compute_weights(...)` | portfolio-builder/app/select.py |
| Buffer-zone delta | `evaluate_target_vs_live(target, live, universe, ...)` | pipeline/app/engine.py |

These move to a shared importable location (see "Shared module" below) so both the
live services and the backtester depend on ONE copy — no logic drift.

## The replay loop (per simulated trading day)

```
for D in trading_days(start_date .. end_date):
    # 1. POINT-IN-TIME data: only rows with date <= D (no look-ahead).
    prices   = daily_prices WHERE date <= D            (lookback window)
    funds    = fundamentals WHERE as_of_date <= D      (latest per ticker, ≤ D)
    universe = universe_snapshots active as of D

    # 2. Reuse pipeline logic exactly:
    regime  = detect_regime(spy_prices ≤ D)
    factors = compute_all_factors(prices, funds)
    ranks   = rank_universe(factors, regime, strategy)

    # 3. Vetter — see "Vetter handling" (default: DETERMINISTIC backstop only)
    candidates = ranks minus drawdown-backstop exclusions

    # 4. Portfolio build (same caps/weights as live):
    target = greedy_select + compute_weights(candidates, covariance ≤ D)

    # 5. Buffer-zone delta against the SIMULATED held book:
    intents = evaluate_target_vs_live(target, sim_positions, universe ≤ D, ...)

    # 6. EXECUTE in the simulator at D's (or D+1 open) price:
    apply intents to sim_positions; record fills at modeled price + tx cost

    # 7. Mark-to-market the book at D's close; append to equity curve; same for SPY.
```

Key correctness rules:
- **No look-ahead**: every query is `<= D`. Factor windows, covariance, regime all
  computed only from data available on day D.
- **Fills**: model entries/exits at next-day open (configurable: close-of-D or
  open-of-D+1) with a `tx_cost_bps` slippage/commission assumption.
- **Determinism**: same config + same DB snapshot ⇒ identical equity curve
  (heavily tested, like the rest of the system).

## Vetter handling (the one part that can't be faithfully replayed)

The LLM vetter depends on **live** Tavily/AV news with NO point-in-time history —
we cannot reconstruct "what news existed on 2024-03-15." Options, configurable per
run:

- **`off`** — no vetter (pure deterministic factor/portfolio strategy). Cleanest,
  fully reproducible baseline.
- **`backstop_only`** (DEFAULT) — apply only the DETERMINISTIC falling-knife
  drawdown backstop (price-based, fully reconstructable from `daily_prices ≤ D`).
  This is the part of the vetter that IS point-in-time-safe.
- **`live_llm`** (opt-in, slow/costly, NOT reproducible) — call the real vetter
  with today's news as a rough proxy. Flagged in the UI as non-reproducible.

Default `backstop_only` keeps backtests deterministic and honest about what can
truly be replayed.

## Data sufficiency (verify before building)

The replay needs deep history. Before implementation we confirm:
- `daily_prices` depth ≥ (start_date − max factor lookback, ~400 cal days) for the
  universe — momentum/low-vol/covariance need ~1yr.
- `fundamentals.as_of_date` history exists for value/quality/growth (AV gives
  limited point-in-time; if absent, those factors null out pre-history and the UI
  warns — the strategy still runs on price-based factors).
- This is a GO/NO-GO gate: if history is too shallow, the UI surfaces "insufficient
  data before YYYY-MM-DD" rather than silently producing a misleading curve.

## Schema (new `bt_*` tables — isolated from live)

```
bt_runs        (run_id, config JSONB, start_date, end_date, vetter_mode,
                tx_cost_bps, status, total_return, annualized_return, sharpe,
                max_drawdown, benchmark_return, alpha, created_at, ...)
bt_equity      (run_id, date, portfolio_value, spy_value, drawdown)   -- the curve
bt_positions   (run_id, date, ticker, qty, weight, market_value)      -- daily book
bt_trades      (run_id, date, ticker, action, qty, price, tx_cost)    -- fills log
```
All prefixed `bt_` so they're trivially separable and never collide with live
tables. Delivered via an alembic migration (run by the existing db-migrator) AND
an idempotent `CREATE TABLE IF NOT EXISTS` on backtester startup.

## Service + UI

- New container `backtester-v2` (or extend the existing `backtester`), profile
  `backtest`, own port (e.g. 8020).
- **Own FastAPI app + own static UI** (separate from the live dashboard):
  - **Configure**: start/end date, strategy config (pick a `strategies/*.yaml`),
    vetter mode, tx cost, fill timing, starting capital.
  - **Run**: kick off a backtest; progress bar as it steps through days
    (long runs stream progress like the pipeline does).
  - **View**: equity curve vs SPY, drawdown chart, summary stats (total/annualized
    return, Sharpe, max DD, alpha vs SPY, turnover, win rate), a day-by-day
    holdings/trades explorer, and per-period attribution.
- Runs **in the background** (async job, like pipeline) so a multi-year daily
  step doesn't block the UI; results persist in `bt_*` so you can revisit.

## Shared module (avoid logic drift)

Today `engine.py`, `select.py`, `factors.py`, `rank.py`, `regime.py` live inside
service folders (and were historically copied between them). To guarantee the
backtester runs the SAME logic as production:

- Move these pure modules into `shared/stock_strategy_shared/strategy_core/`
  (or import them via a shared package), and have BOTH the live services AND the
  backtester import from there.
- This is the one nontrivial refactor; it's also a standing risk reducer (the
  "math copied verbatim between services" note in CLAUDE.md). Alternatively, to
  minimize blast radius, the backtester can import directly from the existing
  service paths without moving them — faster, but keeps the drift risk. **Decision
  needed (see Open Questions).**

## Phasing (incremental, each independently shippable)

1. **Phase 0 — data audit**: confirm price/fundamental history depth; build the
   GO/NO-GO date gate. (No service yet; a script + report.)
2. **Phase 1 — replay engine (headless)**: the day-stepping loop calling the real
   pipeline functions, vetter `off`/`backstop_only`, writing `bt_*`. CLI/endpoint,
   deterministic, fully unit + integration tested. No UI yet.
3. **Phase 2 — service + API**: wrap Phase 1 in a FastAPI service under the
   `backtest` profile; background jobs + progress; results endpoints.
4. **Phase 3 — UI**: the separate configure/run/view interface, equity-vs-SPY
   chart, holdings/trades explorer.
5. **Phase 4 (optional)** — `live_llm` vetter mode; parameter sweeps (compare N
   configs); shared-module refactor if not done in Phase 1.

## Testing

- Determinism: same config + DB ⇒ byte-identical equity curve.
- No look-ahead: a unit test asserting day-D computations never read date > D.
- Parity: for a single rebalance, backtester factors/ranks/target MATCH what the
  live pipeline produces for the same inputs (shared-module guarantees this; a
  test pins it).
- Metrics: known synthetic series ⇒ known Sharpe/drawdown/return.
- Isolation: a test (or compose assertion) that the `backtest` profile is not in
  the default service set and the service writes only `bt_*`.

## Explicitly OUT of scope (v1 of this plan)

- Intraday simulation (daily bars only).
- Faithful historical LLM vetting (impossible without point-in-time news).
- Tax-lot accounting, margin, shorting (long-only, matching the live system).
- Modifying ANY live service behavior.
