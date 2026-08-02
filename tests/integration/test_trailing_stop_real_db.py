"""_plan_stops against a REAL migrated Postgres.

Every unit test above this tier mocks the database, so the SQL in _plan_stops has
never actually run. That is the gap this tier exists for — a previous bug in this
repo shipped green because a `str` was bound to a DATE column and only a real
asyncpg round-trip could see it. The array-unnest join here
(`unnest(CAST(:ts AS text[]), CAST(:ds AS date[]))`) is exactly that shape.

Also covers the behaviour that cannot be unit-tested: episode rows actually being
written, the stop_peak landing where the re-entry gate reads it, and the whole
thing staying inert when the feature is off.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

_PIPELINE = os.path.join(os.path.dirname(__file__), "..", "..", "services", "pipeline")


class _TS:
    """Minimal stand-in for TrailingStopConfig."""
    def __init__(self, **kw):
        self.enabled = kw.get("enabled", True)
        self.stop_pct = kw.get("stop_pct", 0.15)
        self.arm_after_sessions = kw.get("arm_after_sessions", 5)
        self.max_stale_sessions = kw.get("max_stale_sessions", 2)
        self.max_stops_per_run = kw.get("max_stops_per_run", 5)


@pytest_asyncio.fixture
async def mod(async_dsn, monkeypatch):
    """Import the pipeline's main against the test DB and point its engine at it."""
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    sys.path.insert(0, os.path.abspath(_PIPELINE))
    monkeypatch.setenv("DATABASE_URL", async_dsn)
    import app.main as m
    m.engine = create_async_engine(async_dsn, future=True)
    yield m
    await m.engine.dispose()
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]


@pytest_asyncio.fixture
async def seeded(async_dsn):
    """60 sessions of prices. WINNER rises then collapses 40% off its peak;
    STEADY rises throughout; SPY supplies the session calendar."""
    eng = create_async_engine(async_dsn, future=True)
    start = date(2026, 4, 1)
    sessions = [start + timedelta(days=i) for i in range(60)]
    async with eng.begin() as conn:
        await conn.execute(text(
            "TRUNCATE position_episodes, daily_prices RESTART IDENTITY CASCADE"))
        rows = []
        for i, d in enumerate(sessions):
            rows.append({"t": "SPY", "d": d, "p": 500.0 + i})
            rows.append({"t": "STEADY", "d": d, "p": 50.0 + i * 0.5})
            # WINNER: 100 → 150 over 50 sessions, then a hard collapse to 90.
            px = 100.0 + i * 1.0 if i < 50 else 150.0 - (i - 49) * 6.0
            rows.append({"t": "WINNER", "d": d, "p": px})
        for r in rows:
            await conn.execute(text(
                "INSERT INTO daily_prices (ticker, date, close, adjusted_close, volume) "
                "VALUES (:t, :d, :p, :p, 1000000)"), r)
    await eng.dispose()
    return sessions


async def test_a_collapsed_position_is_stopped_and_recorded(mod, seeded, async_dsn):
    sessions = seeded
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on) VALUES ('WINNER', :d)"),
            {"d": sessions[0]})
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on) VALUES ('STEADY', :d)"),
            {"d": sessions[0]})

    stopped, blocked = await mod._plan_stops(
        _TS(stop_pct=0.15), {"WINNER", "STEADY"}, sessions[-1])

    assert set(stopped) == {"WINNER"}, "the collapsed name should stop, the riser should not"
    # The series rises 100 → 149 (i=0..49) then collapses, so 149 is the true
    # episode high — not the 150 the ramp formula reads like at a glance.
    assert stopped["WINNER"] == pytest.approx(149.0), "peak must be the episode high"

    async with eng.connect() as conn:
        row = (await conn.execute(text(
            "SELECT closed_on, pending_close_since, close_reason, stop_peak "
                "  FROM position_episodes "
            "WHERE ticker='WINNER'"))).one()
    # STOP-PENDING, not closed. The sell is queued for the next open and can be
    # rejected, cancelled or partially filled; closing here would tell Stocker the
    # episode ended while the broker still holds the position, and a later re-open
    # would start a FRESH episode with a reset peak — the stop silently loosening
    # itself. The episode closes only once the position is confirmed gone.
    assert row.closed_on is None, "episode must stay OPEN until the sale confirms"
    assert row.pending_close_since == sessions[-1]
    assert row.close_reason == "trailing_stop"
    assert float(row.stop_peak) == pytest.approx(149.0)
    await eng.dispose()


async def test_the_stop_peak_then_blocks_reentry(mod, seeded, async_dsn):
    """The gate the re-entry rule depends on, end to end: once the episode is
    closed with a peak, the name is blocked while it trades below that peak."""
    sessions = seeded
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on, closed_on, close_reason, "
            "stop_peak) VALUES ('WINNER', :o, :c, 'trailing_stop', 150.0)"),
            {"o": sessions[0], "c": sessions[-1]})
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on) VALUES ('STEADY', :d)"),
            {"d": sessions[0]})

    _stopped, blocked = await mod._plan_stops(_TS(), {"STEADY"}, sessions[-1])
    assert blocked == {"WINNER"}, "WINNER last traded at 90, well below its 150 peak"
    await eng.dispose()


