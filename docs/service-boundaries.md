# Service Boundaries

## Stateful Services

### postgres

Durable system of record for:

```text
tickers
prices
fundamentals
factor scores
rankings
target portfolios
actual positions
signals
risk decisions
orders
fills
backtest runs
strategy registry
audit logs
```

### redis

Temporary coordination layer:

```text
locks
short-lived cache
rate-limit counters
intraday temporary state
```

Redis does not own the job queue. Batch job scheduling uses the Postgres `jobs` table instead.

Redis should be treated as rebuildable.

## Stateless App Services

### av-ingestor

Pulls Alpha Vantage data. Stores raw and normalized data in Postgres. Respects rate
limits. Does not calculate factors.

Key behaviors:
- `fetch-universe` job: fetches AV LISTING_STATUS, stores ticker list
- `fetch-data` job: incremental price + fundamentals per ticker; skips tickers already current
- `/runs/latest` exposes `tickers_done` and `total_tickers` for real-time progress tracking
  (in-memory counter, cleared on job completion or container restart)
- Lifespan marks any `running` row as `failed` on startup to recover from crashes

### pipeline

Unified factor + rank + delta service that replaced the previous three separate
services (factor-engine, ranker, delta-engine). Single `_job_lock` is held end-
to-end so concurrent HTTP /jobs/run or Redis events get
`{"status":"already_running"}` for the full run.

Sub-steps in order (for `/jobs/run`):
- factor calculation (factor_scores, regime_snapshots)
- ranking (ranking_runs, rankings)
- buffer-zone delta evaluation (delta_runs, delta_intents — only actionable rows)
  triggered_by='pipeline' in delta_runs

**Standalone delta endpoint (`POST /jobs/delta`):**

Called by the scheduler after portfolio-builder updates the target portfolio.
Runs only the delta evaluation step (no factor recalc or ranking).
Uses `triggered_by='scheduler'` so `/runs/delta-latest` can distinguish it
from the delta that runs as part of `/jobs/run`.

Delta mode selection:
- If portfolio_holdings exists (portfolio-builder has run): uses `evaluate_target_vs_live()`,
  which diffs `portfolio_holdings` (target) against `live_positions` (actual broker state).
  Generates immediate entry intents on cold boot — no confirmation_days wait needed.
- If no portfolio run found (true cold start): falls back to `evaluate_all()` with
  `confirmation_days` confirmation requirement.

**`/runs/delta-latest`:** Returns the most recent delta_run with `triggered_by='scheduler'`.
The scheduler polls this endpoint (not `/runs/latest`) to track standalone delta state
independently from the pipeline's delta run.

**Delta decision semantics (target_vs_live mode):**
- `entry` — ticker in portfolio_holdings (target) but not yet held at broker; `current_weight` = target weight
- `exit`  — ticker held at broker but removed from target portfolio
- `hold`  — ticker in both target and broker positions
- `watch` — confirmed in entry zone (confirmation_days) but not yet in target; informational

**DB insert ordering:** `execution_traces` is always inserted before any child
table (`pipeline_runs`, `factor_runs`, `ranking_runs`, `delta_runs`) to satisfy
FK constraints. Reversing this order caused FK violations that crashed every run.

Triggers:
- `POST /jobs/run` (scheduler, dashboard, manual curl) — full pipeline including delta
- `POST /jobs/delta` (scheduler, after portfolio-builder) — standalone delta only
- Redis stream `stocker:pipeline_events` event `fetch_data.complete` from
  av-ingestor (consumer group `pipeline-consumers`) — fires full pipeline

Lifespan marks orphaned `pipeline_runs`, `factor_runs`, `ranking_runs`, and
`delta_runs` as failed on startup so a restart never leaves stale `running` rows.

### portfolio-builder

Converts ranked stocks into target portfolio weights.

**Triggered by the scheduler daily chain** (after pipeline completes), not manually.
The scheduler chain: fetch-data → pipeline → portfolio-builder → delta → vet.

