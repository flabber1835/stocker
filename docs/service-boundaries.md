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
- Lifespan calls the shared `mark_orphaned_runs_failed("ingest_runs", ...)` on
  startup so any `running` row left by a crash is marked `failed` with the
  `RESTART_ABORTED:` prefix in `error_message`. The scheduler detects this prefix
  in `_step_state` and treats the run as recoverable (`idle` → re-trigger) rather
  than a real failure (which would suspend the chain until midnight).

### pipeline

Unified factor + rank service (delta removed from this step — see below).
Single `_job_lock` is held end-to-end so concurrent HTTP /jobs/run or Redis
events get `{"status":"already_running"}` for the full run.

Sub-steps in order (for `/jobs/run`):
- factor calculation (factor_scores, regime_snapshots)
- ranking (ranking_runs, rankings)

Delta is intentionally NOT run inside `/jobs/run`. It runs as a dedicated
scheduler step after the vetter and portfolio-builder have completed, so
proposals always reflect today's vetter exclusions and target weights.
Running it early would show stale proposals based on yesterday's vetter data.

**Standalone delta endpoint (`POST /jobs/delta`):**

Called by the scheduler as step 5 of the daily chain, after portfolio-builder.
Runs only the delta evaluation step (no factor recalc or ranking).
Uses `triggered_by='scheduler'` in delta_runs.

Delta mode selection:
- If portfolio_holdings exists (portfolio-builder has run): uses `evaluate_target_vs_live()`,
  which diffs `portfolio_holdings` (target) against `live_positions` (actual broker state).
  Generates immediate entry intents on cold boot — no confirmation_days wait needed.
- If no portfolio run found (true cold start): falls back to `evaluate_all()` with
  `confirmation_days` confirmation requirement.

**`/runs/delta-latest`:** Returns the most recent delta_run with `triggered_by='scheduler'`.
The scheduler polls this endpoint (not `/runs/latest`) to track standalone delta state
independently from the pipeline's delta run.

**Manual vs scheduled delta (`delta_runs.manual`):** `POST /jobs/delta?manual=true`
sets `delta_runs.manual=TRUE` to mark a human-initiated run (scheduler /jobs/run-now)
vs the after-close cron chain. This is a SEPARATE column from `triggered_by`, which
stays `'scheduler'` for both — retagging `triggered_by` would break /runs/delta-latest's
`triggered_by='scheduler'` filter and wedge the supervisor's done-detection. The flag is
surfaced through /runs/delta-latest and api /delta/latest so the dashboard can refuse to
auto-approve a manual run's proposals (a human must click). The scheduler appends
`manual=true` to the delta trigger only when the chain's in-memory `origin` is `'manual'`
(set by /jobs/run-now; reset to `'scheduled'` on date rollover). A manual run also runs a
cancel-all-orders + re-sync pre-step before the chain — see docs/risk-safety-rules.md.

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

Lifespan calls the shared `mark_orphaned_runs_failed()` for `pipeline_runs`,
`factor_runs`, `ranking_runs`, and `delta_runs` so a restart leaves no stale
`running` rows. The helper prefixes `error_message` with `RESTART_ABORTED:`
so the scheduler can distinguish a recoverable restart-orphan from a real
failure (see Restart Recovery below).

**Already-ran-today guard:** When `pipeline /jobs/run` sees an existing
`pipeline_runs` row with `status='success'` and `run_date = MAX(SPY date)`,
it returns `{"status": "already_ran_today"}` without creating a new row. The
scheduler classifies the pipeline step as `done` by comparing `run_date` (the
data session) against the session being processed (SESSION anchor) — a
data-date-vs-data-date check that is correct across midnight and on
weekends/holidays. (`chain_date` is still written for audit but the scheduler no
longer keys the pipeline step on it; the old `chain_date == today` workaround was
needed only while the step was wall-clock-anchored.)

**Redis consumer PEL drain:** On startup `_redis_consumer_loop` first reads
the Pending Entries List with `id="0"` until empty, then switches to `>` reads
for new messages.  Without this, `fetch_data.complete` events claimed by a
prior consumer instance but never xack'd (because the service crashed mid-handle)
would be stuck in the PEL forever — they are NOT redelivered by `>` reads.

### portfolio-builder

Converts ranked stocks into target portfolio weights.

**Triggered by the scheduler daily chain** (after the vetter completes), not manually.
The scheduler chain: fetch-data → pipeline → vet → portfolio-builder → delta.
The vetter runs *before* portfolio-builder so today's exclusions are available.

Steps:
1. Load top N candidates from ranking run
2. Apply LLM vetter exclusions — excluded tickers are removed from the candidate
   pool (binding). When a `vetter_run_id` is supplied, those tickers cannot be
   selected. The chain guarantees a vetter run exists (vet is a mandatory step),
   so in normal operation this step is always applied.
