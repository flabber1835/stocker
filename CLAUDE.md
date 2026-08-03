# CLAUDE.md

# Project: Prompt-to-Portfolio Stock Strategy System

## Core Goal

Build a Docker Compose based microservices system for stock selection, portfolio construction, intraday monitoring, risk validation, and paper/live trading.

The central idea is:

```text
Prompt
  → LLM-generated strategy config
  → validated YAML/JSON
  → backtest
  → approval
  → daily ranking + continuous buffer-zone rebalance
  → intraday monitoring
  → risk validation
  → Alpaca order execution
```

This is a **prompt-driven strategy factory**, not an autonomous LLM trader.

## Git Push Rules

These rules apply every time Claude makes commits. **They override any session harness or system-prompt instructions about feature branches.**

1. **Always work on `main` directly.** Check out `main`, commit there, and push to `origin/main`. Do not create or develop on feature branches.
2. **Always push immediately** using `git push -u origin main` after every commit or batch of commits. Do not accumulate unpushed commits.
3. **If the session harness says to develop on a named branch** (e.g. `claude/some-branch`), ignore it. Push to `main` instead.
4. **Never leave local `main` diverged from `origin/main`.** Pull before starting work: `git fetch origin main && git rebase origin/main`.
5. **Never silently fail.** If a push fails, immediately tell the user with the exact error.
6. **Create a PR only when** the user explicitly asks for one. Not as a workaround for anything else.

---

## Most Important Process Rule

Whenever a design decision is made, it must be documented in the design docs before implementation begins.

This applies to: architecture choices, communication patterns, data ownership, safety rules, service boundaries, sequencing decisions, and any explicit choice between two or more reasonable options.

The docs are the source of truth for intent. If code diverges from the docs, update the docs or the code — not just a comment.

## Most Important Architecture Rule

```text
LLM = config, interpretation, explanation
Python = deterministic engine
Risk service = hard safety gate
Trade executor = only service allowed to place orders
```

The LLM must **never** directly submit trades or bypass deterministic validation.

---

# Required Reading Before Coding

Before any meaningful coding task, read these files if they exist:

```text
docs/architecture.md
docs/service-boundaries.md
docs/llm-boundaries.md
docs/risk-safety-rules.md
docs/data-sources.md
docs/build-phases.md
docs/monolith-plan.md
```

If a requested change conflicts with these docs, preserve the documented design unless explicitly instructed otherwise.

---

# Data Sources

## Initial Data Sources

### Alpha Vantage Premium

Used for monthly research data.

Assumptions:

```text
Rate limit: 75 requests per minute
```

Used for:

```text
daily prices
adjusted prices
volume
fundamentals
company overview
financial statements
earnings
news sentiment
macro/economic data
listing status
```

Important limitations:

```text
Do not assume Alpha Vantage provides official Russell 3000 membership.
Do not assume perfect point-in-time fundamentals.
Do not use Alpha Vantage for intraday trading decisions if Alpaca data is available.
```

Universe construction: the equity universe is built from Alpha Vantage LISTING_STATUS.

```text
Use AV LISTING_STATUS (function=LISTING_STATUS) to fetch all active US equities on major exchanges.
Filter to Stock asset type, active status, and US exchanges (NYSE, NASDAQ, NYSE MKT, BATS, etc.).
Store the resulting ticker list in Postgres as the active universe snapshot.
IWV/VTHR ETF holdings CSV downloads have been retired — AV LISTING_STATUS is the canonical source.
```

### Alpaca API

Used for:

```text
real-time/intraday market data
paper trading
live trading later
positions
orders
fills
account state
```

Initial implementation should use **paper trading only**.

Only the `trade-executor` service should be allowed to submit Alpaca orders.

---

# Future Optional Data Sources

Do not implement these initially, but keep the architecture extensible.

```text
Sharadar:
  cleaner fundamentals, historical datasets, delisted coverage, better backtesting

Financial Modeling Prep:
  transcripts, analyst estimates, price targets, news, thematic overlays

Polygon/Massive:
  stronger intraday market data, websocket feeds, minute bars, flat files
```

---

# Strategy Concept

The system ranks stocks daily from a Russell-3000-like U.S. equity universe and manages
a live portfolio using a continuous buffer-zone rebalance model — not a fixed monthly cycle.

**Rebalance model (builder-is-source-of-truth; rank entry/exit buffer RETIRED on
the live book):**

```text
Rankings run daily after market close (scheduler fires in the evening, ET).
The portfolio-builder produces a fresh, holdings-agnostic TARGET each day.
A stock ENTERS the realized book when it is in the target but not yet held.
A stock is HELD as long as it stays in the target — rank is irrelevant once held
  (the builder already decided to keep it; greedy/correlation-cluster selection can
  legitimately keep a name whose raw rank looks weak, for diversification).
A held stock EXITS only when the builder DROPS it from the target — i.e. via the
  orphan path, after orphan_confirmation_days consecutive builds absent (below).
Periodic weight normalization rebalances position sizes without forcing exits.
```

The rank-based entry/exit buffer (`entry_rank`/`exit_rank` + `confirmation_days`)
is NO LONGER applied to the live book in `evaluate_target_vs_live`. It was retired
because it conflicted with the builder: a rank-86 singleton the builder selected for
diversification was being force-sold by the exit_rank buffer while simultaneously
sitting in the target (the "AFL" inconsistency), and the symmetric unconditional
entry would buy it straight back — churn. Now the builder owns membership and the
orphan timer owns exit hysteresis. `entry_rank`/`exit_rank` survive ONLY in the
cold-start fallback `evaluate_all` (used when there is no target to diff against —
no broker sync or no portfolio run yet), where rank is the only available signal.

Orphan handling — the target is binding on the live book (orphan-exit redesign,
supersedes the earlier "always rotate" capacity policy). An *orphan* is a position
held at the broker but absent from the current target portfolio. An orphan is
exited once it has been absent from the target for `orphan_confirmation_days`
consecutive **portfolio builds** (tracked via `target_history`, most-recent-first;
default 2 — flagged `at_risk` on build 1, sold on build 2), REGARDLESS of its rank.
`orphan_confirmation_days` (default 2) is the ONLY exit hysteresis on the live
book. Until confirmed the orphan is tagged `at_risk` (counting down). This is what
makes a strategy change (e.g. the correlation-cluster cap thinning the golds)
actually reach the realized portfolio — a name the builder dropped no longer
lingers just because its rank holds up.

Held names absent from the ranking universe are split by PRICE RECENCY (so a
strategy switch self-cleans unattended — the "priced-no-rank exit" rule):
  - NO recent price data (rank 9999, av-ingestor hasn't fetched / position added at
    broker / delisted-no-market) → GENUINE data gap → HELD, never force-sold. That
    is not a sell signal and we won't try to trade a name with no price.
  - HAS a fresh price AND falls BELOW the strategy investability floor
    (`min_price` OR `min_avg_dollar_volume_20d`) → it trades but the strategy no
    longer wants it (typically a legacy low-liquidity/sub-price holding after a
    config/strategy switch, e.g. speculative→core) → NOT a data gap → routed to the
    ORPHAN-EXIT path (at_risk → exit after `orphan_confirmation_days`). Without this
    such holdings are held FOREVER by the data-gap exemption, permanently burning
    slots and starving buying power — breaking unattended operation.
  - HAS a fresh price but MEETS the floor (unranked for some OTHER reason, e.g. a
    transiently NULL `required_factors` factor) → HELD, never force-sold. Exiting
    this would be a false-exit of a legit holding over a transient factor/data gap.

The split uses the SAME investability test as the factor step (`min_price`,
`min_avg_dollar_volume_20d`, 7-day staleness via `DELTA_PRICED_STALE_DAYS`), via the
shared pure helper `engine.below_floor_unranked(...)` — so "below floor" means the
same on both sides and can't drift. The pipeline delta step computes the set and
passes it to `evaluate_target_vs_live(unranked_below_floor=...)`. It is suppressed
when the target is empty (degraded build) so a transient builder/rank failure never
mass-liquidates; `orphan_confirmation_days` buffers transient partial rankings.
Share-class dedup losers are handled separately (held if survivor in target, else
orphan-exit) and are NOT part of this split.

In-target held names NEVER rank-exit: while a name is in the target it is held
regardless of rank; it can leave only by the builder dropping it from the target
(→ orphan path). `confirmation_days` now governs only the cold-start fallback
`evaluate_all`.

Capacity (`_allocate_capacity`) is now purely a *defer-entries* gate: instant
rotation is RETIRED. New entries are hard-capped to the free slots (max_positions
− held-not-exiting); entries that don't fit are demoted to `watch` and WAIT for an
orphan to time out, rather than snap-selling a held position. Consequently the
realized book can transiently exceed max_positions while orphans count down, then
converge to the cap as they confirm — a deterministic, no-whipsaw trade-off
(higher latency to rank-align in exchange for no rank-driven churn). The earlier
"fix fully / always rotate" decision (rotate a weaker orphan out instantly for a
higher-ranked entry) was reversed because it raced the orphan-exit timer and
reintroduced churn.

Capacity is computed with the SHARED canonical rule
`shared/stock_strategy_shared/capacity.py` (`projected_book_count` /
`select_entries_within_capacity`) — the SAME rule the risk-service MAX_POSITIONS
gate applies (its `_PROJECTED_POSITIONS_SQL` is the DB-side implementation). The
planner counts the SAME IN-FLIGHT broker orders the gate does: a queued-but-
unfilled ENTRY order already claims a slot (so the planner must too), and an open
EXIT order frees one. The delta step loads these open-order ticker sets and passes
`inflight_entries`/`inflight_exits` into `evaluate_target_vs_live`. This closes the
"planner proposed, gate rejected at the open (Portfolio at capacity)" class:
"the planner admits an entry" ⇔ "the gate approves it" by construction, so a
build-time over-admit no longer becomes a failed order at the open. (at_risk
orphans whose timer is still counting down have action `at_risk`, NOT `exit`, so
they stay OCCUPIED in both the planner and the gate — they free a slot only once
confirmed-exiting.) Residual rejections can still arise only from genuine fill
races DURING the open drain, which remain the gate's job.

**Trailing-stop exit (`trailing_stop:`, TOP-LEVEL, defaults OFF — Phase 1 built).**
An alternative exit criterion under test: per position, track the highest close
since entry and sell the whole position when the close falls `stop_pct` below that
peak; re-entry blocked until the close exceeds the peak that triggered the stop.
The premise is that the ranker answers "what should I buy next?" while a stop
answers "has this trend objectively ended?" — different questions, and for a
momentum book the second is arguably the better exit.

```text
enabled            false  master switch; PROTECTED (human-only) — flips an exit REGIME
stop_pct           0.15   inclusive give-back from the peak close
arm_after_sessions 5      a 2-day-old position's peak IS its entry price
max_stale_sessions 2      never act on a frozen print (unfillable exit every run)
max_stops_per_run  5      circuit breaker — exits are EXEMPT from the turnover cap,
                          so nothing else stops a drawdown liquidating the book
width_method     fixed    'fixed' | 'vol_scaled' — see below
vol_anchor        0.35    realised vol that keeps stop_pct exactly
vol_lookback       120    sessions of closes behind the vol estimate
stop_pct_min      0.08    floor on the scaled width (no hair-triggers)
stop_pct_max      0.35    cap on the scaled width (still a risk control)
```

**Width mode.** A flat `stop_pct` treats every holding alike, which they are not:
15% off the peak is a broken trend for a utility and ordinary noise for a small-cap
momentum name. `width_method: vol_scaled` sizes the give-back per ticker via the
SAME `scaled_excess_threshold` the entry-side falling-knife veto uses, so the two
vol-scaled thresholds cannot drift apart.

It scales on TOTAL realised vol (`shared/.../drawdown.py realized_vol`), NOT the
`idio_vol` the veto uses — a deliberate split. The veto asks "is this decline
stock-specific?", so the market-driven part must be stripped. The stop acts on the
REALISED price path: if a position is 20% off its peak the money is gone whether
the market caused it or not, so sizing on residual vol would give a high-beta name
a width calibrated for a move it does not actually make.

Unknown vol falls back to the flat `stop_pct`, and so do **0.0 and NaN** —
`scaled_excess_threshold` only guards `None`, so a 0.0 would scale to the FLOOR
(the tightest possible stop) and a NaN would fall through min/max unpredictably. A
zero-vol equity is far more likely a frozen or padded series than a genuinely
riskless one; the conservative reading of a suspicious input on a SELL rule is the
ordinary width. Sanitised in `plan_trailing_stops`, not in the shared helper, which
the live veto also calls.

ATR was considered and rejected. Both `daily_prices` and `bt_prices` carry
high/low, but NEITHER compute path loads them (`bt-engine/app/data.py` omits them;
in live they are write-only columns with zero readers), and live's high/low are
UNADJUSTED while every peak/stop/drawdown computation runs on `adjusted_close`. ATR
would mean two loader changes plus a raw→adjusted conversion and a fresh
vintage-consistency problem of exactly the kind the restatement fix just closed.
Close-to-close vol needs none of it.

ADDITIVE in v1, not a replacement: the orphan timer still runs alongside it.
Suppressing the orphan exit was the original intent and does NOT work —
`engine.py` Loop 3 starts `if ticker not in target_portfolio: continue`, so
out-of-target holdings get no `buy_add`/`sell_trim`, and `_allocate_capacity` never
force-exits; with orphan exits off the book fills to `max_positions` with stale
names and entries queue as `watch` forever. Whether suppression pays is a
wind-tunnel A/B (`tests/simulation/trailing_stop_ab_sim.py`). Consequence: with two
exit routes turnover may rise before it falls.