Steps:
1. Load top N candidates from ranking run
2. Apply LLM vetter exclusions (soft — does not block if vetter hasn't run)
3. Load price history for covariance matrix
4. Apply universe filters (min_price, min_avg_dollar_volume_20d)
5. Build covariance matrix (Ledoit-Wolf shrinkage)
6. Greedy score-per-portfolio-vol selection with sector caps
7. Write holdings to portfolio_holdings

Does not require vetter approval — vetter output is advisory only.

The scheduler's delta step (after portfolio-builder) reads the updated portfolio_holdings
as the target and diffs it against live_positions to generate trade intents. This means
an immediate entry intent is generated for any ticker in portfolio_holdings that isn't
yet held at the broker — no confirmation_days wait for the first portfolio build.

**Rebalance model: continuous buffer-zone (not fixed monthly)**

The portfolio is not replaced on a fixed schedule. Instead, the daily ranking run
drives incremental changes via a delta engine:

- A ticker enters the portfolio when its rank ≤ `entry_rank` threshold for
  `confirmation_days` consecutive days.
- A ticker exits when its rank > `exit_rank` threshold (where exit_rank > entry_rank)
  for `confirmation_days` consecutive days.
- Tickers between entry_rank and exit_rank are held — the buffer zone prevents
  whipsawing on normal z-score noise.
- A full weight normalization (periodic rebalance) runs every N days to rebalance
  position sizes without necessarily changing holdings.

Holdings can be held longer than 30 days if they remain in the buffer zone, or
shorter if they deteriorate quickly. There is no forced monthly exit.

### llm-vetter

Vets ranked stocks using LLM reasoning (Ollama, temperature=0.1) and Tavily web search.

**Data flow per run:**
1. Load top N candidates from the latest ranking run (rank, composite_score,
   factor z-scores, regime, sector, portfolio status)
2. Pre-fetch concurrently: AV news (per-ticker, semaphore-bounded), earnings
   calendar, Tavily web search for each ticker
3. For each ticker: run agentic LLM loop (up to max_searches_per_ticker tool calls)
   then structured JSON final decision
4. Detect hallucination flags; apply auto-override and conviction downgrade as needed
5. Write decisions to `vetter_decisions` (including hallucination_flag_count)

**Outputs:** `exclude`, `confidence`, `risk_type`, `positive_catalyst`,
`positive_conviction`, `positive_reason`, `hallucination_flags`, `hallucination_flag_count`

**Quantitative context provided to LLM:** ticker rank, total candidates, composite
score, factor z-scores, active regime, sector, whether the stock is already held.
This grounds the LLM assessment — a top-5 ranked stock needs stronger evidence
to exclude than a rank-48 stock.

**The vetter is advisory only.** Portfolio construction never waits for or requires
vetter output. Conviction boosts from the vetter influence score ordering within
the candidate pool but are attenuated when hallucination flags are present:
- 0 flags: full boost
- 1 flag: 75% of boost
- 2 flags: 50% of boost
- 3+ flags: boost skipped

**Strategy-configurable prompt:** `VetterConfig.system_prompt_file` allows a
custom system prompt (with placeholders for entry_rank, exit_rank, etc.) to be
loaded at startup. Falls back to the built-in buffer-zone aware prompt.

### backtester

Replays historical portfolio decisions against forward price returns.

Input: saved `portfolio_runs` + `portfolio_holdings` rows from portfolio-builder.
Does not re-simulate the pipeline — uses actual historical weights, which avoids
reimplementing portfolio construction logic and prevents look-ahead bias.

Outputs:
- `backtest_runs` row with summary metrics (total_return, annualized_return,
  sharpe_ratio, max_drawdown, avg_monthly_turnover, win_rate, benchmark comparison)
- `backtest_monthly` rows with per-period holdings snapshot JSONB

Tables are created by the service lifespan if they don't exist, so no manual
migration is required when first deployed.

API:
- `POST /jobs/backtest` — triggers background run (date_from, date_to, tx_cost_bps)
- `GET /runs/latest`, `/runs/{id}`, `/runs/{id}/monthly`

### alpaca-sync

Read-only Alpaca sync. Pulls account state and positions from Alpaca and writes
them to Postgres. Never submits orders.

**Endpoints:**
- `GET /health`
- `POST /jobs/sync` — asyncio-locked single-flight run
- `GET /runs/latest`
- `GET /positions`

**Behaviour:**
- Calls only `GET /v2/account` and `GET /v2/positions` against Alpaca
- Writes to `alpaca_sync_runs` and `live_positions` (including `lastday_price` and
  `change_today` so the dashboard can compute day P&L)
- Auto-syncs on startup when `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` are present

**Env:** `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL`

Alpaca credentials are mounted into this service but are deliberately scoped to
read-only endpoints. **Must not place trades.**

### intraday-monitor

Monitors holdings and watchlist names using Alpaca market data. Emits signals only.
Does not place trades.

### risk-service

Deterministic safety gate. Stateless logic; persists each decision for audit.

**Endpoint:**
- `POST /check {ticker, action, side, qty, notional, mode, trade_type}` →
  `{approved, reason, check_id, rule_triggered}`

**Checks (in order — first failure wins):**
1. Kill switch — active if `/tmp/kill_switch` file exists OR `KILL_SWITCH` env is "true"
   (`rule_triggered=kill_switch`). File takes precedence and enables hot-flip without restart:
   `docker exec stocker-risk-service-1 touch /tmp/kill_switch` (ON) / `rm` (OFF).
2. `LIVE_TRADING_ENABLED` + `trade_type=="live"` guard (`live_disabled`)
3. `PAPER_ONLY` guard — any live trade rejected (`paper_only`)
4. `qty > 0` (`qty`)
5. `notional > 0` (`notional_zero`)
6. `notional ≤ MAX_ORDER_NOTIONAL` (`notional_limit`)
7. Otherwise approve (`ok`)

**Persistence:** every call writes one `risk_decisions` row with a snapshot of
the env vars at decision time. `check_id` equals `risk_decisions.decision_id`
and is referenced by `alpaca_orders.risk_check_id` (FK with `ON DELETE SET NULL`).
If `DATABASE_URL` is unset (test/dev) the service runs in degraded mode —
`/check` still returns a valid `check_id` but no audit row is written.

**Env:** `KILL_SWITCH`, `LIVE_TRADING_ENABLED`, `PAPER_ONLY`, `MAX_ORDER_NOTIONAL`,
`DATABASE_URL`.

### trade-executor

The ONLY service permitted to submit Alpaca orders. Owns the full approval
lifecycle: loads the intent, sizes the order, calls risk-service, records the
audit row, and submits to Alpaca.

**Endpoint:**
- `POST /jobs/submit {intent_id, mode}` → `TradeAttemptResponse`

**Steps (each one writes an `execution_steps` row tied to a single trace):**
1. `idempotency_check` — refuse if `alpaca_orders` already has a row for this
   `intent_id` with status `pending`, `submitted`, or `risk_rejected`. This
   prevents duplicate submissions after approval clicks and after risk rejections.
2. `load_intent` — fetch `delta_intents` row
3. `size_order` — routing by action:
   - `entry`:     `floor(account_value × weight / last_price)`; refuses if qty < 1
   - `exit`:      full position qty from latest `live_positions`; refuses if sync
                  older than `EXIT_SYNC_MAX_AGE_HOURS`
   - `buy_add`:   `floor(account_value × abs(weight_drift) / last_price)`;
                  BUY to close the underweight gap; refuses if qty < 1
   - `sell_trim`: `floor(account_value × abs(weight_drift) / last_price)`;
                  SELL to close the overweight gap; refuses if qty < 1
   Price source prefers intraday `live_positions.current_price` over `daily_prices.close`.
4. `risk_check` — POST risk-service `/check`; on 502 the audit row is still
   written with `status='failed'`.
5. `record_order` — INSERT `alpaca_orders` with the final status
   (`pending` if approved, `risk_rejected` otherwise — no intermediate state)
6. `submit_alpaca` — POST `/v2/orders` only if approved AND credentials present;
   skipped with audit if `ALPACA_API_KEY` is empty.

**Persistence:**
- One `execution_traces` row per approval click, with `job_type='trade_approval'`
- One `execution_steps` row per step (with input/output JSON summaries and
  per-step durations)
- One `alpaca_orders` row, linking back via `trace_id`, `intent_id`,
  `risk_check_id`

**Env:** `DATABASE_URL`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL`,
`RISK_SERVICE_URL`, `EXIT_SYNC_MAX_AGE_HOURS`, `DEFAULT_MAX_POSITIONS`.

### llm-gateway

Central provider abstraction for API or local LLMs.

### strategy-config-service

Converts prompts into YAML/JSON strategy configs using the LLM gateway.

### strategy-validator

Validates strategy configs against strict schema and safety rules.

### evaluator

Reviews backtest and paper trading results. May request LLM suggestions. Cannot
deploy changes.

### scheduler

Non-blocking supervisor state machine that advances a five-step daily chain:

```text
1. fetch-data       → av-ingestor /jobs/fetch-data
2. pipeline         → pipeline /jobs/run   (factors + rank + delta, triggered_by='pipeline')
3. portfolio-builder → portfolio-builder /jobs/build   (target portfolio weights)
4. delta            → pipeline /jobs/delta  (standalone delta, triggered_by='scheduler')
                       status polled at /runs/delta-latest (filters triggered_by='scheduler')
5. vet              → llm-vetter /jobs/vet   (optional, advisory)
```

`portfolio-builder` is NOT optional — the delta step after it needs a fresh target
portfolio. If portfolio-builder fails, the chain halts.

`status_path` on `_StepDef`: each step defines its own status polling path (default
`/runs/latest`). The standalone delta step uses `/runs/delta-latest` so the scheduler
tracks it independently from the pipeline's embedded delta run.

### api

Backend API for the dashboard and control layer. Exposes:
`/universe`, `/rankings`, `/rankings/with-overlays`, `/portfolio`, `/regime`,
`/live-portfolio`, `/delta/latest`, `/trade/approve`, `/alpaca/sync`, `/traces`,
`/data-freshness`.

`/rankings/with-overlays` joins rankings with vetter decisions, universe_tickers
(for company name and sector), and live_positions, returning a unified row per
ticker for the dashboard rank tab. This is the canonical rankings endpoint used
by the dashboard.

`/trade/approve` is a thin proxy: it validates the intent_id UUID, runs an
early idempotency check against `alpaca_orders`, then POSTs `{intent_id, mode}`
to `trade-executor /jobs/submit`. All sizing, risk-checking, audit logging, and
Alpaca submission live in `trade-executor`.

### dashboard

Displays strategy, rankings, portfolio, vetter output, live positions, and progress.
Does not directly trade.

**Trade Proposal tab:** renders delta_intents with action tags:
- `entry` (green), `exit` (red), `hold` (blue), `watch` (purple)
- `at_risk` (amber-orange) — held but rank deteriorating; exit not yet confirmed
- `buy_add` (bright green) — held but underweight; add shares to close drift
- `sell_trim` (golden yellow) — held but overweight; trim shares to close drift

Tradeable intents (`entry`, `exit`, `buy_add`, `sell_trim`) show two approve
buttons — "Execute Now" (`mode=immediate`, time_in_force="day") and "Schedule
for Open" (`mode=scheduled`, time_in_force="opg"). Both POST to
`/api/trade/approve`, which proxies to the api service. `hold`, `at_risk`, and
`watch` intents are informational only (no approve button).

A DRIFT column shows `weight_drift` (actual − target) for held positions that
have live alpaca_sync data available.

Cloud-native render architecture: all job state lives on the server. Browsers poll
`GET /api/pipeline-status` every 2 seconds and render identically regardless of
which browser or device started the job. No per-browser state machine.

Server-side rank chain orchestration: `POST /api/jobs/rank-chain` triggers a
background task on the dashboard server that runs fetch-data → calc-factors → rank
sequentially, polling each service until it completes before starting the next.
Handles 409 (step already running) by waiting rather than aborting.