async def test_an_orphan_close_does_not_block_reentry(mod, seeded, async_dsn):
    """Only a STOP blocks. A name the orphan timer sold must be re-buyable the
    moment the builder wants it again."""
    sessions = seeded
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on, closed_on, close_reason) "
            "VALUES ('WINNER', :o, :c, 'gone')"), {"o": sessions[0], "c": sessions[-1]})
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on) VALUES ('STEADY', :d)"),
            {"d": sessions[0]})

    _stopped, blocked = await mod._plan_stops(_TS(), {"STEADY"}, sessions[-1])
    assert blocked == set()
    await eng.dispose()


async def test_a_new_holding_opens_an_episode(mod, seeded, async_dsn):
    sessions = seeded
    stopped, _ = await mod._plan_stops(_TS(), {"STEADY"}, sessions[-1])
    assert stopped == {}, "a brand-new episode is unarmed — it cannot stop on day one"

    eng = create_async_engine(async_dsn, future=True)
    async with eng.connect() as conn:
        row = (await conn.execute(text(
            "SELECT opened_on, closed_on FROM position_episodes WHERE ticker='STEADY'"))).one()
    assert row.opened_on == sessions[-1] and row.closed_on is None
    await eng.dispose()


async def test_absence_needs_two_runs_before_the_episode_closes(mod, seeded, async_dsn):
    """The peak-reset guard, against a real table. One degraded sync must not end
    the episode, because the re-opened one would carry a fresh, looser peak."""
    sessions = seeded
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on) VALUES ('WINNER', :d)"),
            {"d": sessions[0]})

    await mod._plan_stops(_TS(), set(), sessions[-2])       # absent, run 1
    async with eng.connect() as conn:
        row = (await conn.execute(text(
            "SELECT closed_on, pending_close_since FROM position_episodes "
            "WHERE ticker='WINNER'"))).one()
    assert row.closed_on is None and row.pending_close_since == sessions[-2]

    await mod._plan_stops(_TS(), set(), sessions[-1])       # absent, run 2
    async with eng.connect() as conn:
        row = (await conn.execute(text(
            "SELECT closed_on, close_reason FROM position_episodes "
            "WHERE ticker='WINNER'"))).one()
    assert row.closed_on == sessions[-1] and row.close_reason == "gone"
    await eng.dispose()


async def test_the_circuit_breaker_bounds_one_run(mod, seeded, async_dsn):
    sessions = seeded
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        # Two collapsed names sharing WINNER's series.
        for t in ("WINNER", "WINNER2"):
            await conn.execute(text(
                "INSERT INTO position_episodes (ticker, opened_on) VALUES (:t, :d)"),
                {"t": t, "d": sessions[0]})
        await conn.execute(text(
            "INSERT INTO daily_prices (ticker, date, close, adjusted_close, volume) "
            "SELECT 'WINNER2', date, close, adjusted_close, volume "
            "FROM daily_prices WHERE ticker='WINNER'"))

    stopped, _ = await mod._plan_stops(
        _TS(max_stops_per_run=1), {"WINNER", "WINNER2"}, sessions[-1])
    assert len(stopped) == 1, "the breaker must bound a market-wide collapse"
    await eng.dispose()


async def test_a_stop_whose_sale_never_fills_keeps_its_peak(mod, seeded, async_dsn):
    """THE reason the stop marks pending instead of closing.

    A stop fires, the sell is queued for the next open — and is rejected. The
    broker still holds the position. If the episode had been closed, the next sync
    would see the ticker held with no open episode and open a NEW one dated today,
    with today's price as its peak. The stop would then need another full
    stop_pct fall FROM THE REDUCED PRICE before firing again: a risk control
    silently loosening itself at the worst moment.

    Here the episode stays open, so opened_on and the recorded peak survive and
    the stop can fire again on the next run.
    """
    from app.episodes import plan_episode_sync

    sessions = seeded
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM position_episodes"))
        await conn.execute(text(
            "INSERT INTO position_episodes (ticker, opened_on, close_reason, "
            " stop_peak, pending_close_since) "
            "VALUES ('WINNER', :o, 'trailing_stop', 149.0, :p)"),
            {"o": sessions[0], "p": sessions[-1]})
        rows = (await conn.execute(text(
            "SELECT ticker, opened_on, pending_close_since, close_reason "
            "  FROM position_episodes WHERE closed_on IS NULL"))).fetchall()

    open_eps = {r.ticker: r.opened_on for r in rows}
    pending = {r.ticker: r.pending_close_since for r in rows}
    stop_pending = {r.ticker for r in rows
                    if r.close_reason == "trailing_stop"
                    and r.pending_close_since is not None}

    # The sale did not fill, so the broker still reports the position HELD.
    sync = plan_episode_sync({"WINNER"}, open_eps, pending, sessions[-1],
                             stop_pending=stop_pending)

    assert "WINNER" not in sync.to_clear_pending, (
        "a stop-pending episode must NOT be cleared just because the position is "
        "still held — it is still held precisely BECAUSE the sale has not happened")
    assert "WINNER" not in sync.to_open, "no second episode may be opened"
    assert "WINNER" not in sync.to_close

    async with eng.connect() as conn:
        row = (await conn.execute(text(
            "SELECT opened_on, stop_peak FROM position_episodes "
            "WHERE ticker='WINNER'"))).one()
    assert row.opened_on == sessions[0], "the original entry date must survive"
    assert float(row.stop_peak) == pytest.approx(149.0), "the peak must survive"
    await eng.dispose()
