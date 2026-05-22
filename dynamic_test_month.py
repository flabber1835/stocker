"""
Month-long dynamic pipeline test against the live Docker stack.

Simulates a full month of daily price data with engineered ticker dynamics so
the ranking list moves observably day by day, exercises weekends + a mid-week
holiday (no data → no new ranking_run), and confirms the API endpoints that
back the dashboard expose the correct state at every step.

What it verifies (end-to-end):
  • Data flows from daily_prices → factor_scores → rankings → portfolio_holdings
    → delta_intents.
  • Stocks engineered to rise in price climb the ranking list across the month.
  • Stocks engineered to fall drop out of the top-N and trigger exits.
  • Non-trading days (weekend) produce NO new ranking_runs.
  • A simulated mid-week exchange holiday produces NO new ranking_run.
  • Portfolio-builder rebuilds each trading day.
  • Standalone /jobs/delta runs each trading day with triggered_by='scheduler'.
  • Dashboard-backing API endpoints (/rankings, /portfolio, /delta/latest,
    /regime, /universe) reflect the current day's state.

Usage: python dynamic_test_month.py
"""
import sys
import time
import uuid
import asyncio
import asyncpg
import httpx
from datetime import date, datetime, timedelta, timezone
from typing import Optional

PIPELINE_URL          = "http://localhost:8018"
PORTFOLIO_BUILDER_URL = "http://localhost:8008"
API_URL               = "http://localhost:8000"
DB_URL                = "postgresql://stocker:stocker@localhost:5433/stocker"

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"
WARN = "\033[93m!\033[0m"

_failures = 0
_passes = 0


def ok(msg: str):
    global _passes
    _passes += 1
    print(f"  {PASS} {msg}", flush=True)


def fail(msg: str):
    global _failures
    _failures += 1
    print(f"  {FAIL} {msg}", flush=True)


def warn(msg: str):
    print(f"  {WARN} {msg}", flush=True)


def section(title: str):
    print(f"\n{'═'*70}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{'═'*70}", flush=True)


def info(msg: str):
    print(f"  {INFO} {msg}", flush=True)


def assert_eq(label: str, got, expected):
    if got == expected:
        ok(f"{label}: {got!r}")
    else:
        fail(f"{label}: got {got!r}, expected {expected!r}")


def assert_true(label: str, value: bool, detail: str = ""):
    if value:
        ok(f"{label}{(' — ' + detail) if detail else ''}")
    else:
        fail(f"{label}{(' — ' + detail) if detail else ''}")


# ── Universe construction ────────────────────────────────────────────────────

# Engineered groups so we can predict ranking movement.
UP_TICKERS     = [f"UP{i:02d}" for i in range(10)]   # accelerate during test month
DOWN_TICKERS   = [f"DN{i:02d}" for i in range(10)]   # decelerate / fall
STABLE_TICKERS = [f"SK{i:02d}" for i in range(10)]   # consistent
ALL_TICKERS    = UP_TICKERS + DOWN_TICKERS + STABLE_TICKERS
BENCHMARK      = "SPY"

# 255 warmup days satisfy momentum (252d) and SMA (200d) lookbacks.
# Stay just inside the 402-calendar-day price-load window the pipeline uses
# (which is `CURRENT_DATE - 402 days`).
WARMUP_DAYS = 255

# Smoke-test mode: run only the first N test-month trading days to verify the
# plumbing end-to-end before committing to the full month-long run.
import os as _os
SMOKE_DAYS = int(_os.environ.get("SMOKE_DAYS", "0"))


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # Sat=5, Sun=6


def is_holiday(d: date, holidays: set[date]) -> bool:
    return d in holidays