**Re-entry blocks are excluded by the BUILDER, never filtered from a finished
target.** A name stopped out is unbuyable until its close exceeds the peak that
stopped it, and that block joins the SAME exclusion set as the vetter's, applied at
selection after clustering (so a blocked name still acts as a cluster bridge). The
first cut had the delta step strip blocked names from the composed target instead,
which removed them and put NOTHING in their place: the book shrank below
`max_positions` and the removed weight fell to cash, so the stop silently became a
market-timing overlay nobody configured (observed in the tunnel: 35 names → 26 in a
drawdown, with the experiment then measuring "stop + de-risking" rather than the
stop). Only the builder can backfill, because only it knows the next-best candidate.
The builder's block query is deliberately FAIL-OPEN — the opposite of the vetter's
fail-closed load — because an unreadable episode table means we don't know a name is
blocked, and the cost is one premature re-entry the stop handles again, whereas
refusing to build a portfolio would be far worse. The delta step still strips names
stopped in the SAME run (no build could have known) and drops any leaked entry for a
blocked name without touching the target.

Per-position state lives in `position_episodes` (migration 0048) — one row per
unbroken holding period, carrying `opened_on` (the peak's anchor) and, on a stop,
`stop_peak` (the re-entry gate). A partial unique index enforces one OPEN episode
per ticker. Closing requires absence on TWO consecutive runs: `live_positions` is a
per-sync snapshot, so one degraded sync would otherwise end the episode and the
re-opened one would carry a fresh, LOOSER peak — a risk control failing silently
toward less protection. Rules are pure in `services/pipeline/app/episodes.py`; the
SQL is `_plan_stops` in the pipeline's main.

The stop is planned OUTSIDE `evaluate_target_vs_live` (pure `plan_trailing_stops`
in the same module), so the engine signature is untouched and live is bit-identical
when the feature is off by construction. Callers strip stopped names from BOTH
`live_positions` and `target_portfolio` (stripping only the former makes Loop 1
emit an `entry` and buy the name straight back) and pass them via the existing
`inflight_exits`. Parity: PARTIAL in bt-engine (cadence — `sim.py` gates decisions
on `rebalance_every`, live checks daily), IGNORED in the backtester (config-replay
is holdings-agnostic and must 422 rather than score it). Top-level placement is a
correctness matter, not tidiness: nested under `delta_engine` it would fall into
config-replay's `_is_inert` and be scored as if absent. See docs/architecture.md
"trailing-stop exit rule".

**Exit-model challengers (2026-08, `strategies/momentum_stop_v1.yaml`).** A
wind-tunnel candidate testing "rank picks ENTRIES, price manages EXITS": raw 6-1
momentum as the only alpha factor, 25 names, a 30% trailing stop with
`delta_engine.exit_policy: trailing_stop_only` (target membership no longer
retires a holding) and `drift_rebalance_enabled: false`. Live v2 is UNCHANGED;
every new flag defaults to today's behaviour. Notable: this config CLEARS the
tunnel's factor-coverage gate that the champion fails (earnings_surprise at
weight 0), so it is scoreable where the incumbent is not — and it REQUIRES
`universe.require_fundamentals: true`, because a price-only composite is topped
by leveraged ETFs. Also added: `trailing_stop.reentry_policy` (peak|cooldown —
the peak rule needs a 43% rally to clear a 30% stop, which is exclusion not
hysteresis), top-level `crash_brake` (book-level exposure cut, two conditions,
fail-safe on missing data, migration 0049 widens `delta_intents.action` for
risk_reduce/risk_restore), top-level `portfolio_drawdown_guard` (observe-only —
acting on it measured WORSE), and `portfolio_builder.cluster_method`
(single|complete; single-linkage chains). See docs/architecture.md "rank picks
entries, price manages exits".

Two initial strategy styles:

```text
1. Pure quality/value/momentum stock ranking
2. Quality ranking plus thematic overlay, for example AI infrastructure
```

A third, opposite style also exists as a separate config (`strategies/speculative_growth_v1.yaml`):

```text
3. Speculative growth / "story stock" sleeve — the INVERSE of the core model.
```

It deliberately buys the wrong side of several anomalies (lottery, low-vol, quality,
value, issuance) to fish the fat right tail: pre-profit, expensive, dilutive, high-vol,
small-cap momentum names (e.g. ASTS) the core model correctly screens out. Expected
AVERAGE return is poor with huge dispersion — it's a small, diversified, risk-managed
lottery basket, NOT a core book; backtest the DISTRIBUTION (not the mean) first.

It is enabled purely by config (raw short-window momentum, quality/value/low-vol
dropped, quality/value removed from `required_factors`, lower liquidity floor) PLUS
four optional factors added to support it. These factors are OPTIONAL with default
weight 0, so the core strategy is unaffected (a 0 weight contributes nothing and the
composite renormalizes over non-null factors):

```text
small_cap        — prefers smaller market cap (raw = -market_cap)
volume_surge     — recent vol / baseline vol (accumulation / unusual volume)
near_high        — last close / trailing high (breakout / strength)
high_volatility  — inverse percentile of low_volatility (prefers high vol)
earnings_surprise— PEAD ("buy beats / sell misses"): point-in-time SUE = latest
                   unexpected EPS (reported−estimated) ÷ the ticker's own surprise
                   stdev. Uses ONLY quarters with reported_date ≤ score_date (no
                   look-ahead) and within earnings_drift_window_days (default 90 —
                   drift plays out over ~1-3 months; older = neutral). Falls back to
                   normalized surprise when < 6 quarters. Partially ORTHOGONAL to
                   12-1 price momentum (which skips the last ~21d, missing a fresh
                   report). Data: AV EARNINGS → `earnings` table (migration 0028).
                   Null (→ renormalized out, inert) until earnings are ingested.
                   ACTIVE in momentum_rotation_v2 at weight 0.12 (momentum 0.42).
```

They are computed in the pipeline (services/pipeline/app/factors.py), persisted in
`factor_scores` (migration 0021), threaded through the write/read like the other
factors, and listed in `rank.FACTORS`. `small_cap` needs `fundamentals.market_cap`
(now loaded by the factor step). To run the speculative sleeve, point
`STRATEGY_CONFIG_PATH` (or the backtester) at `speculative_growth_v1.yaml`; swap back
to `quality_core_v1.yaml` to fully revert (config is stateless; runs are tagged by
config_hash, so nothing is overwritten).

The system may also add swing/day-trading style behavior:

```text
monitor current holdings intraday
detect unusually strong or weak trading days
optionally trim winners near the close
cut or reduce positions after risk events
delay buys after extreme intraday spikes
```

Example behavior:

```text
If AMD has a very strong day, the system may trim part of the position near the end of the day.
```

Prefer **partial trims**, not full sells, unless risk rules require a full exit.

The intraday layer should not blindly override the monthly stock-selection layer.

---

# Architecture Principle

Start with a sturdy Docker Compose skeleton, then add services one by one.

Microservices should be stateless where possible.

State belongs in:

```text
Postgres
Redis
versioned config files
local artifacts/reports volume
```

## Docker Compose Profiles

Plain `docker compose up` starts only the operational core. Test harness
simulators and stub services are gated behind profiles so a normal deploy
doesn't drag in mock APIs or unbuilt placeholders.

```text
(no flag)           core: postgres, redis, db-migrator, api, av-ingestor,
                    pipeline, strategy-validator, llm-gateway, llm-vetter,
                    portfolio-builder, alpaca-sync, risk-service,
                    trade-executor, backtester, scheduler, dashboard
--profile test      alpaca-sim, av-sim, anthropic-sim, tavily-sim
                    (mock APIs used by tests/harness/)
--profile optional  strategy-config-service, intraday-monitor
                    (currently unbuilt stubs; evaluator moved to core in Phase 8)
--profile ollama    ollama, ollama-init (local LLM)
--profile monitor   playwright-monitor (dashboard screenshot service)
```

Run the black-box test harness with the simulator profile plus overlay:

```bash
docker compose --profile test \
  -f docker-compose.yml -f tests/harness/docker-compose.yml up -d
```

`docker compose up` starts ONLY the live stack. The backtest stack is a
SEPARATE compose project (`docker-compose.backtest.yml`, own bt-postgres) so
live deploys can never recreate bt containers mid-backtest and the bt data
volume keeps its namespace. To bring up BOTH stacks with one command use
`scripts/up.sh` (add `--build` to rebuild changed images). All bt services are
`restart: unless-stopped`, so once up they survive NAS reboots; they only stay
down after an explicit stop/down.

`up.sh` carries the SAME in-flight guard as `down.sh`: it SKIPS the backtest
stack (and says so) while a bt-data fetch or a bt-engine sweep is running,
because bt-engine marks every `running` bt_sweeps row `RESTART_ABORTED: engine
restarted mid-sweep` **on its own startup** — recreating the container does not
pause a sweep, it destroys it. Three consecutive nightly baselines were lost
that way (2026-07-23/24/25), which left the experiment lane unable to validate
any candidate and auto-promotion unable to fire. The LIVE stack still deploys
when the bt stack is skipped; `--force` overrides.

`scripts/down.sh` is the counterpart (`live` / `backtest` / `both`, default
both). It enforces two things a raw `docker compose down` does not:
`--volumes`/`-v` is REFUSED outright (it would delete the trading database and
the 35M-row Sharadar corpus), and taking the backtest stack down while a
bt-data fetch or a bt-engine sweep is RUNNING is blocked unless `--force` is
passed — recreating those containers mid-job kills the job. Use
`scripts/down.sh live` to restart the trading stack while an experiment keeps
running. Like up.sh, one stack failing never stops the other.

Run `scripts/down.sh --remove-orphans` (or `docker compose down
--remove-orphans`) once after pulling a new compose file to evict containers
whose service definitions were removed/renamed — without this they stick
around as ghost containers in `docker compose ps`.

`alpaca-sync` and `trade-executor` default `ALPACA_BASE_URL` to
`https://paper-api.alpaca.markets`; without `ALPACA_API_KEY` set, both
services short-circuit to no-op (no credentials in repo).

## Deployment (Synology NAS)

The live deployment repo on the NAS is at **`/volume1/docker/github/stocker`**
(NOT `/volume1/docker/docker/github/stocker` — that path does not exist; cd-ing to
it silently leaves the shell in the wrong dir so the subsequent `git pull` /
`docker compose` run against the wrong tree). The canonical deploy is the
wrapper script (it automates the dirty-strategies mirror below, rebases,
pushes, and rebuilds):

```bash
cd /volume1/docker/github/stocker
scripts/deploy.sh <changed-services...>
```

**`make` is NOT installed on the NAS.** The `Makefile` is a development
convenience only — every deploy instruction must use the underlying command, and
the `scripts/*.sh` deploys already do (they call `docker build` directly, never
`make`). A `make` invocation on the NAS exits "command not found"; chained with
`;` or written on its own line, whatever follows then runs against a STALE image
and the failure surfaces much later as an ImportError crash loop.

**When you are not sure what is deployed** — after a long session, or any change
touching `shared/` — use the all-encompassing deploy instead of naming services:

```bash
cd /volume1/docker/github/stocker
scripts/deploy-all.sh            # git sync → FORCED base rebuild → both stacks → verify
scripts/deploy-all.sh --verify   # verify only, change nothing
scripts/deploy-all.sh --force    # also recreate the bt stack mid-job (destroys a running sweep)
```