3. Load price history for covariance matrix
4. Apply universe filters (min_price, min_avg_dollar_volume_20d)
5. Build covariance matrix (Ledoit-Wolf shrinkage)
6. Greedy score-per-portfolio-vol selection with sector caps
7. Write holdings to portfolio_holdings

The portfolio is never built without the vetter: the scheduler marks `vet`
`optional=False`, so a vetter failure halts the chain before portfolio-builder
runs. The vetter does not "approve" stocks — it only removes excluded tickers;
the deterministic ranker still owns the final score.

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

**The vetter is a mandatory, binding gate — but it can only exclude.** The
scheduler marks the `vet` step `optional=False`, so the chain halts (and the
portfolio is never built) if the vetter fails. Its exclusions are binding:
excluded tickers are removed from the candidate pool before portfolio
construction. It does NOT apply positive-conviction score boosts — the
deterministic ranker owns the final score. `positive_conviction`/`positive_reason`
are recorded for the dashboard and audit only; they do not change ordering or
weights. Hallucination flags only attenuate the vetter's own decision (auto-override
of unsupported excludes, conviction downgrade), never a score boost.

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
- Calls only read endpoints against Alpaca: `GET /v2/account`, `GET /v2/positions`,
  and `GET /v2/orders` (reconciles fill status of orders trade-executor submitted).
  It never submits or cancels orders — only trade-executor places orders.
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
1. fetch-data        → av-ingestor /jobs/fetch-data
2. pipeline          → pipeline /jobs/run   (factors + rank only; delta is step 5)
3. vet               → llm-vetter /jobs/vet         (mandatory; failure halts the chain)
4. portfolio-builder → portfolio-builder /jobs/build (target portfolio weights;
                       reads vetter_exclusions from step 3)
5. delta             → pipeline /jobs/delta  (standalone delta, triggered_by='scheduler')
                       status polled at /runs/delta-latest (filters triggered_by='scheduler')