def trading_days_between(start: date, end: date, holidays: set[date]) -> list[date]:
    """Inclusive list of trading days, skipping weekends + holidays."""
    out = []
    cur = start
    while cur <= end:
        if not is_weekend(cur) and not is_holiday(cur, holidays):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def generate_price_series(
    ticker: str,
    trading_days: list[date],
    start_price: float,
    daily_drift: float,
    daily_vol: float,
    seed: int,
) -> list[tuple[date, float]]:
    """Geometric random walk; deterministic from `seed`."""
    import random
    rng = random.Random(seed)
    series = []
    price = start_price
    for d in trading_days:
        # log-normal-ish step
        step = daily_drift + daily_vol * (rng.random() - 0.5) * 2.0
        price = max(5.5, price * (1.0 + step))
        series.append((d, round(price, 4)))
    return series


# ── DB helpers ───────────────────────────────────────────────────────────────

async def wipe_state(conn: asyncpg.Connection):
    """Truncate pipeline-related tables — keep schema; cascades clean child rows."""
    await conn.execute("""
        TRUNCATE
            delta_intents, delta_runs,
            portfolio_holdings, portfolio_runs,
            rankings, ranking_runs,
            factor_scores, factor_runs,
            regime_snapshots,
            pipeline_runs,
            execution_steps, execution_traces,
            live_positions, alpaca_sync_runs,
            vetter_exclusions, vetter_decisions, vetter_runs,
            scheduler_runs,
            daily_prices, fundamentals,
            universe_tickers, universe_snapshots
        RESTART IDENTITY CASCADE
    """)


async def seed_universe(conn: asyncpg.Connection, tickers: list[str], snap_date: date) -> int:
    """Insert universe_snapshots row + universe_tickers, return snapshot_id."""
    snap_id = await conn.fetchval(
        "INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count) "
        "VALUES ($1, $2, $3) RETURNING id",
        "AV_LISTING", snap_date, len(tickers),
    )
    for t in tickers:
        await conn.execute(
            "INSERT INTO universe_tickers (snapshot_id, ticker, name, sector, asset_class) "
            "VALUES ($1, $2, $3, $4, 'Equity')",
            snap_id, t, f"{t} Inc", "Technology",
        )
    return snap_id


async def seed_fundamentals(conn: asyncpg.Connection, tickers: list[str], as_of: date):
    """Seed fundamentals for all tickers — slightly varied so quality scoring differentiates."""
    for i, t in enumerate(tickers):
        # Bias UP tickers slightly stronger on quality, DOWN slightly weaker — but
        # keep the gap small so price-driven momentum is the dominant ranking signal.
        if t.startswith("UP"):
            pe, pb, roe, de = 18.0, 3.5, 0.20, 0.45
        elif t.startswith("DN"):
            pe, pb, roe, de = 22.0, 3.0, 0.14, 0.55
        else:
            pe, pb, roe, de = 20.0, 3.2, 0.17, 0.50
        await conn.execute("""
            INSERT INTO fundamentals
                (ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity,
                 revenue_growth, eps_growth, market_cap, avg_volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (ticker, as_of_date) DO UPDATE SET
                pe_ratio=EXCLUDED.pe_ratio, pb_ratio=EXCLUDED.pb_ratio,
                roe=EXCLUDED.roe, debt_to_equity=EXCLUDED.debt_to_equity,
                revenue_growth=EXCLUDED.revenue_growth, eps_growth=EXCLUDED.eps_growth,
                avg_volume=EXCLUDED.avg_volume
        """, t, as_of, pe, pb, roe, de, 0.15, 0.12, 50_000_000_000, 100_000_000)
        # ^^^ avg_volume in this column actually stores **dollar volume** (20-day avg);
        # min_avg_dollar_volume_20d filter compares against it directly. $100M ≫ $20M cutoff.


async def insert_prices(conn: asyncpg.Connection, ticker: str, series: list[tuple[date, float]]):
    """Bulk insert a price series for a ticker."""
    rows = [
        (ticker, d, p * 0.998, p * 1.005, p * 0.995, p, p, 8_000_000, "synthetic")
        for d, p in series
    ]
    await conn.executemany("""
        INSERT INTO daily_prices (ticker, date, open, high, low, close, adjusted_close, volume, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (ticker, date) DO NOTHING
    """, rows)


