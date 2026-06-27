"""CHAIN INVARIANT (real Postgres): no actionable intent the planner produces is
rejectable by the risk gate under unchanged account state.

This is the cross-seam guard that would have caught the capacity bug automatically
instead of one audit at a time. It drives the REAL planner (engine
`evaluate_target_vs_live`) against a real, fully-migrated DB, writes the actionable
intents, then drives the REAL risk gate (`_decide`) over them in submission order
— recording each approved order before checking the next, exactly as the executor
does — and asserts EVERY actionable intent is approved.

The seeded scenario is engineered to be the exact shape that used to break:
a near-capacity book with an in-flight (queued, unfilled) entry order. With the
in-flight-aware capacity fix the planner DEFERS the entry that wouldn't fit
(→ watch, not submitted), so the gate never rejects a submitted intent. Without
the fix the planner would emit that entry and the gate would reject it here —
so this test fails on a capacity-parity regression.

`engine` (planner) imports as a top-level module from services/pipeline/app;
the risk gate imports as `app` from services/risk-service — different dirs, no
`app`-name collision, so both run in one process over the shared DB.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest  # noqa: F401
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# ── planner (engine) — top-level module from services/pipeline/app ────────────
_PIPELINE_APP = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "pipeline", "app"))
if _PIPELINE_APP not in sys.path:
    sys.path.insert(0, _PIPELINE_APP)
from engine import evaluate_target_vs_live, RankObservation  # noqa: E402

# ── risk gate — `app` package from services/risk-service ──────────────────────
# Imported LAZILY inside the test (not at module top level) so collection doesn't
# leave risk's `app` resident in sys.modules and shadow sibling integration tests
# that import a DIFFERENT service's `app` (e.g. portfolio-builder's app.select).
# We snapshot and restore sys.path + the `app*` modules around the import.
_RISK = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "risk-service"))


class _risk_app_imported:
    """Context manager: import the risk-service `app` package, restore on exit."""

    def __enter__(self):
        self._saved_path = list(sys.path)
        self._saved_mods = {k: v for k, v in sys.modules.items()
                            if k == "app" or k.startswith("app.")}
        for k in list(self._saved_mods):
            del sys.modules[k]
        sys.path.insert(0, _RISK)
        from app import main as risk_main  # noqa: E402
        from app.main import _decide, TradeCheckRequest  # noqa: E402
        self.risk_main, self._decide, self.TradeCheckRequest = (
            risk_main, _decide, TradeCheckRequest)
        return self

    def __exit__(self, *exc):
        sys.path[:] = self._saved_path
        for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(self._saved_mods)
        return False


try:
    from zoneinfo import ZoneInfo
    TODAY_ET = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
except Exception:  # pragma: no cover
    TODAY_ET = date.today().isoformat()


def _obs(rank: int):
    base = date(2025, 1, 1)
    return [RankObservation(run_date=base + timedelta(2 - i), rank=rank,
                            composite_score=round(1.0 / rank, 6)) for i in range(3)]


async def _seed(eng):
    """Near-capacity book (33 held) + one in-flight entry order (QONE) + a delta run.
    Fresh sync/pipeline + same-day baseline so every risk control passes for the
    actionable intents."""
    async with eng.begin() as c:
        await c.execute(text(
            "INSERT INTO pipeline_runs (run_id, status, completed_at) "
            "VALUES (gen_random_uuid(), 'success', NOW())"))
        await c.execute(text(
            "INSERT INTO alpaca_sync_runs (run_id, status, completed_at, account_value, buying_power) "
            "VALUES (gen_random_uuid(), 'success', NOW() - interval '6 hours', 100000, 100000)"))
        sync_id = (await c.execute(text(
            "INSERT INTO alpaca_sync_runs (run_id, status, completed_at, account_value, buying_power) "
            "VALUES (gen_random_uuid(), 'success', NOW(), 100000, 100000) RETURNING run_id"))).scalar()
        # 33 held: H1 overweight (→ sell_trim), the rest ~equal.
        for i in range(1, 34):
            mv = 6000 if i == 1 else 2000
            await c.execute(text(
                "INSERT INTO live_positions (sync_run_id, ticker, qty, market_value) "
                "VALUES (:s, :t, :q, :mv)"),
                {"s": sync_id, "t": f"H{i}", "q": 10, "mv": mv})
        # in-flight (queued, unfilled) entry order for a NEW ticker → already claims a slot
        await c.execute(text(
            "INSERT INTO alpaca_orders (id, ticker, action, side, status, notional, created_at) "
            "VALUES (gen_random_uuid(), 'QONE', 'entry', 'buy', 'submitted', 2500, NOW())"))
        run_id = (await c.execute(text(
            "INSERT INTO delta_runs (run_id, strategy_id, run_date, status) "
            "VALUES (gen_random_uuid(), 'test', :d, 'running') RETURNING run_id"),
            {"d": date.fromisoformat(TODAY_ET)})).scalar()
    return str(run_id)


def _build_inputs():
    # 33 held H1..H33. Target keeps H1..H32, DROPS H33 (orphan→exit), adds 3 entries.
    held = {f"H{i}" for i in range(1, 34)}
    target = {f"H{i}": 0.025 for i in range(1, 33)}     # 32 holds
    target.update({"NEW1": 0.025, "NEW2": 0.025, "NEW3": 0.025})
    universe = {t: _obs(rank) for rank, t in enumerate(
        list(held) + ["NEW1", "NEW2", "NEW3"], start=1)}
    # H1 is overweight (6% actual vs 2.5% target) → sell_trim; others ≈ target.
    actual = {f"H{i}": (0.06 if i == 1 else 0.025) for i in range(1, 34)}
    # orphan timer = 1 build; history shows H33 absent in the one required build → exit.
    target_history = [set(target.keys())]
    return held, target, universe, actual, target_history


async def _inflight_sets(eng, live: set[str]):
    """Load in-flight entry/exit order tickers exactly as the delta step does."""
    from stock_strategy_shared.order_status import open_status_sql
    inflight_entries: set[str] = set()
    inflight_exits: set[str] = set()
    async with eng.connect() as c:
        rows = (await c.execute(text(
            f"SELECT DISTINCT ticker, action FROM alpaca_orders "
            f"WHERE status IN ({open_status_sql()}) AND action IN ('entry','exit')"))).fetchall()
    for r in rows:
        if r.action == "exit":
            inflight_exits.add(r.ticker)
        elif r.ticker not in live:
            inflight_entries.add(r.ticker)
    return inflight_entries, inflight_exits


async def _run(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    try:
        return await _run_with(eng)
    finally:
        await eng.dispose()


async def _run_with(eng):
    # Clean the tables this test touches so it's order-independent.
    async with eng.begin() as conn:
        await conn.execute(text(
            "TRUNCATE alpaca_orders, delta_intents, delta_runs, live_positions, "
            "alpaca_sync_runs, pipeline_runs RESTART IDENTITY CASCADE"))
    run_id = await _seed(eng)
    held, target, universe, actual, target_history = _build_inputs()
    inflight_entries, inflight_exits = await _inflight_sets(eng, held)

    decisions = evaluate_target_vs_live(
        target_portfolio=target, live_positions=held, universe=universe,
        confirmation_days=3, max_positions=35, actual_weights=actual,
        drift_threshold=0.02, account_value=100000.0, buying_power=100000.0,
        target_history=target_history, orphan_confirmation_days=1,
        inflight_entries=inflight_entries, inflight_exits=inflight_exits,
    )

    # Persist actionable intents (the gate's exit-intent / turnover scoping reads them).
    actionable = {"entry", "exit", "buy_add", "sell_trim"}
    acts = [d for d in decisions.values() if d.action in actionable]
    async with eng.begin() as c:
        for d in acts:
            await c.execute(text(
                "INSERT INTO delta_intents (id, run_id, ticker, action) "
                "VALUES (gen_random_uuid(), :r, :t, :a)"),
                {"r": run_id, "t": d.ticker, "a": d.action})

    # Point the risk gate at the test DB and drive it like the executor: sells first,
    # then entries best-rank-first; record each approved order before the next check.
    order = (["exit", "sell_trim"], ["entry", "buy_add"])
    results = []
    with _risk_app_imported() as risk:
        risk.risk_main.engine = eng
        try:
            for group in order:
                grp = sorted([d for d in acts if d.action in group], key=lambda d: d.rank)
                for d in grp:
                    side = "buy" if d.action in ("entry", "buy_add") else "sell"
                    notional = 2500.0
                    approved, reason, rule, _ = await risk._decide(risk.TradeCheckRequest(
                        ticker=d.ticker, action=d.action, side=side, qty=10, notional=notional,
                        mode="immediate", trade_type="paper", sim_date=TODAY_ET))
                    results.append((d.ticker, d.action, approved, rule, reason))
                    if approved and d.action in ("entry", "buy_add"):
                        # executor records the reservation before the next check (capacity grows)
                        async with eng.begin() as c:
                            await c.execute(text(
                                "INSERT INTO alpaca_orders (id, ticker, action, side, status, notional, created_at) "
                                "VALUES (gen_random_uuid(), :t, :a, 'buy', 'pending', :n, NOW())"),
                                {"t": d.ticker, "a": d.action, "n": notional})
        finally:
            risk.risk_main.engine = None
    return decisions, results


def test_no_actionable_intent_is_rejectable(async_dsn):
    decisions, results = asyncio.run(_run(async_dsn))

    # THE INVARIANT: every actionable intent the planner emitted is gate-approved.
    rejected = [r for r in results if not r[2]]
    assert not rejected, f"planner produced gate-rejectable intents: {rejected}"

    # Sanity that the scenario actually exercised the seam (else the test is vacuous):
    actions = {r[1] for r in results}
    assert "entry" in actions, "scenario produced no entry to capacity-check"
    assert "exit" in actions, "scenario produced no exit (turnover-exemption path)"
    # And the capacity fix bound: NEW3 must have been DEFERRED to watch (not emitted),
    # because the in-flight QONE entry consumed the last slot. If this regresses, NEW3
    # becomes an actionable entry and the invariant above fails at the gate.
    assert decisions["NEW3"].action == "watch", (
        f"NEW3 should be deferred by the in-flight capacity gate, got "
        f"{decisions['NEW3'].action}")
    assert decisions["NEW1"].action == "entry" and decisions["NEW2"].action == "entry"