```

`vet` runs BEFORE `portfolio-builder` so the same-cycle vetter exclusions can feed
the build. `portfolio-builder` auto-selects the latest successful vetter_run that
matches `source_ranking_run_id` when no `vetter_run_id` is supplied (the scheduler
passes none) — without this the scheduler chain would silently skip exclusions and
risky tickers would surface as BUY+EXCL in the trader UI.

Neither `vet` nor `portfolio-builder` is optional. `vet` is `optional=False`: if
the vetter fails, the chain halts (the portfolio must never be built without
today's binding exclusions). `portfolio-builder` is likewise required — the delta
step after it needs a fresh target portfolio. If either fails, the chain halts.

**Session-keyed chain (supersedes wall-clock `today`).** The supervisor keys a
chain to the trading SESSION it is processing — `latest_closed_session(now_ET)`
in `services/scheduler/app/staleness.py` — NOT wall-clock `today`. The session is
the most recent NYSE session whose 16:00 ET close has passed; crucially it is
**stable across midnight** (it only rolls at the next session's close), so a chain
that starts in the evening and runs past midnight keeps the same key.

This is the fix for the *cross-midnight abandon* bug: previously the supervisor
reset its per-day state whenever wall-clock `today` changed, so a long chain
(e.g. a full fetch started 22:30 ET) was silently abandoned at 00:00 ET — its
`scheduler_runs` row coerced to `failed`, the in-flight fetch orphaned, and the
dashboard reverted to "READY" on the prior session's data. Keying on the session
means midnight is a non-event; the key (and the chain) only roll when the next
session actually closes.

**Data-frontier start gate.** The supervisor STARTS a fresh chain only when the
latest closed session has not yet been processed:

```text
last_processed_session  < latest_closed_session   → run  (incl. weekend catch-up of a missed Friday)
last_processed_session >= latest_closed_session   → skip (weekend/holiday/post-completion no-op)
last_processed_session is None (cold start)        → run
```

`last_processed_session` is the data date of the most recent successful
`delta_runs` row (`_latest_delta_date()`). This subsumes the old
`should_run_chain` trading-calendar gate (on a weekend the session is the prior
Friday, so once Friday is processed there is nothing to do) and additionally
avoids re-opening a redundant chain once a trading-day session is done. The
scheduled-time floor (`_is_after_scheduled_time`, default 22:30 ET) is kept
because AV publishes EOD data ~1–2h after the close and the exact time is
unknown — it ensures a chain only starts once the data has reliably landed. The
gate applies only to STARTING a chain; once one is open (`current_run_id` set) it
advances every tick. Manual `/jobs/run-now` (`_force_pending`) bypasses it.

**Every step is anchored on a DATA-session date (no wall-clock anchors).** The
`DateAnchor` is `SESSION` for fetch-data (`session_date` = MAX SPY date ingested)
and pipeline (`run_date` = MAX SPY date scored), and `UPSTREAM_RANK` for vet
(`source_rank_date`), portfolio-builder (`portfolio_date`) and delta (`run_date`).
No step compares against wall-clock `today`/`started_at` anymore. This is what
lets a step that completed the previous evening still read `done` after midnight
(its session date matches the session, even though its `started_at` date does
not), and it removes the entire "data-date vs calendar-date" re-trigger-loop bug
family — including the weekend wedge and the evening-ET vetter re-billing — at the
source. `ingest_runs.session_date` (migration 0016) and the vetter's JOINed
`source_rank_date` were added to expose these dates to the scheduler.

`status_path` on `_StepDef`: each step defines its own status polling path (default
`/runs/latest`). The standalone delta step uses `/runs/delta-latest` so the scheduler
tracks it independently from the pipeline's embedded delta run.

**FastAPI lifespan must not block on DB.** All persistence-using services schedule
`wait_for_db` as a background task via `warm_up_db_in_background` (in
`shared/stock_strategy_shared/db.py`) so the lifespan can yield immediately and
uvicorn starts accepting `/health` requests right away. If the lifespan blocks
on DB readiness (as it did prior to May 2026), the docker healthcheck
(`start_period=20s` + `5 × 5s` = 45 s) can fail before `wait_for_db`'s 90 s max
on slow NAS hardware, and `restart: unless-stopped` triggers a death loop the
service can never escape. DB-dependent endpoints fail with 503/connection errors
until the warm-up task succeeds; `/health` always responds.

**Stuck-step timeout (`max_running_minutes`):** Each `_StepDef` may declare a maximum
running age. `_step_state` checks this BEFORE its date-match early return so a job
that started yesterday and is still "running" today (cross-midnight hang) is correctly
classified as failed and the chain can advance. Currently set on `vet` (90 min) and
`delta` (30 min). If Ollama crashes mid-run or the LLM provider stalls past the vet
limit, the scheduler converts the hung "running" into "failed" — and because `vet` is
`optional=False`, that **halts the chain** rather than letting the timer block it
forever (no portfolio/proposal is produced that day until the next run).

**Restart Recovery (`RESTART_ABORTED:` marker):**
Every persistence-using service calls the shared
`mark_orphaned_runs_failed()` on startup. The helper marks any
`status='running'` rows from a previous crashed run as `failed` and prefixes
`error_message` with `RESTART_ABORTED:`. In the scheduler, `_step_state`
checks for this prefix on every `failed` row:

```text
data["status"] == "failed":
  RESTART_ABORT_MARKER in error_message → return "idle"   # re-trigger
  no marker                              → return "failed" # suspend chain