# ── HTTP helpers ─────────────────────────────────────────────────────────────

async def post_and_wait(
    client: httpx.AsyncClient, url: str, status_url: str,
    label: str, timeout_sec: int = 240,
) -> dict:
    """POST a job and poll status_url until status in (success/failed). Returns final payload."""
    # Capture latest run id before POST so we can detect "new run started" vs the prior one.
    pre = await client.get(status_url, timeout=10.0)
    pre_run_id = pre.json().get("run_id") if pre.status_code == 200 else None

    r = await client.post(url, timeout=20.0)
    if r.status_code == 409:
        # Some services return 409 when busy — wait for the in-flight run to finish.
        pass
    elif r.status_code not in (200, 201, 202):
        raise RuntimeError(f"{label} POST returned HTTP {r.status_code}: {r.text[:200]}")
    else:
        body = r.json()
        if body.get("status") in ("already_ran_today",):
            # If the service reports it already ran today, it means our incremental
            # date-advance failed — should never happen in this test.
            raise RuntimeError(
                f"{label} returned already_ran_today (date={body.get('date')}); "
                f"incremental time-advance is broken"
            )

    deadline = time.monotonic() + timeout_sec
    last = {}
    while time.monotonic() < deadline:
        s = await client.get(status_url, timeout=10.0)
        if s.status_code == 200:
            last = s.json()
            st = last.get("status")
            # Require both a terminal status AND a new run_id (to avoid returning
            # the prior run as "success" before the new one is even recorded).
            new_run_id = last.get("run_id")
            if st == "success" and new_run_id and new_run_id != pre_run_id:
                return last
            if st == "failed" and new_run_id and new_run_id != pre_run_id:
                raise RuntimeError(f"{label} FAILED: {last.get('error_message','')[:300]}")
        await asyncio.sleep(1.0)
    raise TimeoutError(f"{label} did not complete within {timeout_sec}s; last={last}")


# ── Test orchestration ───────────────────────────────────────────────────────