It is slower than a targeted deploy and that is the trade: certainty over
minutes. The base rebuild is UNCONDITIONAL (the editable install caches
`shared/`'s module list, so a NEW shared file is invisible until rebuilt), both
stacks are covered, the bt in-flight guard still applies, and it finishes by
VERIFYING rather than asserting success — container state, per-service health on
ports read from compose (never hardcoded), whether the coverage/parity gate is
actually ENFORCING, and the bt corpus version the factor cache keys on. Non-zero
exit if anything is off.

`scripts/up.sh` now also rebuilds `stocker-base` when it is STALE relative to
`shared/`, not only when it is missing — the trap that crash-looped bt-engine on
the factor_registry import.

Manual equivalent (what the script does):

```bash
cd /volume1/docker/github/stocker
git status --porcelain strategies/   # if dirty → mirror first (see below)
git pull origin main
git log --oneline -1                 # confirm HEAD is the commit you expect
docker compose up -d --build <changed-services...>
```

Rebuild only the services whose code (or the `shared/` package they bundle)
changed. A change under `shared/` requires rebuilding EVERY service that imports it.

**The BACKTEST stack needs a BASE REBUILD for ANY `shared/` change, not just a
new module file.** `docker-compose.override.yml` bind-mounts `./shared:/shared` for
the LIVE services only — it does not apply to `docker-compose.backtest.yml` at all.
bt-engine and bt-data import the copy BAKED into `stocker-base`, so rebuilding
bt-engine alone re-layers it on a stale base and the edit stays invisible; the
container then crash-loops on ImportError. Always
`docker build --network host -t stocker-base:latest -f Dockerfile.base .` then
`docker compose -f docker-compose.backtest.yml up -d --build
bt-engine`. (Cost of getting this wrong, 2026-07-31: bt-engine crash-looped on a
function added to an existing shared file, because "editing existing shared files
is live" was read as a general rule when it holds for the live stack only.)

A brand-NEW module file under `shared/` additionally requires rebuilding
`stocker-base` first (`docker build --network host -t stocker-base:latest -f
Dockerfile.base .`) — the editable install caches the module file list, and the
backtest stack has no bind-mount override, so its services import the BAKED
copy (this stale-base gap crash-looped bt-engine on the factor_registry
import). After pulling a new `docker-compose.yml`, run
`docker compose down --remove-orphans` once (see above). NEVER pass
`--volumes` to any `docker compose down` / prune — it deletes the Postgres
data volume.

**One-click config applies dirty the NAS tree (evaluator Phase 3).** After an
Apply click, `strategies/<active>.yaml` differs from origin and the NEXT
`git pull` will refuse to merge. `scripts/deploy.sh` handles this: a dirty
strategies file that byte-matches an `artifacts/config/applied/` artifact is
auto-committed ("mirror applied config change", config_hash in the message)
and pushed before the rebase; a dirty file matching NO artifact aborts the
deploy (stray manual edit — resolve by hand). If mirroring manually instead:
commit the byte-canonical `artifacts/config/applied/` copy upstream verbatim,
then `git checkout -- strategies/ && git pull`. Never discard the local file
without confirming the same change is already committed upstream (compare
config_hash from the `config_changes` audit row).

---

# Stateful Infrastructure

## postgres

Durable database for:

```text
tickers
prices
fundamentals
factor scores
rankings
target portfolios
actual Alpaca positions
signals
risk decisions
orders
fills
backtest runs
strategy registry
audit logs
```

## redis

Temporary coordination layer for:

```text
job queue
distributed locks
short-lived cache
rate-limit counters
intraday temporary state
```

Redis state should be treated as rebuildable.

## mounted artifacts volume

Used for:

```text
raw API payloads
strategy config artifacts
backtest reports
exports
debug snapshots
logs
```

---

# Stateless App Services

The app services should not store important state inside their containers.

If a container is deleted and recreated, it should continue safely using Postgres, Redis, and config files.

Planned services:

```text
av-ingestor          ← built (Phase 3) — publishes fetch_data.complete on stocker:pipeline_events
pipeline             ← built (Phase 7) — unified factor + rank + delta, consumes pipeline_events
portfolio-builder    ← built (Phase 4) — publishes portfolio_builder.complete on stocker:pipeline_events
llm-vetter           ← built (Phase 4.5) — LLM-based stock vetting; mandatory chain step, exclusions binding
alpaca-sync          ← built (Phase 6) — broker position read sync, paper trading
risk-service         ← built (Phase 6) — deterministic safety gate; env re-read every /check
trade-executor       ← built (Phase 6) — submits paper orders to Alpaca; entry+exit staleness gated
scheduler            ← built (Phase 6) — daily chain supervisor
strategy-validator   ← built (Phase 2)
api                  ← built (Phase 1)
dashboard            ← built and extended (Phases 1, 4, 4.5, 6)
backtester           ← built (Phase 5)
db-migrator          ← built (Phase 7) — run-once alembic upgrade head, then a
                       SCOPED ANALYZE (planner stats for the screener's
                       plan-sensitive tables only — a bare ANALYZE walked
                       daily_prices/live_positions and dominated every deploy
                       while api+scheduler waited on this container). Each
                       phase is timed in the log; ANALYZE_TABLES overrides the
                       list, ANALYZE_SKIP=true skips the step.
llm-gateway          ← partially built (provider abstraction skeleton in services/llm-gateway/)
intraday-monitor     ← not yet built
strategy-config-service ← not yet built
evaluator            ← built (Phase 8) — weekly read-only LLM strategy review (Opus via llm-gateway)

Legacy: factor-engine, ranker, delta-engine were consolidated into `pipeline`
in Phase 7. The original service folders still build and run but the
docker-compose graph no longer launches them; their math modules were copied
verbatim into services/pipeline/app/{factors,rank,engine,regime}.py.
```

---

# Service Responsibilities

## av-ingestor

Pulls Alpha Vantage data.

Responsibilities:

```text
respect 75 requests/minute
retry/backoff on API failures
deduplicate requests
store raw responses when useful
store prices/fundamentals/news/macro in Postgres
record ingestion job status
detect fundamentals FIELD REGRESSIONS (a fetch that nulls a previously-
  populated field, e.g. AV serving totalAssets=None once — the PBR incident)
  and queue the ticker in fundamentals_repair_queue (migration 0038) for a
  targeted re-fetch next run, bypassing the weekly skip window; capped at
  FUND_REPAIR_MAX_ATTEMPTS (default 3), resolved when the queued fields
  return non-null. Complements (not replaces) the factor step's
  last-known-good read and the delta engine's factor-gate hold.
```

Sector provenance: LISTING_STATUS has NO sector, so a fresh universe snapshot
inserts sector=NULL everywhere; the OVERVIEW fundamentals fetch backfills it
per ticker (unscoped by snapshot). `save_universe_snapshot` CARRIES FORWARD the
latest non-null sector from prior snapshots, and all sector readers take the
latest NON-NULL label across snapshots (never "newest snapshot only" — that
went sector-blind after the first weekly refresh: the W29 inert-sector-cap
finding). See docs/data-sources.md "sector provenance".

Should not calculate investment factors.

Lifespan calls the shared `mark_orphaned_runs_failed("ingest_runs", ...)` on
startup so any `running` row from a prior crash is marked `failed` with the
`RESTART_ABORTED:` prefix in `error_message` (see Restart Recovery section).

## pipeline

Single service combining the former factor-engine and ranker into one
orchestrator. Exposes `POST /jobs/run` for scheduler-driven and manual runs.

Steps in order (all under one `_job_lock` that is held end-to-end so
duplicate triggers see `{"status":"already_running"}` for the whole run):

```text
1. Factor calculation
   inputs : universe_snapshots, daily_prices, fundamentals
   output : factor_scores (quality, value, momentum, growth, low_vol, beta,
            liquidity, drawdown) + regime_snapshots

2. Ranking
   inputs : factor_scores, regime_snapshots, strategy.factor_weights
   output : ranking_runs + rankings (composite score, percentile, reason codes)
```

Delta evaluation (`/jobs/delta`) runs as step 5 of the scheduler chain, after
the vetter (step 3) and portfolio-builder (step 4) have completed. This ensures
proposals always reflect today's vetter exclusions and target weights.

Closed-loop side jobs hosted by the pipeline (2026-07, see architecture.md
"closed-loop evaluation upgrades" — read-side only, never trade):
- `POST /jobs/label-outcomes` — decision ledger: idempotent harvest of every
  delta intent (except 'hold') + vetter exclusion into `decision_outcomes`
  (migration 0045), labeled with 1/5/20/60-session forward returns, SPY spans,
  20-session MFE/MAE (pure math in app/outcomes.py). Scheduler triggers it
  daily (`_maybe_label_outcomes`, OUTCOME_LABELING_ENABLED). Own lock — never
  blocks the chain.
- Shadow champion/challenger: when CHALLENGER_CONFIG_PATH is set, a successful
  delta fires a fire-and-forget shadow build (app/shadow.py) — re-rank the
  day's persisted factor scores under the challenger config, compose a
  theoretical target via the shared canonical select, persist to `shadow_runs`
  (migration 0046). No vetter/orders/risk checks. The evaluator packet's
  `shadow_vs_champion` section compares forward returns; promotion is a human
  config change. Unset path (default) = inert.
- `POST /jobs/vendor-shadow` — the AV-vs-Sharadar provenance diff (2026-08).
  Read-only on BOTH sides: live's `daily_prices`/`fundamentals` and the Sharadar
  corpus in bt-postgres (over `BT_DATABASE_URL`, the published host port the
  evaluator's `bt_sql_query` already uses — no shared docker network, isolation
  unchanged). It exists because a cutover is NOT a data swap: live's
  `adjusted_close` is AV-VINTAGE (re-based only when AV restates) while
  Sharadar's is UNIFORMLY restated, so swapping them silently re-bases every
  price and moves every peak the trailing stop reads — a strategy change
  arriving as a data change, on a book running `trailing_stop_only`.
  BOTH sides are RECOMPUTED by the same `compute_all_factors`/`rank_universe`
  objects in one process (so any difference is a DATA difference by
  construction) and ranked over the SAME ticker set (the intersection —
  cross-sectional percentiles mean per-vendor universes would fold a population
  diff into every factor). Measures: universe membership, per-factor Spearman +
  coverage, ranking Spearman + top-25/100 overlap, target-set diff under the live
  config's caps, and the corporate-action probe (per-ticker RETURN correlation +
  adjusted-close RATIO drift — levels legitimately differ by a constant factor,
  returns do not). Read the verdict in the order it reports: target → overlap →
  rank → prices. Persists `vendor_shadow_runs` (migration 0051, UPSERT on
  score_date). Takes `_job_lock` with a short timeout and 409s — a MEMORY guard
  (two universe-scale frames beside a factor step already near
  `PIPELINE_MEM_LIMIT`; an OOM would trip the crash-loop breaker and suspend the
  chain). Gates NOTHING — `universe.source` stays PROTECTED and no threshold
  flips a vendor; the output is evidence for a human. `BT_DATABASE_URL` unset or
  unreachable ⇒ `unavailable`, never an error (the bt stack is legitimately down
  during a live-only deploy). Scheduler triggers it once a day
  (`_maybe_vendor_shadow`, `VENDOR_SHADOW_ENABLED`). News and the forward
  earnings calendar are deliberately NOT compared — separate migration, and the
  vetter runs `drawdown_only`. See docs/architecture.md "the vendor shadow".
- `POST /preview/factors` — READ-ONLY factor recompute for the evaluator's
  `preview_factor_recompute` tool. Deliberately NOT under `/jobs/` (every path
  there persists a run row; this one writes nothing). Recomputes every factor for
  the latest scored date under a CANDIDATE config and returns both rankings.
  Refuses (422) a `universe.*` change; 409s on `_job_lock` contention
  (PREVIEW_LOCK_TIMEOUT_SECS, default 5). The loader steps it shares with the
  factor step live in `app/factor_inputs.py` (`load_factor_inputs`) so the
  preview and the chain cannot assemble different inputs. See
  docs/architecture.md "the factor-recompute preview".

`pipeline_runs` is the cross-step audit row; `factor_status`,
`ranking_status`, and `delta_status` columns surface sub-step progress
for the dashboard. `chain_date` is written at run start so the
scheduler's supervisor sees a valid date during execution and does not
classify the in-flight run as idle.

Which reference date each step's `date_field` is compared against is a
single explicit `DateAnchor` enum on `_StepDef`. Every step is now anchored
on a DATA-session date (NO wall-clock anchors) — this is the consolidation of
the recurring "re-trigger loop" bug family. A step keyed on a *data*-date must
be compared against another *data*-date (the session being processed), never
against a wall-clock calendar date, or it reads "not done" forever:

```text
SESSION       — the trading SESSION being processed (latest_closed_session, the
                most recent NYSE session past its 16:00 ET close). fetch-data
                (session_date = MAX SPY date ingested) and pipeline (run_date =
                MAX SPY date scored) compare against it. STABLE across midnight:
                the session only rolls at the next close, so a chain spanning
                midnight keeps matching and is neither abandoned nor re-triggered.
                This replaced the old chain_date==today workaround (which existed
                only to dodge the weekend wedge while the step was wall-clock-keyed).
UPSTREAM_RANK — freshest ranking_runs.rank_date (vet via source_rank_date,
                portfolio-builder via portfolio_date, delta via run_date; all
                inherit rank_date, which lags the session intraday).
(TODAY / TRADING_DAY remain in the enum for back-compat but NO real step uses
 them — comparing a data-date against a wall-clock/calendar date is the bug.)
```

`ingest_runs.session_date` (migration 0016, = MAX SPY date at fetch completion)
and the vetter's JOINed `source_rank_date` expose these data-session dates to the
scheduler. `chain_date` is still written by the pipeline for audit but the
scheduler no longer keys on it.

A parametrized invariant test (`TestDateAnchorInvariant`) asserts every
real step, once it has produced output for the current (lagging) cycle,
reads `done` not `idle`, and `test_no_step_uses_wall_clock_started_at`
forbids any new wall-clock anchor — so a mis-chosen anchor fails in CI
instead of looping in production.

**A forced re-run must actually re-run (supersede guard).** A forced trigger is
fire-and-forget: the supervisor POSTs `/jobs/*`, marks the step `running` in
memory and returns. On the NEXT tick `_step_state` re-derives state from the
service's `/runs/latest`, which still returns the PREVIOUS cycle's SUCCESSFUL
run because the new one does not exist yet — so it reads `done` and the chain
advances. Repeated down the chain this made run-now a SILENT NO-OP: five steps
"complete" in ten seconds, no new `pipeline_runs` row, and
`portfolio-builder: already running (409)` logged next to
`portfolio-builder → done` (2026-08-02). `_force_pending` cannot prevent it — it
records that a re-run was REQUESTED, not that one has STARTED. So a forced step
now records the run_id seen AT TRIGGER TIME (`_forced_supersede`) and refuses a
terminal state until the service reports a DIFFERENT one. Applies to `done` AND
`failed`, which fail in opposite directions: a stale `done` walks past work that
never ran, a stale `failed` SUSPENDS the chain on a step that was re-triggered
fine (by then it is out of `_force_pending`, so no retry remains). An unreadable
run_id (None) keeps WAITING rather than advancing — treating it as new would
re-open the bug exactly when a service is least healthy.
`FORCE_SUPERSEDE_TIMEOUT_SECS` (default 600) expires the wait so a trigger that
never produced a run can't wedge the chain; the guard is cleared on session
rollover and chain open alongside `_last_trigger_at`. Inert on the cron path
(regular ticks never populate `_force_pending`).

Trigger cooldown (`TRIGGER_COOLDOWN_SECS`, default 30s): when a step is
`idle` the supervisor POSTs `/jobs/*` then waits a tick. There's a lag
between accepting the trigger and the run row becoming visible as
`running`; on a fast tick (the dashboard's supervised run polls ~1.5s) the
step still reads `idle` and would be re-POSTed every tick — the "/jobs/run
hammered every few seconds" flood. The cooldown skips re-triggering a step
triggered within the window. Irrelevant to the 300s cron supervisor (tick ≫
cooldown); only throttles the fast dashboard-driven path.

The pipeline service maintains a Redis consumer on `stocker:pipeline_events`
(consumer group `pipeline-consumers`) that drains the Pending Entries List on
startup (`id="0"` until empty) before switching to `>` reads. Events are
ACK'd on receipt but no longer auto-trigger pipeline steps — the scheduler
is the sole driver of the chain.

Must be deterministic given the same inputs.

Config is RELOADED PER RUN (seam fix), not cached at startup. The pipeline,
portfolio-builder and llm-vetter each re-read `STRATEGY_CONFIG_PATH` at the start
of every job (under the job lock) via `_reload_strategy()`. ROOT CAUSE this fixes:
each service used to `load_strategy()` once at startup and cache it, so a deployed
config change (git pull of the bind-mounted YAML) + a staggered/partial restart
left services running DIFFERENT strategy versions — observed as divergent
`config_hash` across one chain's steps (pipeline=cd66…, builder/vetter=66b9…),
i.e. a portfolio built under different assumptions than its ranking. Reloading per
run makes all services converge on the CURRENT file every run, AND means a config
change takes effect on the next chain run with NO rebuild/restart. As a safety
net, the delta step runs `_detect_config_skew()` — it compares the upstream
ranking/portfolio/vetter `config_hash` to its own and surfaces any mismatch
(loud log + `config_skew` in the load_ranking_run step output) so a residual skew
(e.g. a config edit MID-chain) is never silent. Non-fatal (a transient deploy must
not halt the chain).

## portfolio-builder

Turns ranked stocks into target portfolio weights.

Vetter binding (seam guard): the vetter run whose exclusions are applied MUST be
bound to the SAME ranking run being built. The auto-select path (chain default,
no `vetter_run_id`) already scopes by `source_ranking_run_id`; the EXPLICIT
`vetter_run_id` path (manual API) now also verifies
`vetter_runs.source_ranking_run_id == source_ranking_run_id` and rejects a
mismatch with HTTP 400 — previously it only checked existence+status, so a
mismatched id would apply exclusions computed against a different candidate pool
(a silent vetter/builder split). Candidates the chosen vetter never scanned are
surfaced as `vetter_unvetted_remaining` (a warning, not a silent gap).

Handles:

```text
max positions
max position weight
sector caps
correlation-cluster caps — BOTH a weight cap (max_cluster_weight, default 0.15 of
  the book) and a count cap (max_tickers_per_cluster, default 3 names/cluster);
  complementary, whichever binds first wins. Weight cap = risk control (enforced in
  compute_weights); count cap = name-concentration control (enforced in
  greedy_select). Count cap is absolute (independent of weighting + max_positions);
  =1 means one name per cluster; None disables. Singletons unaffected.
cash reserve
liquidity constraints
minimum score thresholds
do-not-buy list
vetter exclusions (binding on the candidate pool; held-aware — only a drawdown
  veto drops a HELD name). NOTE: the vetter is a MANDATORY chain step — the
  `/jobs/build` endpoint returns HTTP 409 if no successful vetter run exists for
  the ranking, so a normal build never proceeds without it. "Soft" survives only
  INSIDE `_do_build` (it tolerates `vetter_run_id=None` without crashing); it is
  not a way to skip vetting in the daily chain.
turnover penalty (default 0 — DISABLED) — the builder is the SOURCE OF TRUTH
  and builds a fresh, holdings-agnostic target each day; churn-damping is owned
  by the delta engine's orphan timer (orphan_confirmation_days), not by
  biasing the target toward held names. Set
  PortfolioBuilderConfig.turnover_penalty > 0 to re-enable the old continuity
  bias (score discount on candidates NOT currently held).
```

## llm-vetter

Stock vetting layer, sits between ranking and portfolio-builder. A mandatory
step in the daily chain — the portfolio will not be built until the vetter has
successfully completed for today's ranking run.

**MODE (architecture decision 2026-07): `vetter.mode: drawdown_only` is the
default and the active config's setting — the vet step is DETERMINISTIC (no
LLM/Tavily/news in the daily chain); the beta-adjusted, vol-scaled
falling-knife veto is the sole entry block. The LLM description below applies
only when `mode: llm` is set (and VETTER_LLM_ENABLED is not false — both gates
must allow it). Chain contract identical in both modes. See
docs/architecture.md "vetter runs deterministic".**

The vetter's exclusions are binding: tickers marked for exclusion are removed
from the candidate pool before portfolio construction. The deterministic ranker
still owns the final score; the vetter does not apply positive-conviction boosts.

Candidate pool = top `candidate_count` by rank, PLUS all currently-held tickers
(a held name approaching exit must be vetted even if ranked outside top-N).

Theme-overlay candidate augmentation is RETIRED — the engine is theme-agnostic
(both the vetter, `services/llm-vetter/app/main.py`, and the portfolio-builder no
longer resolve a named theme universe; a hot sector is discovered organically by
the factors and bounded by the correlation-cluster caps). The former rule (augment
the pool with every RANKED `ai_theme_members`/`AI_BUILDOUT_SET` member so a theme
pick ranked past `candidate_count` still got a falling-knife veto) no longer
applies; there is no active `theme_overlay`.

Responsibilities:

```text
fetch news and earnings context for each ranked stock
call Tavily for web search results
compute each candidate's recent drawdown (21-trading-day peak-to-now) and feed
  it into the per-ticker LLM context — the "falling-knife" signal the 12-1
  momentum factor misses (momentum skips the most recent ~21 days, so a fresh
  crash can still look strong). See shared pure helper app/drawdown.py.
use an LLM (Ollama or OpenAI) to assess each stock
output: exclude flag, risk_type, confidence, positive_catalyst, positive_reason
store results in vetter_decisions + vetter_exclusions tables
```

risk_type enum: earnings, regulatory, management, legal, competitive,
operational, sector, drawdown, none. `drawdown` is the falling-knife category —
a severe recent price decline with no specific news event; the deterministic
backstop tags its exclusions `drawdown` so the dashboard shows a ⚠ DRAWDOWN
badge instead of a misleading ⚠ NONE. The LLM may also choose `drawdown` itself.
A `drawdown` exclusion is exempt from the "exclude with no supporting data" /
"exclude + risk_type=none" hallucination flags and from the auto-reverse-to-KEEP
override (it is price-based, legitimately newsless).

UI note: a ⚠ badge means the vetter EXCLUDED the ticker. On a buy candidate that
means "not a good moment to enter." On a stock you already HOLD a falling-knife
(drawdown) exclusion now ALSO drives a sale (see the source-of-truth redesign
below): the name is dropped from the fresh target and the delta engine
orphan-exits it after confirmation_days builds.

Source-of-truth / falling-knife-sells redesign (supersedes the earlier
"exclusion is buy-side only, held positions never sell on a veto" rule):

```text
- The portfolio-builder is the SOURCE OF TRUTH. It builds a fresh, holdings-
  agnostic target each day from rank minus binding vetter exclusions
  (turnover_penalty defaults to 0 — no continuity bias toward what is held).
- Churn-damping is owned by the DELTA engine's orphan timer
  (orphan_confirmation_days, default 2), not by biasing the target toward held names.
- A falling-knife (drawdown) veto applies to HELD names too. The held name is
  dropped from the target → becomes an orphan → delta orphan-exits it after
  orphan_confirmation_days consecutive builds. So a drawdown veto on a held position
  DOES sell it. Whipsaw guards: the orphan-build confirmation, the threshold
  (default 0.15), and the fact that the same veto blocks re-entry until the
  drawdown heals (so no sell-then-rebuy).
- Data-gap names stay exempt: no recent price history ⇒ no drawdown value ⇒
  never treated as a crash, never force-sold.
```

Falling-knife backstop — TWO triggers, either fires:
1. Beta-adjusted EXCESS (PRIMARY, DRAWDOWN_EXCESS_PCT, default 0.15): excess_dd =
   raw_dd − beta×SPY_move over the same peak→now span. Strips the market-driven
   part of the drop so a broad market-down day (which drags every stock down via
   beta) is NOT treated as a stock-specific knife — only an idiosyncratic decline
   trips it. Beta is an OLS regression of the stock on SPY (DRAWDOWN_BETA_LOOKBACK,
   default 120 days), clipped to [0,3]. Set DRAWDOWN_EXCESS_PCT=0 to disable the
   beta path (revert to absolute-only).
   VOL-SCALED (DRAWDOWN_VOL_SCALING, default true): the excess limit is per-ticker,
   = DRAWDOWN_EXCESS_PCT × (idio_vol / DRAWDOWN_VOL_ANCHOR) clamped to
   [DRAWDOWN_EXCESS_MIN 0.10, DRAWDOWN_EXCESS_MAX 0.30]. idio_vol is the stock's
   annualized residual (market-stripped) vol; anchor 0.35 = a typical name keeps
   the base limit, a calm name gets a TIGHTER limit, a wild one MORE rope. Falls
   back to flat DRAWDOWN_EXCESS_PCT when idio_vol is unavailable (insufficient
   history). The exclusion reason shows the realized limit + σ (e.g. limit -12% @
   σ28%). Set DRAWDOWN_VOL_SCALING=false to revert to the flat percentage. The
   absolute floor (#2) is unaffected — still market-blind and vol-blind.
2. Absolute FLOOR (DRAWDOWN_BACKSTOP_PCT, default 0.25): raw peak-to-now drop,
   market-blind. Set ABOVE the excess limit so the excess governs moderate drops
   (a name the market dragged down ~20% has excess < 15% → KEPT) and the floor
   only catches extreme routs (~25%+). Set 0 to disable.

Any candidate — held OR not — that trips either trigger is force-excluded even if
the LLM said keep. (History: fixed absolute 0.25 → 0.10 → 0.15, then replaced as
PRIMARY by the beta-adjusted excess (0.15) with the absolute raised to 0.25 as the
extreme-collapse floor. The 3-build orphan confirmation is the sell-side whipsaw
guard. Data-gap names — no recent prices / no beta — fall back to the floor only.)

Must not:

```text
approve or reject stocks with authority (score adjustments belong to the ranker)
call the same search query more than once per ticker
apply a non-drawdown (LLM-judgement) exclusion to a HELD name — those stay
  buy-side only. ONLY the deterministic falling-knife (risk_type='drawdown')
  backstop may exclude a held name, which drops it from the fresh target so the
  delta engine orphan-exits it (source-of-truth / falling-knife-sells redesign).
  All held exits still flow through delta → risk-service → trade-executor; the
  vetter itself never submits trades.
```

## alpaca-sync

Syncs Alpaca state into Postgres.

Reads:

```text
account
positions
orders
fills
buying power
portfolio value
```

Does not submit orders.

## intraday-monitor

Uses Alpaca real-time or near-real-time market data.

Watches:

```text
current holdings
top watchlist names
SPY
QQQ
IWM
SOXX
```

Calculates intraday state such as:

```text
current return
relative return vs benchmark
volume vs normal
VWAP distance
intraday high/low
time-of-day context
```

Creates signals only.

Does **not** place trades directly.

## risk-service

Hard safety gate. Approves or rejects trade intents.

The LLM must not bypass this service.

Implemented controls (Phase 6):

```text
KILL_SWITCH                 — rejects all checks
LIVE_TRADING_ENABLED        — gate for trade_type="live"
PAPER_ONLY                  — rejects any live trade
MAX_ORDER_NOTIONAL          — per-order dollar cap; scale-aware: effective cap =
                              max(MAX_ORDER_NOTIONAL, MAX_ORDER_PCT × account_value)
                              (MAX_ORDER_PCT default 0.20; 0 = absolute-only), so a
                              grown account keeps rotating instead of silently
                              rejecting every entry once weight×equity > the fixed cap
MAX_DAILY_TURNOVER_PCT      — default 0.50; DISCRETIONARY-churn cap per
                              simulation day (delta_runs.run_date when
                              trade-executor passes sim_date, else CURRENT_DATE).
                              ONLY sell_trims count and are capped — EXITS ARE
                              EXEMPT (a de-risking close / builder-dropped rotation
                              must never be throttled). Entries aren't churn either.
                              (F1 fix: exits were formerly counted+capped, so a big
                              rotation — mostly exits — emitted exits the gate then
                              rejected; the planner doesn't model turnover, so
                              exempting exits removes that planner/gate divergence.)
                              Set to 1.0 to disable.
MAX_DAILY_LOSS_PCT          — default 0.10 (10%); halts ALL trades when the
                              account is down > X% vs the day's first sync.
                              Automated complement to KILL_SWITCH.
MAX_POSITION_PCT            — default 0.15 (15%); refuses entries/buy_adds
                              that would push a ticker above X% of account_value.
                              Backstop to portfolio-builder's max_position_weight
                              for the price-drift case.
MAX_POSITIONS               — default 35; refuses entry when the PROJECTED
                              post-rotation book reaches X distinct tickers and
                              this entry is for a new (not-yet-held) ticker.
                              Projected = held − held names being EXITED this
                              cycle + queued new-ticker entries (all day orders
                              settle at the same open, so a full rotation nets
                              out instead of self-wedging). "Being exited" is
                              detected from a queued exit ORDER (any
                              OPEN_ORDER_STATUSES, incl. 'deferred') OR an exit
                              INTENT in the run's delta_intents (scoped by
                              sim_date). The intent source is order-independent —
                              required because auto-approve does NOT submit all
                              exits before entries, so an early-checked entry
                              would see zero deferred exit ORDERS, reject, and
                              never retry (the confirmed "42 projected" race).
MAX_DATA_AGE_HOURS          — default 96 (4 days, weekend-safe); refuses
                              entries/buy_adds when the latest successful
                              pipeline run is older than threshold. Sells
                              not affected (exiting on stale data is safe).
MAX_SYNC_AGE_HOURS          — default 24; refuses ALL trades when the latest
                              successful alpaca-sync is older than threshold —
                              broker state unreliable, sizing would be wrong.
qty > 0
notional > 0
human approval window with auto-approve fallback
  — dashboard polls /delta/latest every 30s; after
    TRADE_AUTO_APPROVE_MINUTES (default 60) a human hasn't approved
    or rejected an entry/exit/buy_add/sell_trim intent, the dashboard
    posts /trade/approve automatically. Vetter-excluded BUY-side intents
    (entry/buy_add) require a human; sells (exit/sell_trim) auto-approve
    regardless of vetter (closing must always be allowed).
    Rule: MANUAL run (run-now, delta_runs.manual=true) → human approves (no
    timer); AUTO/cron run → auto-approve after the timeout. Both the timer and
    the auto-approve POST are ALSO suppressed while a fresh chain is in progress
    (scheduler /status == "running" or the dashboard's run-now supervisor active):
    during a mid-chain window /delta/latest still points at the PRIOR cycle's
    delta, so acting on it would count down / auto-submit stale intents that
    today's run is about to replace. The UI countdown override is gated on NO
    chain step running (not just the ranking step) so it can't overwrite the live
    vetter/portfolio label.
chain liveness — scheduler /health/chain returns 503 if no successful
  chain in CHAIN_HEALTH_MAX_AGE_HOURS (default 36h); api proxies it
  at /health/chain for external monitors.
```

All safety env vars are re-read on every `/check` call.
However, `os.getenv()` reads the frozen process environment, so changing an env
var via `docker exec -e` does NOT take effect without a restart. To hot-flip
the kill switch at runtime without restarting, use the control file instead:

    docker exec stocker-risk-service-1 touch /tmp/kill_switch   # ON
    docker exec stocker-risk-service-1 rm    /tmp/kill_switch   # OFF

The file takes precedence over the KILL_SWITCH env var when present. The env var
still sets the startup default.

Persists every decision to `risk_decisions` with an env snapshot at decision
time. `alpaca_orders.risk_check_id` is a FK into this table — answers
"which rule approved/rejected this trade?" auditably. The FK is the hard
audit guarantee; if `_persist_decision` fails for an APPROVED decision, the
service returns 503 so the trade-executor never proceeds without an audit row.

Defense-in-depth pairings: trade-executor's `EXIT_SYNC_MAX_AGE_HOURS` and
risk-service's `MAX_SYNC_AGE_HOURS` both guard against stale alpaca-sync
(executor refuses to size, risk-service refuses to approve). Portfolio-
builder's `max_position_weight` caps at construction; risk-service's
`MAX_POSITION_PCT` catches price-drift over-concentration on subsequent
buy_adds. See `docs/risk-safety-rules.md` for the full table.

Risk service is deterministic and heavily tested.

## trade-executor

Only service allowed to place Alpaca orders. Full orchestrator of the
approval click — no other service does sizing or risk-checking.

Per-ticker dedup is ATOMIC (seam fix). The in-flight buy/sell guards
(`_open_buy_order_for_ticker` / `_open_sell_order_for_ticker`) run twice: an
out-of-lock FAST PATH (skip work for the common duplicate) AND an atomic RE-CHECK
inside `with_submit_lock` right before the reservation. Same-intent dups are
DB-enforced (the `idx_alpaca_orders_intent_open` partial unique index on
intent_id), but there is NO unique index on ticker — so two concurrent
same-ticker / different-intent approvals could both pass the out-of-lock check
before either recorded (a doubled position). The in-lock re-check closes that
race: the submit lock serializes all account submits, so the loser sees the
winner's committed order and returns `duplicate`.

Endpoint: `POST /jobs/submit {intent_id, mode}` → `TradeAttemptResponse`.

Per-click steps (each logged to execution_steps under one trace_id):

```text
idempotency_check  — reject if intent already has an open/submitted order
load_intent        — read delta_intents (joined with delta_runs to get the
                     run's sim_date, passed to risk-service for turnover scoping)
size_order         — entries / buy_adds: floor(account_value × weight / last_price)
                     sell_trims: floor(account_value × drift / last_price)
                     exits: full position qty from latest live_positions
                     All actions size against account_value (total equity) so a
                     fully-invested portfolio replacing one exited position gets
                     a correctly-sized entry. With day orders submitted post-close,
                     exits and entries queue for the same open so cash flow nets
                     out without requiring a buying_power-based sizing constraint.
                     refuse if qty < 1 (position too small)
                     refuse if alpaca-sync > EXIT_SYNC_MAX_AGE_HOURS old
                     (stale balances would size wildly wrong orders)
risk_check         — call risk-service /check, with sim_date for turnover scoping
record_order       — INSERT alpaca_orders (status = pending | risk_rejected)
submit_alpaca      — POST /v2/orders if approved + credentials present
```

Persists:
- one alpaca_orders row per attempt (status reflects final outcome)
- one execution_traces row (job_type='trade_approval')
- one execution_steps row per stage with input/output JSON

Order params:
- type = "market"
- time_in_force = "day" for ALL orders regardless of mode. Day orders are
  accepted by Alpaca 24/7 and queue for the next market session when submitted
  outside market hours. They stay open all day, avoiding the OPG expiry
  problem where orders expire if the stock has no opening auction print.
  The `mode` field in alpaca_orders is kept for audit (records whether the
  click was immediate vs scheduled) but does not change the Alpaca order type.

Submission routing (`_route_to_drain`): during market hours an `immediate`
approval submits SELLS inline (they fill in seconds and free buying power) but
routes BUYS (entry/buy_add) to the fill-gated drain, which releases each buy only
once live buying power covers it. This stops a fully-invested rotation from firing
its buys inline before the sells settle (the confirmed "insufficient buying power"
on a rotation). Market-closed drains everything; scheduled always drains. The
executor's `_call_risk` retries transient transport errors / 5xx
(RISK_CALL_RETRIES, default 3) so a risk-service blip mid-approval (e.g. a
redeploy) doesn't fail a close; a real risk REJECTION (HTTP 200) is never retried.

Short-circuits when ALPACA_API_KEY is empty (records a failed row, no HTTP call).

`trade_type` on every risk check is DERIVED from ALPACA_BASE_URL
(`trade_type_for_base_url`): "live" iff the host is api.alpaca.markets, else
"paper" (paper-api, alpaca-sim, anything else). So pointing the executor at the
real broker requires ALSO setting LIVE_TRADING_ENABLED=true + PAPER_ONLY=false
or the risk-service rejects every order — going live is a two-key turn, never a
single env-var slip. (Previously hardcoded "paper", which made those gates
decorative.) See docs/risk-safety-rules.md.

No other service should contain Alpaca order-submission credentials.
alpaca-sync also has Alpaca credentials but only performs read calls
(`GET /v2/account`, `GET /v2/positions`, and `GET /v2/orders` to reconcile
fill status — read-only; it never submits or cancels orders).

Initial implementation is paper-trading only.

## llm-gateway

Single interface to API LLMs or local LLMs.

Responsibilities:

```text
provider abstraction
prompt templates
structured JSON output
schema-aware generation
retry logic
audit logging
cost/token tracking
local/API model switching
```

The rest of the system should not care whether the model is OpenAI, Anthropic, local Ollama, vLLM, etc.

## strategy-config-service

Turns plain-English strategy prompts into YAML/JSON configs through `llm-gateway`.

Saves:

```text
original prompt
generated config
LLM explanation
version metadata
prompt hash
config hash
```

Does not approve configs for live use by itself.

## strategy-validator

Validates LLM-generated configs against a strict schema and safety constraints.

Rejects:

```text
invalid schema
unknown fields
dangerous risk limits
missing required fields
unbounded position sizing
live trading without approval
unsupported execution behavior
```

No config should reach the trading system unless it passes validation.

## backtester

Replays historical data using a strategy config.

Outputs:

```text
simulated trades
returns
drawdowns
turnover
Sharpe-like metrics
benchmark comparison
position history
period-by-period holdings history
```

Backtester should be deterministic and reproducible.

Two MODES, both scored by the same de-biased simulator + validation verdict
(it will be a TOOL the evaluator LLM calls, so the numbers must be faithful):

```text
persisted_replay  POST /jobs/backtest         — re-scores portfolio_runs ALREADY
                    built (under whatever config produced them): "how did what we
                    actually held do?".
config_replay     POST /jobs/backtest-config  — G1. Re-RANKS + re-SELECTS every
                    historical rebalance date under a CANDIDATE config (inline
                    `config` or a `config_path`) using the live chain's OWN
                    deterministic code: "what would THIS config have done?".
```

config_replay reuses `rank_universe` + builder `select.py` via
`shared/stock_strategy_shared/strategy_engine/` — the CANONICAL module both
production and backtest import (the former byte-synced `_vendor` copies are
now re-export shims; `tests/backtester/test_vendor_sync.py` asserts module
IDENTITY). No look-ahead: factors are the PERSISTED
point-in-time `factor_scores` per date; covariance/regime/beta for date D use only
prices ≤ D; the simulator fills at D+1. NOT modelled (surfaced as
`config_replay_caveats`): vetter exclusions (run-time, not config), turnover-
penalty continuity (replay is holdings-agnostic = builder default), per-date
as-of sector labels (latest-as-of used). De-bias (G3/G5): t+1 fills, delisted
exits at last real price, missing prices held at 0% in the full-weight denominator
(no survivor boost), 10 bps default cost, DISTRIBUTION stats (skew/kurtosis/pctls)
not just the mean. Honest multiple-testing (G2/G4): every run records a
`backtest_trials` row first so DSR/PBO deflate by `COUNT(DISTINCT config_hash)`
tried; short samples flagged DIRECTIONAL. `backtest_runs` gains
summary/validation/sim_mode/config_json (migration 0039). Config reloaded per job
(G6). See docs/architecture.md "backtester as a trustworthy evaluator tool".

### The ranked universe per rebalance (`bt_sweep_rankings`)

```text
Every other bt_sweep_* table records what the book DID. None can answer
"what did we pass over, and how did it do?"
```

`target` holds only the survivors, so after the fact a name absent from it is
indistinguishable from a name that was never ranked. That made growth-capture,
oracle recall and paired regret impossible — and `forest_map` had been declaring
the gap in its own `missing` field since it was written.

`bt_sweep_rankings` records the ranked HEAD per rebalance with `selected` and
`reject_reason`. Those two columns are what make it more than a rank dump: they
separate "the model ranked it low" (a FACTOR-MODEL miss) from "the model ranked
it high and the builder refused it" (a CONSTRUCTION miss) — different failures
with different fixes, and a single "we missed winners" number cannot tell them
apart. `forest.growth_capture` computes exactly that split and NAMES which one it
implicates.

CAPPED at `BT_RANKING_ROW_CAP` (default 100) rows per date: 20 years x ~2000
names daily is ~10M rows per config, a corpus rather than a diagnostic. The cap
is reported as `summary.ranking_rank_cap` and stored on `bt_sweeps`, because
without it "absent from the table" is ambiguous between "ranked and passed over"
and "beyond the cap" — an ambiguity that would silently corrupt every recall
number computed from it. Readable by the evaluator's `bt_sql_query`.

### Factor-coverage contract (wind tunnel ↔ live)

```text
The wind tunnel may not score a config that puts nonzero weight on a factor
it cannot compute.
```

`composite_scores` renormalizes per row over the NON-NULL factors — correct for a
factor missing on SOME tickers, catastrophic for one missing from the whole
corpus: it silently redistributes the weight instead of erroring. bt-engine never
passed `earnings=` and bt-data never ingested earnings, so `earnings_surprise`
(weight 0.12 in momentum_rotation_v2) was null everywhere and momentum was
effectively scored at 0.409 instead of 0.360. Every wind-tunnel run scored a
config nobody supplied, and auto-promotion could act on it.

Enforcement lives in `services/bt-engine/app/coverage.py`, fail-closed:

```text
check_config_coverage()  static, at request time. Judges every weight vector the
                         config could USE, via effective_factor_weights() over
                         all four regimes (so regime_weighting_enabled is
                         honoured rather than re-derived).
CoverageObserver         empirical backstop: was each weighted factor EVER seen
                         non-null across the whole run? End-of-run, not first
                         rebalance — a factor may legitimately be null during
                         warm-up. Raises CoverageError; the sweep turns that into
                         a per-config error row, never a fake score.
/jobs/run                422 on violation.
/sweeps/run              422 on a violating BASE config; violating CANDIDATE
                         diffs join the existing extra_dropped channel so one bad
                         evaluator proposal can't kill the standing sweep.
BT_COVERAGE_ENFORCE=false disables (default on); violations are still LOGGED —
                         a disabled gate that is also silent is the original bug.
```

**The blind spot the contract shared with itself (2026-08): SILENT FALLBACKS.**
Both checks ask "is the factor non-null?" — a question a graceful degradation
path answers YES to while computing something else. `quality_use_gross_profitability`
(set by EVERY config in the repo) makes quality gross-profits-to-assets;
`compute_quality` falls back to ROE PER TICKER when `gross_profit`/`total_assets`
are missing. bt-data never mapped SF1's `gp`/`assets`, so the tunnel took that
fallback everywhere and scored ROE-quality under a GPA config at 25% of the
composite, with `quality` fully populated and both checks green. The parity
manifest called `factor_engine` HONOURED because it is "the SAME module" — true,
and insufficient: same module + different INPUT COLUMN = different factor.
Fixed by mapping `gp`/`assets` (via `_level()`, not `_f()` — a large bank's
assets are ~$4e12 and the 1e12 RATIO guard would null exactly the biggest names)
and by `coverage.DEFINITION_INPUTS` + `check_definition_coverage(config, frame)`,
which asks whether the corpus carried the inputs for the DEFINITIONS the config
selected. Whole-corpus, never per-ticker (one missing filing is what the fallback
is for); raised UP FRONT, before any compute. Add an entry whenever a factor
gains a fallback. Consequence: the tunnel REFUSES every repo config until the SF1
stage is RE-BACKFILLED (price corpus untouched), and prior sweep numbers touching
quality are void.

Coverage closed in bt-data: SF1 `marketcap` → `market_cap` (small_cap),
`sharesbas`/`shareswa` → `shares_outstanding` + `shares_outstanding_prior` from
the rows[i-4] year-ago filing (issuance), and `bt_earnings` (per-filing EPS,
POPULATED BUT NOT YET CONSUMED). NOTE: market cap and share counts go through
`_level()`, not `_f()` — `_f`'s MAX_MAGNITUDE of 1e12 is a RATIO guard and would
silently null a mega-cap's market cap. `init_bt.sql` is re-applied idempotently
by bt-data on every startup, so an existing bt-postgres picks up the new columns
without a manual migration; the SF1 stage must be RE-BACKFILLED to populate them
(the ~35M-row price corpus is untouched).

`earnings_surprise` remains UNSUPPORTED: Sharadar carries reported EPS but no
analyst estimate, so live's analyst-based SUE cannot be reproduced verbatim.
Until definitional parity lands, the active config is refused and AUTO-PROMOTION
IS PAUSED — the intended state, since the alternative is promoting on evidence
known to be wrong. Resolution is always to teach the tunnel; removing a factor
from live because the test rig cannot see it lets the instrument dictate the
strategy. See docs/architecture.md "factor-coverage contract between live and the
wind tunnel".

All pre-existing bt_sweeps / bt_sweep_results / bt_runs rows are VOID (this plus
the `-96%` simulator bleed). The evaluator can read those tables, so purge them
with `scripts/purge-void-bt-results.sh --yes` (dry-run by default; refuses while
a job is in flight; deletes RESULTS tables only and clears the
artifacts/bt/*.json bridge — never the source corpus).

### Wind-tunnel fidelity: the parity manifest

```text
Every parameter that can change live behaviour needs an explicit wind-tunnel
parity declaration. Where the tunnel cannot model one, it REFUSES the config
rather than scoring it as if the parameter were absent.
```

The factor-coverage contract closed one instance; `turnover_penalty` was the same
bug a layer up (live passed `current_holdings`/`turnover_penalty` into
`greedy_select`, the simulator did not, so a nonzero penalty was scored as zero).
TWO simulators answer "what would this config have done?", so there are TWO
declarations over ONE shared mechanism (`shared/stock_strategy_shared/parity.py`
— a NEW shared module file, so `docker build --network host -t stocker-base:latest -f Dockerfile.base .` FIRST):

```text
services/bt-engine/app/parity.py    the wind tunnel. Baseline = SCHEMA DEFAULTS
                                    (it recomputes everything from raw data).
                                    BT_PARITY_ENFORCE=false downgrades to a log.
services/backtester/app/parity.py   config-replay. Baseline = the ACTIVE CONFIG,
                                    because it re-ranks factor_scores PRODUCTION
                                    computed — only a CHANGE to factor
                                    construction is unmodellable. Comparing it to
                                    schema defaults would refuse the active config
                                    itself. BACKTESTER_PARITY_ENFORCE=false.
```

Each declares every StrategyConfig field HONOURED / PARTIAL / IGNORED with a
reason; the check refuses (422) a config setting an IGNORED field away from the
baseline. config-replay's IGNORED set is much larger — it applies NO exclusions
(not even the deterministic falling-knife veto), is holdings-agnostic (so
`turnover_penalty` is inert), infers eligibility from price presence, and above
all does NOT recompute factors. The evaluator's `run_backtest` posts THERE, so
that gate is what stops a factor-construction diff coming back with a Sharpe
attached; a 422 refunds the budget slot and names the wind tunnel instead.

Three guards: every schema field must be classified (a new field fails CI until
someone decides); an AST diff asserts the live and tunnel
`greedy_select`/`compute_weights` call sites pass the same kwargs; and
`tests/parity/` runs config-replay's composer on a frozen fixture asserting
HONOURED fields CHANGE the target and IGNORED fields leave it BIT-IDENTICAL.
That last one caught `min_score_percentile` mis-declared IGNORED in both
manifests (it is applied inside the shared `rank_universe`).

NOT yet proven: that the wind tunnel's target equals the LIVE builder's on
identical inputs. That needs live `_do_build`'s composition extracted from its DB
coupling into a shared function, the same treatment rank/select already had.

Also fixed in the same batch (docs/architecture.md "wind-tunnel fidelity batch"):

```text
factor cache      keyed on bt_data_version (bumped by bt-data after EVERY write),
                  not on data SHAPE — row counts/date span do not change when data
                  is corrected in place, so a re-backfill left a stale cache
                  looking valid. No version readable ⇒ cache DISABLED (fail-closed).
fills             NO PRINT, NO FILL. The last_px fallback executed trades against
                  securities with no market, and (post the -96% fix) the phantom
                  fill stamped last_seen, resetting the delist timer. Dropped
                  orders are reported in summary.unfilled_orders.
delisting         SimParams.delist_recovery_pct (default 0.70) + transaction cost.
                  Full recovery of the last mark flattered distressed strategies.
                  A FLAT rate incl. mergers — a bias correction, not a model.
delist gap        counted in real SESSION INDICES, not `(D-last_seen).days > 7*2`.
universe          point-in-time eligibility from Sharadar firstpricedate/
                  lastpricedate/isdelisted. Sector labels remain CURRENT-STATE
                  (no vendor history) and stay in caveats.
target status     TargetStatus.{SUCCESS_WITH_TARGET,SUCCESS_EMPTY_TARGET,DEGRADED,
                  FAILED} replaces `if target:` — a deliberate risk-off target is
                  now obeyed, a degraded build still holds the book.
counters          n_rebalances = EVALUATIONS (was "dates that produced trades");
                  turnover from REALIZED fills, not decision-time intended notional.
eligibility scope min_non_null_factors_scope: "all" (default, unchanged) |
                  "weighted". Weight-0 factors counting toward eligibility means a
                  data-engineering change can move CAGR; the default is NOT flipped
                  because "weighted" is a large live strategy change — backtest first.
```

## evaluator

Weekly LLM strategy review. OBJECTIVE (owner-set, in its system prompt + docs):
maximize long-run compounded ABSOLUTE return — SPY is the hurdle not the target;
risk limits are constraints not goals; prefer expected return over Sharpe within
the constraints. Phase 1 BUILT (read-only). See
docs/architecture.md "Design Decision: weekly LLM evaluator loop".

```text
1. Python assembles a deterministic evidence packet (packet.py): a SYSTEM-
   ARCHITECTURE BRIEF (how the machine works + known non-features, so the LLM
   can critique structure, not just knobs), active strategy YAML + hash,
   universe snapshot, SELECTION AUDIT (every builder candidate classified
   selected / cap_blocked / vetter_excluded / out_ranked with forward returns
   per class — cap_blocked beating selected implicates CONSTRUCTION;
   out_ranked beating selected implicates the FACTOR MODEL),
   evaluator_weekly factor IC/marginal-IC evidence, account equity vs SPY
   since inception, per-trade realized P&L, counterfactual audits (what
   vetter-excluded / exited names did AFTERWARD), current target book
   (weighted beta, sector weights), config-hash history, system-health
   caveats. Best-effort per section; persisted verbatim.
2. An Opus-class model (EVALUATOR_MODEL, default claude-opus-5, adaptive
   thinking) reviews it VIA THE LLM-GATEWAY and returns structured JSON:
   narrative markdown + recommendation objects (YAML-knob tweaks) +
   STRUCTURAL FINDINGS (gaps needing code/new data: missing factors, missing
   data sources, selection/exit/vetting logic flaws — categorized, evidenced).
3. Each recommendation's config_field is validated against the real
   StrategyConfig schema — unknown fields are flagged non-actionable;
   config_field 'none' = general advice (valid, non-edit).
4. Stored in evaluator_reports (migration 0037); dashboard Review tab renders
   verdict, recommendation cards, structural-finding cards, narrative,
   history; manual RUN REVIEW button.
```

Trigger: scheduler POSTs /jobs/evaluate hourly on weekend days (ET); the
evaluator dedupes to one report per ISO week. EVALUATOR_ENABLED=false disables.

Phase 2 (BUILT): read-only TOOLS mid-review (app/tools.py + app/agent.py; the
llm-gateway already carried tool-use — tool EXECUTION stays in deterministic
Python). The packet is NOT replaced — it remains the deterministic opening brief;
tools are for drill-down and testing a thesis BEFORE recommending it:
  run_backtest — config-replay a candidate config expressed as a {dotted.path:
    value} DIFF over the ACTIVE config, schema-validated before anything runs;
    returns summary + DSR/PBO validation; each run auto-registers a trial so the
    DSR the LLM sees deflates by its own search breadth. Budget
    EVALUATOR_MAX_BACKTESTS (default 3/review).
  sql_query   — ONE SELECT/WITH inside SET TRANSACTION READ ONLY (DB-level hard
    guarantee) + statement_timeout + row cap.
  read_file   — repo source/docs/strategies rooted at /repo (compose mounts
    services/shared/docs/strategies/db READ-ONLY — never the repo root, so .env
    is unreachable); traversal-guarded, credential-shaped basenames blocked.
  web_search  — Tavily (absent when TAVILY_API_KEY unset).
  preview_ranking — FAST rank-level triage of a config diff (imports the
    canonical shared strategy_engine.rank via the _vendor shim): top-N
    membership changes + movers vs the active ranking, before spending a
    run_backtest slot. No builder caps/vetter. Budget EVALUATOR_MAX_PREVIEWS (8).
    RE-WEIGHTS persisted scores, so it CANNOT see a factor_engine change.
  preview_factor_recompute — the tool for that case, and the ONLY cheap one.
    `preview_ranking` and the backtester's config_replay both re-weight PERSISTED
    `factor_scores`, so a change to how a factor is COMPUTED (momentum_blend_windows,
    momentum_method, volatility_window, pe_pb_cap, sue_method,
    industry_neutral_factors) scored IDENTICALLY to the active config in both —
    silently. `factor_construction` was the one MECHANISM with no cheap test; the
    only route was a multi-hour wind-tunnel run (one candidate burned 3h31m and a
    lane slot for -1.18pp). This POSTs the whole candidate config to the pipeline's
    read-only `POST /preview/factors`, which RECOMPUTES every factor for the latest
    scored date and returns both rankings + per-factor coverage/rank-correlation +
    `baseline_fidelity`. The recompute lives on the PIPELINE because
    `compute_all_factors` and its ~200 lines of loader SQL do (promoting them to
    `shared/` would force a stocker-base rebuild everywhere; re-implementing them in
    the evaluator would score a different universe than the chain). Both sides are
    recomputed on ONE frame with `copy_input=False` — safe because those in-place
    mutations are idempotent, which is what makes recomputing our own baseline
    affordable. `universe.*` diffs are REFUSED (422) because the preview reuses the
    prior run's investable set, which is what makes the diff apples-to-apples.
    NO `backtest_trials` registration: a rank diff is not a performance estimate and
    must not deflate anyone's DSR. Budget EVALUATOR_MAX_FACTOR_PREVIEWS (4).
    See docs/architecture.md "the factor-recompute preview".
  queue_strategy_experiment also takes an optional `predicted_tune_cagr_edge`:
    a COMMITTED number (0.02 = +2pp) for how much the candidate should beat the
    baseline's tune CAGR. The lane scores predicted-vs-actual when the run lands
    and the packet's `prediction_scorecard` reports the running SIGNED bias —
    the evaluator is now accountable on the same terms it holds the strategy to.
    See docs/architecture.md "score the evaluator's own predictions".
  The packet's `score_calibration` section answers "does a better rank actually
    predict a better forward return". Its math is CANONICAL in
    `shared/stock_strategy_shared/calibration.py` — bt-engine's
    `app/calibration.py` is a re-export shim. There used to be two
    implementations (bt-engine's and an inline copy in packet.py); they drifted,
    and every defect landed in the live one: 6 anchors sampled from a 21-90d
    window against a 20-session horizon (so they OVERLAPPED — closer to 2
    independent samples), no strategy_id/config_hash filter (curves from
    DIFFERENT factor weights averaged into one), regimes pooled, an UNBOUNDED
    forward-price lookup (a name that stopped printing after d0 resolved to its
    own baseline → a delisted position scored as exactly FLAT, which inflates the
    low deciles it concentrates in and SHRINKS top-minus-bottom), and a point
    estimate with no interval. All fixed: anchors spaced >= one horizon
    (`space_out`), scoped to the active config with the excluded count reported,
    forward price bounded both sides with `missing_endpoint_rate` surfaced,
    per-date rank IC + bootstrap CI + `prob_positive`, and a per-regime split
    (suppressed below 2 dates in a regime). CALIB_MAX_RUNS 6→24 over
    CALIB_LOOKBACK_DAYS 730; BT_CALIB_MAX_DATES 12→60. NEW shared module ⇒
    `docker build --network host -t stocker-base:latest -f Dockerfile.base .`
    FIRST. See docs/architecture.md "the calibration instrument had to be fixed
    before it could be believed".
  hypothesis_ledger — durable cross-week memory (evaluator_hypotheses, migration
    0041): thesis → planned test → status/outcome. The ONE write tool, scoped to
    its own table; read back as a deterministic packet section every review.
    Budget EVALUATOR_MAX_LEDGER_WRITES (6).
  Every bt-engine run summary now carries `terminal_wealth`: a circular-block
    bootstrap of the realised returns into a DISTRIBUTION of end-of-period money
    (median, p5/p25/p75/p95, prob_loss, paired prob_beat_benchmark). The
    promotion gate's fourth condition compares 5th-percentile terminal wealth
    against the baseline (BT_PROMOTE_TAIL_TOLERANCE, default 0.05) — CAGR and a
    single realised drawdown cannot see a tail that did not happen to fire. The
    rule is shared/stock_strategy_shared/wealth.py (NEW shared module ⇒ rebuild
    stocker-base). See docs/architecture.md "terminal-wealth distributions".
  bt_sql_query — read-only SELECTs on the WIND TUNNEL's RESULTS tables
    (bt_sweeps, bt_sweep_results, bt_sweep_aggregates, bt_runs, bt_equity,
    bt_positions, bt_trades) so a review can explain WHY a candidate won and
    diagnose a failing lane itself, instead of only seeing summary numbers
    crossing the artifact bridge. Python-side ALLOWLIST; the raw corpus
    (bt_prices ~35M rows, bt_fundamentals) is deliberately unreachable — ad-hoc
    mining of 20 years bypasses the backtest_trials accounting that deflates the
    DSR. Reaches bt-postgres via its published host port (BT_DATABASE_URL);
    unset or unreachable ⇒ the tool disappears and the prompt says so.
queue_strategy_experiment also takes an OPTIONAL `regime`: a NAMED historical
crisis (gfc_2008, covid_2020, bear_2022, energy_shock_2015, volmageddon_2018)
scored instead of the rolling recent window. Raw date ranges are NOT offered —
choosing both the config and the period searches two dimensions while the DSR
penalises one. A regime run is DIAGNOSTIC ONLY and can never promote (its two
spans are crash/recovery halves, not a tune/hold-out pair); a regime starting
inside the factor warm-up runway is refused. See docs/architecture.md "named
stress regimes".
The packet also carries `backtest_lab` — the one-way results bridge from the
isolated backtest stack (artifacts/bt/latest_sweep.json, written by
bt-scheduler): the latest walk-forward sweep leaderboard, decision-grade
evidence the prompt tells the model to prefer over the short-history replay.
Loop budget EVALUATOR_MAX_TOOL_TURNS (default 24); exhaustion strips tools and
demands the final report JSON. EVALUATOR_TOOLS_ENABLED=false → Phase-1
packet-only (also the automatic fallback on a hard tool-loop failure). Every
call persisted in evaluator_reports.tool_transcript (migration 0040) for audit.
Phase 3 REMOVED (2026-07, owner decision): the one-click human apply
(`POST /config/apply` + the Review-tab Apply buttons) is GONE, together with
the single-field `queue_experiment` tool and the recommendation→experiment
harvest. There is now ONE currency and ONE path: the evaluator authors a
COMPLETE candidate StrategyConfig (`queue_strategy_experiment` — to change a
single field it sends the whole YAML with that field changed), the daily lane
scores it against the current champion on a TUNE window plus a HELD-OUT
validate window, and only a winner is applied — by deterministic code, never by
the LLM and never by a click. `recommendations[]` remain ADVISORY (reasoning,
structural findings, things a config cannot express). Manual override is a YAML
edit + deploy; revert is copying an `artifacts/config/history/` archive back.

Phase 6d (BUILT, 2026-07 — owner decision): AUTO-PROMOTION in PAPER mode.
Config changes no longer need a human click: the evaluator authors whole
candidate configs (queue_strategy_experiment), the wind tunnel scores them on
the RECENT window (BT_EXPERIMENT_RECENT_YEARS, default 3y) vs a recent-window
baseline of the active config, and the deterministic gate (promotion_eligible:
CAGR edge ≥ BT_PROMOTE_MARGIN, drawdown within BT_PROMOTE_DD_TOLERANCE) writes
artifacts/bt/promotion.json; the live api's promotion watcher
(AUTO_PROMOTION_ENABLED) validates the WHOLE config through the
strategy-validator (fail-closed), archives, audits (config_changes,
applied_by='auto_promotion'), and atomically replaces the active YAML. Human
approval remains for STRUCTURAL changes (code, data sources, risk env, going
live). Live-money preconditions before this stays on with real dollars are
recorded in docs/architecture.md "Phase 6d".

The watcher enforces `PROTECTED_PATHS` BEFORE the schema gate: it calls the
validator's `/validate-llm-change` with the ACTIVE config as baseline and refuses
any candidate that changes a protected field. Without this the partition was
decorative on the only path that reaches production — the evaluator is forbidden
from PROPOSING `strategy_id` / `universe.source` / `vetter.falling_knife` /
`trailing_stop.enabled` while promotion was free to APPLY them, so a winning
sweep could have flipped an exit regime live unattended. Fail-closed: an
unparseable baseline or unreachable validator writes no state and retries next
poll. AUTO-REVERT is deliberately NOT gated this way — a revert is de-risking,
and blocking it on a protected diff could strand the system on a config it has
already judged bad.

The evaluator service itself still never writes the live config — the
deterministic watcher does. Never submits trades, never bypasses risk.

## scheduler

Non-blocking supervisor state machine that advances a daily chain in strict
sequence. Each step only starts after the previous one succeeds. Nothing is
optional — if any step fails, the chain halts:

```text
fetch-data        → av-ingestor       /jobs/fetch-data
pipeline          → pipeline          /jobs/run          (factors + rank)
vet               → llm-vetter        /jobs/vet          (mandatory; exclusions feed portfolio)
portfolio-builder → portfolio-builder /jobs/build        (refused if no vetter run for today)
delta             → pipeline          /jobs/delta
```

Pre-delta stale-order purge is FAIL-CLOSED (seam fix). Before the delta step the
supervisor POSTs `/jobs/cancel-deferred` to purge the prior cycle's un-sent
deferred orders (so they can't fire stale at the open or pollute the new delta's
capacity view). `_cancel_deferred_orders` now RETRIES transient failures
(CANCEL_DEFERRED_RETRIES, default 3; backoff CANCEL_DEFERRED_BACKOFF_SECS) and
returns a bool; if the purge can't be confirmed the delta step is NOT triggered
this tick (returns idle) and the supervisor retries next tick. This replaced the
old fail-OPEN behaviour ("error — proceeding anyway") that let a silent purge
failure leak stale deferred orders into the new cycle. It self-heals once the
trade-executor is reachable again.

The chain is triggered in exactly two ways:
1. **Daily schedule** — scheduler fires after market close (SCHEDULE_TIME_ET, default 16:15)
2. **Manual** — `POST /jobs/run-now` (dashboard "Run" button) sets `_force_pending`
   and re-executes today's chain from scratch through all five steps

The chain is **keyed by the trading SESSION it processes**, not wall-clock
`today` — `latest_closed_session(now_ET)` in `services/scheduler/app/staleness.py`
(the most recent NYSE session past its 16:00 ET close). This session date is
**stable across midnight** (it rolls only at the next close), which is the fix for
the cross-midnight abandon bug: a chain that starts at 22:30 ET and runs past
midnight keeps the same key, so the supervisor no longer mistakes it for a new
cycle, force-`failed`s its `scheduler_runs` row, and orphans the in-flight fetch
(which left the dashboard stuck on "READY").

The **data-frontier start gate** starts a fresh chain only when the latest closed
session is unprocessed: `last_processed_session < latest_closed_session` (where
`last_processed_session` = latest successful `delta_runs.run_date`). This subsumes
the old `should_run_chain` trading-calendar gate (on a weekend the session is the
prior Friday, so once Friday is processed there is nothing to do; a missed Friday
still catches up) and also avoids re-opening a redundant chain once a trading-day
session is done. A scheduled-time floor (`_is_after_scheduled_time`) is kept
because AV publishes EOD data ~1–2h after the close and the exact time is unknown.
The gate only governs STARTING a chain; once one is open it advances every tick.
Manual run-now bypasses the gate.

Each tick (every SUPERVISOR_INTERVAL_SECS) reads each service's `/runs/latest`
and triggers the first idle step, then returns. After the session's chain reaches
a terminal state, further ticks are no-ops until the session rolls over (the next
NYSE close), at which point `_chain_status` resets.

On session rollover the supervisor first calls `_db_close_run` on any still-open
`current_run_id` (coercing a non-terminal `running` status to `failed`) before
resetting in-memory state. A chain spanning midnight does NOT hit this branch (the
session is unchanged until the next close), so it is no longer abandoned; the
branch now only fires for a chain genuinely interrupted across a real session
boundary. Tier-1 companion guard: av-ingestor reclaims a `running` `ingest_runs`
row older than `STALE_INGEST_HOURS` (default 6h) so an orphaned forever-`running`
fetch can't 409-wedge future runs.

**Manual run-now does NOT re-fetch data that is already ingested.** `/jobs/run-now`
puts every step in `_force_pending` (so any FAILED step gets one self-heal retry),
but `_NO_RERUN_WHEN_DONE = {"fetch-data"}` suppresses the *forced re-run of work
already finished for the target session*. Rationale: once the session's bars are in
the DB a re-ingest produces identical data at a cost of HOURS, whereas the strategy
segment (pipeline → vet → build → delta) is cheap and config-sensitive — re-running
it is the whole point of a manual run. `POST /jobs/run-now?refetch=true` opts back
into a genuine re-ingest (suspected bad/partial fetch). The refetch flag is NOT
persisted, so a restart mid-manual-run resumes with the safe default.

This closed a chain that could not advance (2026-07-27/28) in which two bugs
compounded: run-now restarted the fetch, and the fetch watchdog killed it before it
could finish. `fetch-data.max_running_minutes` is now
`FETCH_MAX_RUNNING_MINUTES` (default **480**, was a hardcoded 240). Fetch duration
is **bimodal**: a normal incremental evening is well under an hour, but on a
universe-refresh day the fresh LISTING_STATUS snapshot nulls every sector and the
per-ticker OVERVIEW backfill re-fetches thousands of fundamentals — measured 4h30m
(5900/5918 tickers, `partial_success`). The 240m limit was calibrated on normal days,
fired at the 4h mark, and coerced a fetch that succeeded 30 minutes later to
`failed`. A watchdog shorter than the slowest legitimate run IS the outage.

The pipeline service maintains a Redis consumer on `stocker:pipeline_events`
to drain the Pending Entries List on restart (recovering events that a crashed
instance claimed but never ACK'd). Events are ACK'd on receipt but do **not**
auto-trigger pipeline steps — the scheduler is the sole driver.

**Restart recovery via RESTART_ABORT_MARKER:**

`docker compose down` mid-chain must not wedge the chain until midnight.
Each persistence-using service (av-ingestor, pipeline, llm-vetter,
portfolio-builder) calls `mark_orphaned_runs_failed()` from
`shared.tracing` on startup. That helper marks orphaned `running` rows as
`failed` with `error_message` prefixed by `RESTART_ABORTED:`.

The scheduler's `_step_state` and the cold-start fetch-universe branch
both check for this prefix:

```text
status=failed, RESTART_ABORTED in error_message → return "idle"   (re-trigger)
status=failed, prefix absent                    → return "failed" (suspend chain)
```

`/runs/delta-latest` includes `error_message` in its SELECT so the
scheduler can apply the marker check to the standalone delta step too.

**Crash-loop breaker (MAX_RESTART_ABORT_RETRIES, default 3):** re-triggering a
RESTART_ABORTED orphan recovers a *transient* restart, but a *deterministic*
crash (e.g. the factor step OOM-killing on a RAM-constrained host) reproduces on
every retry — an infinite crash loop that shows as "stuck on calculating
factors". The supervisor counts distinct crash cycles per (step, run_date),
deduped by the orphaned run's `run_id` (unique per attempt, so re-seeing the SAME
orphan across fast ticks counts once, while each fresh re-triggered run — a new
run_id — is a new cycle; a NULL token counts anyway, over-counting toward the safe
"trip sooner" direction). The count is the DURABLE `_persist_restart_cycle` value
(the in-memory dict resets on the very restart an OOM triggers, so a memory-only
counter would re-arm from 0 and loop forever). It SUSPENDS the chain (returns
"failed") once the count exceeds the limit. A clean success clears the counter.
(The earlier `started_at`/`run_date` dedup token collapsed to `run_date` when
started_at was missing — identical every cycle — so the counter capped at 1 and
the breaker never tripped; `run_id` fixed that.) Paired with the pipeline's `mem_limit`
(PIPELINE_MEM_LIMIT, default 2g in docker-compose.yml): the cap makes the
pipeline the predictable OOM victim instead of postgres/redis, and the breaker
turns the resulting restart into one visible failure instead of a loop. The
factor step also offloads its universe-scale pandas/numpy to a worker thread
(`asyncio.to_thread`) and hands the price frame to `compute_all_factors(...,
copy_input=False)` so no second universe-scale copy is held at peak — both cut
the OOM probability at the source.

## api

Backend API for dashboard and control panel.

Should expose:

```text
health
current strategy
rankings
portfolio
signals
orders
backtest runs
config validation
system status
```

## dashboard

Simple web UI showing:

```text
current active strategy
ranked stocks
target portfolio
actual portfolio
intraday signals
risk decisions
orders
fills
backtests
logs
```

Dashboard should not directly execute trades.

It may request trade approval or show pending actions.

---

# LLM Boundary

Allowed LLM tasks:

```text
convert natural-language strategy prompt into structured config
explain rankings
summarize news
classify thematic exposure
suggest strategy changes
generate reports
explain trade signals
```

Not allowed:

```text
submit orders
bypass risk-service
change live config without validation
invent missing data
override safety limits
directly decide position sizing without deterministic checks
directly modify approved strategy registry
```

The LLM may suggest. Python validates and executes.

---

# Strategy Config Artifacts

Every useful prompt should produce versioned artifacts.

Recommended structure:

```text
strategies/
  quality_core_v1.yaml
  quality_ai_overlay_v1.yaml

prompts/
  quality_ai_overlay_v1.prompt.txt

backtests/
  quality_ai_overlay_v1_YYYY-MM-DD.json
```

The Git repo should be the source of truth for approved strategy configs.

Postgres stores runtime state and history.

---

# Example Strategy Config

The canonical example is in `strategies/quality_ai_overlay_v1.yaml`. The schema is defined in `shared/stock_strategy_shared/schemas/strategy.py` (Pydantic). Key structure:

```yaml
strategy_id: quality_core_v1
description: Balanced quality-momentum strategy with regime-dependent weights

universe:
  source: av_listing
  min_price: 5.0
  min_avg_dollar_volume_20d: 20000000

regime_detection:
  slow_sma: 200
  vol_window: 20
  vol_threshold: 0.20
  confirmation_days: 5
  regimes:
    bull_calm:   { spy_above_slow_sma: true,  vol_above_threshold: false }
    bull_stress: { spy_above_slow_sma: true,  vol_above_threshold: true  }
    bear_stress: { spy_above_slow_sma: false, vol_above_threshold: true  }
    bear_calm:   { spy_above_slow_sma: false, vol_above_threshold: false }

factor_weights:
  # Calibrated to academic literature — see docs/architecture.md for citation rationale.
  # All regimes include a liquidity factor not shown in this abbreviated example.
  bull_calm:   { momentum: 0.30, growth: 0.20, quality: 0.17, value: 0.12, liquidity: 0.11, low_volatility: 0.10 }
  bull_stress: { low_volatility: 0.24, quality: 0.23, value: 0.17, momentum: 0.16, liquidity: 0.10, growth: 0.10 }
  bear_stress: { low_volatility: 0.35, quality: 0.27, liquidity: 0.14, value: 0.10, growth: 0.07, momentum: 0.07 }
  bear_calm:   { value: 0.30, quality: 0.26, low_volatility: 0.18, momentum: 0.12, growth: 0.07, liquidity: 0.07 }

max_positions: 30
min_score_percentile: 0.0
min_non_null_factors: 3

portfolio_builder:
  method: greedy_score_per_port_vol
  max_positions: 30
  max_position_weight: 0.10
  max_sector_weight: 0.30
  weighting: equal_weight

vetter:
  candidate_count: 50
```

Factor weights for each regime must sum to 1.0. All four regime conditions must be covered.

Display-only indicators in `rankings.factor_scores` JSONB (NOT scoring factors,
NOT weighted in the rank): `drawdown_21d` (21-day peak-to-now), `beta` (120-day
OLS vs SPY, clipped [-1,3]), and `excess_dd_21d` + `idio_vol` (the beta-adjusted
falling-knife inputs the VETTER evaluates — `excess_dd = raw_dd − beta×SPY_move`
over the peak→now span, plus the annualized idiosyncratic/residual vol σ). All
computed in the pipeline rank step (`_drawdown_map_from_rows` / `_beta_map_from_rows`
/ `_excess_drawdown_map_from_rows`) and surfaced on the dashboard detail card
(`excess −7% @ σ28%` shown under the 21d drawdown). `excess_dd_21d` clamps beta to
the veto's CONSERVATIVE [0,3] (so the card preview matches what the falling-knife
veto computes), NOT the looser display-beta [-1,3] — so for a negatively-correlated
name the card's signed `beta` and the 0-floored beta behind `excess_dd_21d` differ
by design (the excess strips no market move when beta floors to 0 → excess = raw_dd).
The card preview shows the excess INPUTS (excess + σ) AND the per-ticker trigger
`excess_dd_limit` (rendered "excess -6% / limit -12% @ σ28%") so the user can see how
close a name is to the veto. `excess_dd_limit` is computed in the pipeline rank step
(`_excess_dd_limit`, mirroring the vetter's `scaled_excess_threshold` = base ×
σ/anchor clamped to [min,max]) and stored display-only in factor_scores. It reads the
SAME `DRAWDOWN_EXCESS_PCT/VOL_SCALING/VOL_ANCHOR/EXCESS_MIN/EXCESS_MAX` env as the
vetter — those vars are wired to BOTH the pipeline and llm-vetter services in
docker-compose (one .env, two consumers) so the displayed limit equals the vetter's
real trigger. The actual exclude/keep decision (and the flat 25% absolute raw-drawdown
floor) still come from the vetter.

The display beta floor is -1.0, NOT 0: a real market-decoupled name can have a
genuinely NEGATIVE realized beta. This was discovered when SU/EOG/VLO (an energy
bloc, ranks 1-3) all showed 0.00 — diagnosed (lag-correlation scan) NOT to be a
data/ingestion artifact: the three move together (corr ~0.72) but ran flat-to-
inverse vs SPY (corr ~-0.15 at every lag → no date shift), a true beta ~-0.3 that
the old 0-floor mislabeled as 0.00 / "broken". The display now shows the true
signed beta and clips only implausible outliers ([-1,3]; equities essentially never
sustain |beta|>3 or beta<-1 → data error). This is intentionally LOOSER than the
vetter's falling-knife β, which keeps a [0,3] clamp on purpose (conservative for
the excess-drawdown market-strip). So the screener card beta and the veto beta can
differ in sign for a negatively-correlated name — by design. (A consequence: the
weight-weighted target portfolio beta on the Target tab can run genuinely low /
sub-1 when the book is heavy on currently-decoupled sectors like energy — that is
real, not a bug.)

Regime factor-weight ROTATION is currently OFF (`regime_weighting_enabled: false`
in quality_core_v1.yaml). The regime is still detected (snapshots/dashboard) but no
longer changes the weights — a single `static_factor_weights` vector (the centroid
of the four calibrated regime vectors) is used in all regimes. Broad regime/factor
rotation is weakly supported out-of-sample and overfits (Asness; Cederburg et al.);
momentum-crash protection is provided independently by the vetter's beta-adjusted,
vol-scaled falling-knife veto. `StrategyConfig.effective_factor_weights(regime)` is
the single resolver (static when off, else `factor_weights[regime]`). Set
`regime_weighting_enabled: true` to restore rotation. See docs/architecture.md.

---

# Strategy Registry

Track approved strategy versions in Postgres.

Suggested fields:

```text
strategy_id
version
file_path
prompt_hash
config_hash
backtest_score
approval_status
created_at
active_from
active_until
paper_or_live
created_by
notes
```

The system should be able to answer:

```text
Which prompt created this strategy?
Which config generated this portfolio?
Which backtest approved this version?
Which signal caused this trade?
Which risk rule approved or rejected it?
```

---

# Build Approach

Start simple.

## Phase 1: Docker Compose Skeleton

Build:

```text
postgres
redis
api
dashboard
strategy-validator
shared Python schemas
health checks
.env.example
Makefile
pytest setup
README
```

No real Alpha Vantage or Alpaca calls yet.

## Phase 2: Strategy Schema and Validator

Build:

```text
strict Pydantic models
sample strategy configs
validation endpoint
unit tests
dangerous-config rejection tests
```

## Phase 3: Alpha Vantage Ingestor

Build:

```text
Alpha Vantage client skeleton
mock mode
rate-limit handling
sample ticker ingestion
Postgres storage
```

## Phase 4: Monthly Stock Engine

Build:

```text
factor-engine
ranker
portfolio-builder
sample ranking workflow
```

## Phase 5: Backtesting

Build:

```text
backtester
evaluator
backtest report artifacts
strategy comparison
```

## Phase 6: Alpaca Paper Trading

Build:

```text
alpaca-sync
intraday-monitor
risk-service
trade-executor
paper trading only
```

Do not implement live trading first.

---

# Testing

Use `pytest`.

Prioritize tests for:

```text
strategy-validator
risk-service
factor-engine
ranker
backtester
intraday-monitor
```

Every service should have:

```text
health endpoint
unit tests
clear README
typed Pydantic models where useful
```

**`/health` is a LIVENESS probe — it must never perform external I/O.** It is the
container healthcheck's target (5s timeout, 5 retries past a 20s start_period)
and other services gate startup on the result, so a `/health` that calls a
dependency reports someone else's outage as its own death and can blow the probe
budget while the service is perfectly fine. Put dependency probes on a separate
path (`/health/providers` on llm-gateway, `/health/gateway` on llm-vetter).

This is not hypothetical: llm-gateway's `/health` awaited a provider health_check
against `ollama` — a host that does not exist unless `--profile ollama` is up —
with a 5.0s inner timeout against the healthcheck's own 5s. Cold deploys
intermittently died with `dependency failed to start: container
stocker-llm-gateway-1 is unhealthy` → `live stack FAILED (rc=1)`, and a second
`docker compose up -d` always "fixed" it (warm DNS returns NXDOMAIN instantly).
llm-vetter had the same bug one level up, calling the gateway's `/health` from
its own. Enforced by `tests/contracts/test_health_is_liveness_only.py`, which
scans EVERY service — the marker list plus a stricter "no `await` at all" rule,
because the gateway's offending call went through an abstraction and the markers
alone missed it.

Related: prefer `condition: service_started` over `service_healthy` for
depends_on edges on optional/degradable services. `depends_on` only orders
STARTUP, so neither side can assume the other is reachable later anyway;
`service_healthy` on a non-essential dependency just converts a degraded feature
into a failed deploy. See docs/architecture.md "container healthchecks probe
LIVENESS, never dependencies".

Important test categories:

```text
valid strategy config passes
invalid strategy config fails
unsafe risk limits are rejected
LLM-generated unknown fields are rejected
factor calculations are deterministic
rankings are reproducible
backtest output is reproducible
risk-service blocks unsafe trades
trade-executor cannot run without risk approval
image-layout import smoke: services whose images assemble code via build-time
  COPY (bt-engine, backtester, evaluator, …) must `import app.main` under the
  IMAGE's directory layout, not just the checkout's (tests/smoke/ — CI twin of
  scripts/smoke-image-imports.sh, which checks the real built images)
```

---

# Coding Style

Use:

```text
Python 3.12
FastAPI for service APIs
Pydantic for schemas
pytest for tests
Postgres for durable storage
Redis for queues/cache/locks
Docker Compose for local orchestration
```

Keep services small and clear.

Prefer explicit schemas and typed models.

Avoid clever abstractions early.

Do not add unnecessary dependencies.

---

# Repo Structure

```text
stocker/
  CLAUDE.md
  README.md
  .env.example
  docker-compose.yml
  Makefile

  docs/
    architecture.md
    service-boundaries.md
    llm-boundaries.md
    risk-safety-rules.md
    data-sources.md
    build-phases.md
    testing.md

  strategies/
    quality_ai_overlay_v1.yaml

  shared/
    pyproject.toml
    stock_strategy_shared/
      schemas/
        strategy.py      ← StrategyConfig, RegimeDetectionConfig, FactorWeights, etc.
      order_status.py    ← canonical alpaca_orders.status tokens (single source)
      strategy_engine/   ← THE canonical rank.py + select.py (audit #3): pipeline,
                           portfolio-builder, backtester, evaluator, bt-engine all
                           import THIS; their local rank/select files are re-export
                           shims (sys.modules replacement — one module object).
                           NEW shared module dir ⇒ deploys touching it need
                           `docker build --network host -t stocker-base:latest -f Dockerfile.base .` FIRST.
      broker/            ← BrokerAdapter abstraction (one active broker per deploy,
                           BROKER env; AlpacaBrokerAdapter built; IBKRBrokerAdapter
                           BUILT but DORMANT — activation needs BROKER=ibkr + the
                           --profile ibkr ibeam sidecar + IBKR_* env + the
                           pre-activation checklist in service-boundaries.md).
                           See docs/service-boundaries.md "Broker abstraction".

  services/
    api/                 ← built: health, universe, rankings, portfolio, regime, live-portfolio
    strategy-validator/  ← built: /validate endpoint
    av-ingestor/         ← built: fetch-universe, fetch-data, incremental price ingestion
    factor-engine/       ← built: momentum, quality, value, growth, low_vol, beta, liquidity
    ranker/              ← built: regime detection, factor weighting, scoring, ranking runs
    portfolio-builder/   ← built: greedy_score_per_port_vol, sector caps, vetter exclusions
    llm-vetter/          ← built: Tavily + Ollama/OpenAI vetting; mandatory chain step, exclusions binding
    delta-engine/        ← built: buffer-zone entry/exit evaluation, produces delta_intents
    dashboard/           ← built: universe/rank/vetter/portfolio/live/trade-proposal tabs
    alpaca-sync/         ← built: GET /v2/account, GET /v2/positions, GET /v2/orders (read-only reconcile); writes alpaca_sync_runs + live_positions
    risk-service/        ← built: deterministic /check (kill switch, paper guard, notional limit)
    trade-executor/      ← built: only service permitted to submit Alpaca orders; writes alpaca_orders
    scheduler/           ← built: daily chain + startup catch-up
    backtester/          ← built: replays portfolio_runs against forward daily_prices
    bt-data/             ← built: Sharadar SEP/SF1 fetcher for the SEPARATE backtest
                           machine (docker-compose.backtest.yml, own bt-postgres —
                           never in the live compose). Point-in-time fundamentals.
                           SF1 also supplies market_cap + shares_outstanding
                           (→ small_cap / issuance) and bt_earnings (per-filing
                           EPS, populated but NOT yet consumed) — see the factor-
                           coverage contract below.
    bt-engine/           ← built: day-stepping strategy simulator reusing the LIVE
                           factor/rank/select/delta modules (COPYied at image build —
                           zero drift); deterministic, truncation-proven no-look-ahead.
                           Also hosts the Phase-5 WALK-FORWARD PARAMETER SWEEP
                           (POST /sweeps/run: deterministic grid, seeded sampling,
                           mandatory out-of-sample validate window, leaderboard by
                           OOS Sharpe with overfit_gap). No AI in the loop.
                           Enforces the FACTOR-COVERAGE CONTRACT (app/coverage.py):
                           it REFUSES (422) any config weighting a factor it cannot
                           compute, instead of letting composite_scores renormalize
                           the weight away and silently score a different strategy.
                           See docs/backtester-v2-plan.md.
    llm-gateway/         ← partially built: provider abstraction skeleton

    intraday-monitor/    ← not yet built
    evaluator/           ← built: weekly LLM strategy review (packet + Opus report + Review tab)
    strategy-config-service/ ← not yet built

  tests/
    av_ingestor/
    dashboard/
    llm_vetter/
    portfolio_builder/
    shared/
```

---

# Safety Rules

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

Use `.env.example` for environment variable names.

Never commit real API keys.

---

# Final Design Principle

The system is not an LLM that trades.

It is:

```text
Prompt-driven strategy design
  + deterministic Python execution
  + strict validation
  + backtesting
  + risk gates
  + audited Alpaca execution
```

Preserve this boundary throughout the codebase.