```

This distinction matters for **every** step in the chain — fetch-universe,
fetch-data, pipeline (and its inner factor/ranking/delta sub-runs),
llm-vetter, portfolio-builder, and the standalone delta step.  Without it,
a `docker compose down` mid-fetch leaves the chain wedged until midnight.
Coverage:
- `av-ingestor → ingest_runs` (used by both fetch-universe and fetch-data)
- `pipeline   → pipeline_runs / factor_runs / ranking_runs / delta_runs`
- `llm-vetter → vetter_runs`
- `portfolio-builder → portfolio_runs`

The scheduler's cold-start branch (when no universe exists yet) also runs
the marker check on the latest fetch-universe row so a crash during the
very first universe download re-triggers on the next tick instead of
halting with "cannot proceed without universe".

`/runs/delta-latest` includes `error_message` in its SELECT so the
scheduler's delta `_step_state` can detect the marker for that step too.

**Stuck-idle skip for optional steps:** `_startup_catch_up` tracks
consecutive ticks where an optional step (e.g. llm-vetter) returned `idle`.
After 10 consecutive idle ticks (~5 min) it marks the step `failed` and
advances the chain.  Without this, a permanently unreachable optional
service made the catch-up loop spin for its full 6-hour budget.
Optional steps that fail still leave the chain `success` overall.

**Midnight rollover closes open runs:** When `_chain_status["date"]` no
longer matches `date.today()`, the supervisor first calls `_db_close_run`
on `current_run_id` (coercing a non-terminal `running` status to `failed`)
before clearing in-memory state.  Without this, a chain that spans midnight
left orphaned `status='running'` rows in `scheduler_runs` forever.

**Manual force re-run (`POST /jobs/run-now`):** the dashboard "Run" button. Unlike
the cron-driven tick, this always re-executes every step even when today's chain
already shows `success`. Mechanism:
- Resets `_chain_status` for today and populates an in-memory `_force_pending` set
  with every step name.
- Pipeline `/jobs/run?force=true` bypasses the daily idempotency guard. Other
  services have no daily guard and naturally accept a fresh trigger.
- Guarded by `_run_now_lock` (separate from `_chain_lock` — held across the full
  supervised loop including the 3 s sleeps between ticks), so a second click
  returns `already_running` instead of resetting state mid-cycle.
- Persisted to DB inside `scheduler_runs.steps` under a `__meta` sentinel key.
  On container restart the scheduler reads this in `_startup_catch_up` and
  resumes the rerun rather than declaring the chain "already done today".
- If `_trigger_step`'s POST fails, the step stays in `_force_pending` so the next
  tick retries — never advertising a fake "running" state to the dashboard.

### api

Backend API for the dashboard and control layer. Exposes:
`/universe`, `/rankings`, `/rankings/with-overlays`, `/portfolio`, `/regime`,
`/live-portfolio`, `/delta/latest`, `/trade/approve`, `/alpaca/sync`, `/traces`,
`/data-freshness`.

`/rankings/with-overlays` joins rankings with vetter decisions, universe_tickers
(for company name and sector), live_positions, and the latest `fundamentals`
row per ticker (for `market_cap`, surfaced as the screener's SIZE tier:
MEGA/LARGE/MID/SMALL/MICRO). It returns a unified row per ticker for the
dashboard screener (rank) tab. This is the canonical rankings endpoint used by
the dashboard. The screener columns are RANK / TICKER / COMPANY / SIZE; per-factor
z-scores live in the per-ticker detail card, not the table. The `market_cap` join
also covers broker-held tickers that fall outside the ranking window (orphans),
so they still render a SIZE tier instead of a blank cell.

`/rankings/search?q=` searches the **entire ranked universe** for the latest run
(prefix match, no row limit) — not just the loaded top-N — plus any held-but-
unranked broker positions matching the prefix. Its CTEs are scoped to the matched
tickers first so the query stays fast on a Russell-3000-scale table (an unscoped
version timed out behind the dashboard's 10s proxy and silently fell back to
filtering only the loaded top-100).

`/trade/approve` is a thin proxy: it validates the intent_id UUID, runs an
early idempotency check against `alpaca_orders`, then POSTs `{intent_id, mode}`
to `trade-executor /jobs/submit`. All sizing, risk-checking, audit logging, and
Alpaca submission live in `trade-executor`.

### dashboard

Displays strategy, rankings, portfolio, vetter output, live positions, and progress.
Does not directly trade.

**Trade Proposal (trader) tab:** an order blotter — it shows ONLY the four
tradeable actions (`renderTrader` filters delta_intents to
`TRADE_ACTIONS = ['entry', 'buy_add', 'exit', 'sell_trim']`):
- `entry` (green) — buy to open a new position
- `buy_add` (bright green) — held but underweight; add shares to close drift
- `exit` (red) — sell to close
- `sell_trim` (golden yellow) — held but overweight; trim shares to close drift

The non-order actions (`hold`, `at_risk`, `watch`) are no longer listed in the
trader tab — their standing is visible on the rankings/portfolio tabs instead.

Each order shows two approve buttons — "Execute Now" (`mode=immediate`) and
"Schedule for Open" (`mode=scheduled`). Both POST to `/api/trade/approve`, which
proxies to the api service. **Both modes submit `time_in_force="day"`** — the
`mode` field is recorded on `alpaca_orders` for audit (immediate vs scheduled
click) but does not change the Alpaca order type. Day orders are accepted 24/7
and queue for the next session, avoiding the OPG expiry problem (an OPG order
expires if the stock has no opening auction print).

A DRIFT column shows `weight_drift` (actual − target) for held positions that
have live alpaca_sync data available.

**Screener controls:** the `▶ RUN` button lives in the top status bar (right
corner, where the clock used to be). The filter row carries a search box (with
a clear `×`) and a single `Holdings` toggle; the filter row and the column-header
row pin together as one floating block while the body scrolls. Rows are laid out
to fit the viewport width (no horizontal scroll) — COMPANY ellipsizes and the
SIZE cell wraps its badges. Held rows carry a green tint (no separate HOLDINGS
badge).

Cloud-native render architecture: all job state lives on the server. Browsers poll
`GET /api/pipeline-status` every 2 seconds and render identically regardless of
which browser or device started the job. No per-browser state machine.

Server-side rank chain orchestration: `POST /api/jobs/rank-chain` triggers a
background task on the dashboard server that runs fetch-data → calc-factors → rank
sequentially, polling each service until it completes before starting the next.
Handles 409 (step already running) by waiting rather than aborting.