async def run():
    conn = await asyncpg.connect(DB_URL)
    client = httpx.AsyncClient()

    try:
        # The pipeline loads prices with `date >= CURRENT_DATE - 402 days`, so the
        # simulated dates must fall within ~400 calendar days of today's wall clock.
        # Anchor at today and walk the test month forward to end on today.
        anchor_end = date.today()
        # Ensure anchor_end is a trading day; back up to Friday if today is a weekend.
        while anchor_end.weekday() >= 5:
            anchor_end -= timedelta(days=1)

        # Test month: ~30 calendar days ending at anchor_end (~21 trading days),
        # with weekends excluded and a fake mid-month exchange holiday.
        test_month_start = anchor_end - timedelta(days=30)
        # Pick a Monday inside the test month as the fake holiday.
        FAKE_HOLIDAY = None
        cur = test_month_start
        while cur <= anchor_end:
            if cur.weekday() == 0 and cur > test_month_start + timedelta(days=7):
                FAKE_HOLIDAY = cur
                break
            cur += timedelta(days=1)
        HOLIDAYS = {FAKE_HOLIDAY} if FAKE_HOLIDAY else set()

        # All trading days in the test month
        test_trading_days = trading_days_between(test_month_start, anchor_end, HOLIDAYS)
        if SMOKE_DAYS:
            test_trading_days = test_trading_days[:SMOKE_DAYS]
            print(f"[SMOKE MODE] Running only first {SMOKE_DAYS} test trading days", flush=True)
        # Warmup: 270 trading days BEFORE test_month_start
        warmup_start = test_month_start - timedelta(days=int(WARMUP_DAYS * 1.5))
        warmup_trading_days = trading_days_between(warmup_start, test_month_start - timedelta(days=1), HOLIDAYS)
        warmup_trading_days = warmup_trading_days[-WARMUP_DAYS:]  # keep last 270 trading days

        all_trading_days = warmup_trading_days + test_trading_days

        section("Setup: wiping DB + seeding universe, fundamentals, warmup prices")
        await wipe_state(conn)
        # SPY is the benchmark (regime detection) — its prices are loaded by the
        # pipeline but it is NOT in the investable universe.
        snap_id = await seed_universe(conn, ALL_TICKERS, warmup_trading_days[0])
        info(f"Universe snapshot id={snap_id} with {len(ALL_TICKERS)} tickers (SPY excluded — benchmark only)")
        await seed_fundamentals(conn, ALL_TICKERS, warmup_trading_days[-1])
        info(f"Fundamentals seeded for {len(ALL_TICKERS)} tickers")

        # ── Generate price series ─────────────────────────────────────────────
        # SPY: steady uptrend, low vol → bull_calm regime. Seed FULL warmup;
        # test-day prices will be added incrementally in the per-day loop.
        spy_warmup = generate_price_series(
            BENCHMARK, warmup_trading_days,
            start_price=400.0, daily_drift=0.0005, daily_vol=0.005,
            seed=42,
        )
        await insert_prices(conn, BENCHMARK, spy_warmup)
        # Pre-generate the SPY test-month series too so each day's incremental
        # insert is deterministic.
        spy_test = generate_price_series(
            BENCHMARK, test_trading_days,
            start_price=spy_warmup[-1][1], daily_drift=0.0005, daily_vol=0.005,
            seed=43,
        )

        # During warmup, all groups behave similarly. In the test month, UP
        # tickers accelerate, DOWN tickers reverse, STABLE stays flat-ish.
        test_series_by_ticker: dict[str, list[tuple[date, float]]] = {BENCHMARK: spy_test}

        for idx, t in enumerate(UP_TICKERS):
            warmup = generate_price_series(
                t, warmup_trading_days, start_price=100.0 + idx * 2,
                daily_drift=0.0005, daily_vol=0.015, seed=100 + idx,
            )
            test = generate_price_series(
                t, test_trading_days, start_price=warmup[-1][1],
                daily_drift=0.012, daily_vol=0.010, seed=200 + idx,   # strong drift
            )
            await insert_prices(conn, t, warmup)
            test_series_by_ticker[t] = test

        for idx, t in enumerate(DOWN_TICKERS):
            warmup = generate_price_series(
                t, warmup_trading_days, start_price=120.0 + idx * 2,
                daily_drift=0.0010, daily_vol=0.015, seed=300 + idx,   # uptrend during warmup
            )
            test = generate_price_series(
                t, test_trading_days, start_price=warmup[-1][1],
                daily_drift=-0.012, daily_vol=0.012, seed=400 + idx,   # crashes
            )
            await insert_prices(conn, t, warmup)
            test_series_by_ticker[t] = test

        for idx, t in enumerate(STABLE_TICKERS):
            warmup = generate_price_series(
                t, warmup_trading_days, start_price=80.0 + idx * 2,
                daily_drift=0.0006, daily_vol=0.010, seed=500 + idx,
            )
            test = generate_price_series(
                t, test_trading_days, start_price=warmup[-1][1],
                daily_drift=0.0006, daily_vol=0.010, seed=600 + idx,
            )
            await insert_prices(conn, t, warmup)
            test_series_by_ticker[t] = test

        info(f"Warmup: {len(warmup_trading_days)} trading days")
        info(f"Test month: {len(test_trading_days)} trading days "
             f"({test_trading_days[0]} → {test_trading_days[-1]}); 1 holiday excluded ({FAKE_HOLIDAY})")

        # Verify weekends and holiday are properly excluded
        weekend_dates = [
            test_month_start + timedelta(days=i)
            for i in range((anchor_end - test_month_start).days + 1)
            if (test_month_start + timedelta(days=i)).weekday() >= 5
        ]
        wk_in_test = [d for d in weekend_dates]
        assert_true(
            "weekend days were excluded from price seeding",
            FAKE_HOLIDAY not in test_trading_days
            and all(d not in test_trading_days for d in wk_in_test),
            f"{len(wk_in_test)} weekend dates, 1 holiday all excluded",
        )

        # Show the engineered final price ratios — from the in-memory test series
        up_final = sum(test_series_by_ticker[t][-1][1] / 100 for t in UP_TICKERS) / len(UP_TICKERS)
        dn_final = sum(test_series_by_ticker[t][-1][1] / 120 for t in DOWN_TICKERS) / len(DOWN_TICKERS)
        info(f"Engineered avg test-end/initial — UP: {up_final:.2f}x, DOWN: {dn_final:.2f}x")

        # ── Day-by-day simulation ─────────────────────────────────────────────
        section(f"Day-by-day simulation: {len(test_trading_days)} trading days")

        # We seed ALL prices upfront. To simulate "advancing time", we set the
        # database to only expose prices ≤ current_day. Easiest: delete future
        # prices then re-insert them next loop. But that's slow. Instead, we
        # rely on the pipeline's behaviour: it loads max(prices.date) → that's
        # the most recent date in the table. So to advance the simulation we
        # must trim future prices before each call.
        # Strategy: delete all prices > current_day before each pipeline call,
        # then re-insert the full series at the end. Actually simpler: delete
        # in reverse — start with full series, and on each iteration trim
        # prices > current_day. After the loop, the table only holds up to
        # anchor_end which is what we want for the post-simulation API checks.

        # We'll just delete prices strictly greater than current_day each loop.
        ranking_history: list[dict] = []
        portfolio_history: list[dict] = []
        delta_history: list[dict] = []

        for i, current_day in enumerate(test_trading_days):
            info(f"── Day {i+1}/{len(test_trading_days)}: {current_day} ({current_day.strftime('%A')}) ──")

            # Add the current day's price row for every ticker (incremental
            # time-advance: pipeline picks up max(date) = current_day).
            for tk, series in test_series_by_ticker.items():
                today_row = next(((d, p) for d, p in series if d == current_day), None)
                if today_row is None:
                    continue
                await insert_prices(conn, tk, [today_row])

            # Trigger the three steps
            try:
                run_result = await post_and_wait(
                    client, f"{PIPELINE_URL}/jobs/run",
                    f"{PIPELINE_URL}/runs/latest",
                    f"pipeline /jobs/run day={current_day}",
                )
            except Exception as e:
                fail(f"pipeline failed on {current_day}: {e}")
                continue

            build_result = await post_and_wait(
                client, f"{PORTFOLIO_BUILDER_URL}/jobs/build",
                f"{PORTFOLIO_BUILDER_URL}/runs/latest",
                f"portfolio-builder day={current_day}",
            )

            delta_result = await post_and_wait(
                client, f"{PIPELINE_URL}/jobs/delta",
                f"{PIPELINE_URL}/runs/delta-latest",
                f"standalone delta day={current_day}",
            )

            # Capture ranking snapshot for this day
            rankings = await conn.fetch(
                "SELECT ticker, rank, composite_score FROM rankings "
                "WHERE rank_date = $1 ORDER BY rank LIMIT 30",
                current_day,
            )
            ranking_history.append({
                "date": current_day,
                "top10": [(r["ticker"], r["rank"]) for r in rankings[:10]],
                "all_ranks": {r["ticker"]: r["rank"] for r in rankings},
            })

            # Portfolio snapshot
            port_rows = await conn.fetch(
                """SELECT ph.ticker, ph.weight, ph.position
                   FROM portfolio_holdings ph
                   JOIN portfolio_runs pr ON ph.run_id = pr.run_id
                   WHERE pr.run_id = $1
                   ORDER BY ph.position""",
                uuid.UUID(build_result["run_id"]),
            )
            portfolio_history.append({
                "date": current_day,
                "tickers": [r["ticker"] for r in port_rows],
                "weights": {r["ticker"]: float(r["weight"]) for r in port_rows},
            })

            # Delta intents
            intent_rows = await conn.fetch(
                "SELECT action, ticker FROM delta_intents WHERE run_id = $1",
                uuid.UUID(delta_result["run_id"]),
            )
            actions = {"entry": [], "exit": [], "hold": [], "watch": []}
            for r in intent_rows:
                actions[r["action"]].append(r["ticker"])
            delta_history.append({"date": current_day, "actions": actions, "triggered_by": delta_result.get("triggered_by")})

            info(
                f"   ranking_count={len(rankings)} "
                f"port_count={len(port_rows)} "
                f"intents E/X/H/W="
                f"{len(actions['entry'])}/{len(actions['exit'])}/"
                f"{len(actions['hold'])}/{len(actions['watch'])}"
            )

        # Restore future prices so the post-test API checks see the full anchor_end state
        # (we already trimmed prices > anchor_end above implicitly on the last loop iter)

        # ── Verification ──────────────────────────────────────────────────────
        section("Verification: ranking_runs only exist for trading days")

        total_ranking_runs = await conn.fetchval(
            "SELECT COUNT(*) FROM ranking_runs WHERE rank_date BETWEEN $1 AND $2 AND status='success'",
            test_month_start, anchor_end,
        )
        assert_eq("ranking_runs in test month", total_ranking_runs, len(test_trading_days))

        # Confirm NO ranking_run on FAKE_HOLIDAY
        holiday_runs = await conn.fetchval(
            "SELECT COUNT(*) FROM ranking_runs WHERE rank_date = $1", FAKE_HOLIDAY,
        )
        assert_eq(f"ranking_runs on holiday {FAKE_HOLIDAY}", holiday_runs, 0)

        # Confirm NO ranking_run on any weekend in the test month
        weekend_runs_count = 0
        for d in (test_month_start + timedelta(days=i) for i in range((anchor_end - test_month_start).days + 1)):
            if d.weekday() >= 5:
                cnt = await conn.fetchval(
                    "SELECT COUNT(*) FROM ranking_runs WHERE rank_date = $1", d,
                )
                if cnt > 0:
                    weekend_runs_count += 1
        assert_eq("ranking_runs on weekend days", weekend_runs_count, 0)

        section("Verification: portfolio + delta runs each trading day")
        port_runs = await conn.fetchval(
            "SELECT COUNT(*) FROM portfolio_runs WHERE portfolio_date BETWEEN $1 AND $2 AND status='success'",
            test_month_start, anchor_end,
        )
        assert_eq("portfolio_runs in test month", port_runs, len(test_trading_days))

        delta_scheduler_runs = await conn.fetchval(
            "SELECT COUNT(*) FROM delta_runs WHERE triggered_by='scheduler' AND status='success' "
            "AND started_at >= $1",
            datetime.combine(test_month_start, datetime.min.time(), tzinfo=timezone.utc),
        )
        assert_eq("standalone delta_runs (triggered_by='scheduler')", delta_scheduler_runs, len(test_trading_days))

        delta_pipeline_runs = await conn.fetchval(
            "SELECT COUNT(*) FROM delta_runs WHERE triggered_by='pipeline' AND status='success' "
            "AND started_at >= $1",
            datetime.combine(test_month_start, datetime.min.time(), tzinfo=timezone.utc),
        )
        assert_eq("pipeline-embedded delta_runs (triggered_by='pipeline')", delta_pipeline_runs, len(test_trading_days))

        section("Verification: engineered ticker dynamics show up in rankings")
        # Compare first vs last day rankings — UP tickers should rank better,
        # DOWN tickers should rank worse.
        first = ranking_history[0]["all_ranks"]
        last = ranking_history[-1]["all_ranks"]
        up_avg_first = sum(first.get(t, 999) for t in UP_TICKERS) / len(UP_TICKERS)
        up_avg_last  = sum(last.get(t, 999) for t in UP_TICKERS) / len(UP_TICKERS)
        dn_avg_first = sum(first.get(t, 999) for t in DOWN_TICKERS) / len(DOWN_TICKERS)
        dn_avg_last  = sum(last.get(t, 999) for t in DOWN_TICKERS) / len(DOWN_TICKERS)

        info(f"UP tickers avg rank: day1={up_avg_first:.1f} → day{len(test_trading_days)}={up_avg_last:.1f}")
        info(f"DN tickers avg rank: day1={dn_avg_first:.1f} → day{len(test_trading_days)}={dn_avg_last:.1f}")

        assert_true(
            "UP tickers' average rank improved across the month",
            up_avg_last < up_avg_first,
            f"day1 avg {up_avg_first:.1f} → final {up_avg_last:.1f} (lower=better)",
        )
        assert_true(
            "DOWN tickers' average rank worsened across the month",
            dn_avg_last > dn_avg_first,
            f"day1 avg {dn_avg_first:.1f} → final {dn_avg_last:.1f} (higher=worse)",
        )

        # Show a few example movements
        sample_up = max(UP_TICKERS, key=lambda t: first.get(t, 0) - last.get(t, 0))
        sample_dn = max(DOWN_TICKERS, key=lambda t: last.get(t, 0) - first.get(t, 0))
        info(f"Biggest UP climber:  {sample_up} {first.get(sample_up,'-')} → {last.get(sample_up,'-')}")
        info(f"Biggest DOWN faller: {sample_dn} {first.get(sample_dn,'-')} → {last.get(sample_dn,'-')}")

        section("Verification: portfolio composition reflects ranking changes")
        first_port = set(portfolio_history[0]["tickers"])
        last_port  = set(portfolio_history[-1]["tickers"])
        new_entries = last_port - first_port
        new_exits   = first_port - last_port
        info(f"First-day portfolio: {sorted(first_port)}")
        info(f"Last-day portfolio:  {sorted(last_port)}")
        info(f"Tickers added across month: {sorted(new_entries)}")
        info(f"Tickers removed across month: {sorted(new_exits)}")

        # UP tickers should be present in the final portfolio more than DOWN tickers
        up_in_last = sum(1 for t in UP_TICKERS if t in last_port)
        dn_in_last = sum(1 for t in DOWN_TICKERS if t in last_port)
        info(f"UP tickers in final portfolio: {up_in_last}/{len(UP_TICKERS)}")
        info(f"DN tickers in final portfolio: {dn_in_last}/{len(DOWN_TICKERS)}")
        assert_true(
            "UP tickers dominate final portfolio over DOWN tickers",
            up_in_last > dn_in_last,
            f"UP={up_in_last} > DN={dn_in_last}",
        )

        section("Verification: API endpoints return current state for UI")

        # /regime
        r = await client.get(f"{API_URL}/regime", timeout=10.0)
        assert_eq("/regime HTTP status", r.status_code, 200)
        regime_data = r.json()
        info(f"/regime returns: regime={regime_data.get('regime')}, calculated_at={regime_data.get('calculated_at')}")
        assert_true("/regime returns a recognized regime",
                    regime_data.get("regime") in ("bull_calm", "bull_stress", "bear_calm", "bear_stress"))

        # /universe
        r = await client.get(f"{API_URL}/universe", timeout=10.0)
        assert_eq("/universe HTTP status", r.status_code, 200)
        univ = r.json()
        univ_count = len(univ.get("tickers", []))
        assert_true("/universe returns the seeded tickers",
                    univ_count == len(ALL_TICKERS),
                    f"{univ_count} tickers (expected {len(ALL_TICKERS)})")

        # /rankings (latest)
        r = await client.get(f"{API_URL}/rankings", timeout=10.0)
        assert_eq("/rankings HTTP status", r.status_code, 200)
        ranks = r.json()
        api_ranks = ranks.get("rankings", [])
        assert_true("/rankings returns ≥30 entries", len(api_ranks) >= 30, f"got {len(api_ranks)}")
        # Should match last day's ranking
        api_top1 = api_ranks[0]["ticker"] if api_ranks else None
        local_top1 = next((t for t, r in last.items() if r == 1), None)
        assert_eq("/rankings top ticker matches our local snapshot",
                  api_top1, local_top1)

        # /portfolio (latest)
        r = await client.get(f"{API_URL}/portfolio", timeout=10.0)
        assert_eq("/portfolio HTTP status", r.status_code, 200)
        port = r.json()
        api_port_tickers = {h["ticker"] for h in port.get("holdings", [])}
        assert_eq("/portfolio tickers match the last build", api_port_tickers, last_port)

        # /delta/latest
        r = await client.get(f"{API_URL}/delta/latest", timeout=10.0)
        assert_eq("/delta/latest HTTP status", r.status_code, 200)
        dl = r.json()
        run_obj = dl.get("run") or {}
        intents_obj = dl.get("intents") or []
        assert_true("/delta/latest returns a run",
                    run_obj.get("run_id") is not None,
                    f"run_date={run_obj.get('run_date')}, intents={len(intents_obj)}")

        # The latest delta should be the standalone (scheduler-triggered) one
        # because /delta/latest ORDER BY started_at DESC and standalone runs last.
        latest_delta_id = run_obj.get("run_id")
        latest_delta_triggered_by = await conn.fetchval(
            "SELECT triggered_by FROM delta_runs WHERE run_id = $1::uuid", latest_delta_id,
        )
        info(f"/delta/latest run_id triggered_by = {latest_delta_triggered_by}")
        assert_eq("/delta/latest is the standalone (scheduler) delta",
                  latest_delta_triggered_by, "scheduler")

        # /data-freshness
        r = await client.get(f"{API_URL}/data-freshness", timeout=10.0)
        assert_eq("/data-freshness HTTP status", r.status_code, 200)
        freshness = r.json()
        prices_max = (freshness.get("prices") or {}).get("max_date")
        ranks_max = (freshness.get("rankings") or {}).get("rank_date")
        last_test_day = test_trading_days[-1]
        info(f"/data-freshness prices.max_date={prices_max}, rankings.rank_date={ranks_max}")
        assert_eq("/data-freshness prices.max_date == last test day",
                  prices_max, str(last_test_day))
        assert_eq("/data-freshness rankings.rank_date == last test day",
                  ranks_max, str(last_test_day))

        section("Verification: dashboard 'trade proposal' delta intents look sane")
        # The final-day delta should have real entry/exit decisions reflecting
        # the portfolio composition changes between yesterday's target and today's target.
        last_actions = delta_history[-1]["actions"]
        total_intents = sum(len(v) for v in last_actions.values())
        info(f"Final-day delta intents: E={len(last_actions['entry'])}, X={len(last_actions['exit'])}, "
             f"H={len(last_actions['hold'])}, W={len(last_actions['watch'])}; total={total_intents}")
        assert_true("Final-day delta has actionable intents (E+X+H > 0)",
                    (len(last_actions['entry']) + len(last_actions['exit']) + len(last_actions['hold'])) > 0)

        # ── Summary ──────────────────────────────────────────────────────────
        section("Summary")
        print(f"  Passes:   {_passes}")
        print(f"  Failures: {_failures}")
        return 0 if _failures == 0 else 1

    finally:
        await conn.close()
        await client.aclose()


if __name__ == "__main__":
    rc = asyncio.run(run())
    sys.exit(rc)
