"""`_paired_spans` — the query behind a CONFIG-CHANGING decision, run against a
real migrated schema.

The auto-revert path compares the live champion's target book against the
displaced champion's shadow target, both scored over the same fixed session
horizon. Everything downstream of it is pure and unit-tested; this query is the
part that can be silently wrong — a bad join, a str bound to a DATE column, or
picking the superseded build for a date would feed correct-looking numbers into
a rule that rewrites the live strategy.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

D0 = date(2026, 6, 1)
RANK_RUN = ""


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text(
            "TRUNCATE shadow_runs, portfolio_holdings, portfolio_runs, "
            "ranking_runs, factor_runs, daily_prices RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


def _sessions(n: int, start: date = D0) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


async def _seed(conn, *, champ_ret: float, shadow_ret: float,
                n_targets: int = 3, horizon: int = 5):
    """SPY sessions + two priced names: CH (the champion's pick) and SH (the
    displaced champion's). Each moves by its own fixed return over the horizon,
    so the resulting spans are exactly predictable."""
    sess = _sessions(40)
    global RANK_RUN
    RANK_RUN = str(uuid.uuid4())
    factor_run = str(uuid.uuid4())
    await conn.execute(text(
        "INSERT INTO factor_runs (run_id, strategy_id, config_hash, score_date, "
        " regime, status, started_at, completed_at) "
        "VALUES (CAST(:r AS uuid), 's1', 'h1', :d, 'bull_calm', 'success', "
        "        NOW(), NOW())"), {"r": factor_run, "d": sess[0]})
    await conn.execute(text(
        "INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, "
        " config_hash, regime, rank_date, status, started_at, completed_at) "
        "VALUES (CAST(:r AS uuid), CAST(:f AS uuid), 's1', 'h1', 'bull_calm', "
        "        :d, 'success', NOW(), NOW())"),
        {"r": RANK_RUN, "f": factor_run, "d": sess[0]})
    await conn.execute(text(
        "INSERT INTO daily_prices (ticker, date, adjusted_close, close) "
        "VALUES ('SPY', :d, 400, 400)"), [{"d": d} for d in sess])
    # Priced from day 0 so every anchor has a base, geometric so a fixed
    # horizon gives a fixed return regardless of which day is the anchor.
    for tkr, per_day in (("CH", (1 + champ_ret) ** (1 / horizon)),
                         ("SH", (1 + shadow_ret) ** (1 / horizon))):
        rows = [{"t": tkr, "d": d, "px": round(100 * per_day ** i, 6)}
                for i, d in enumerate(sess)]
        await conn.execute(text(
            "INSERT INTO daily_prices (ticker, date, adjusted_close, close) "
            "VALUES (:t, :d, :px, :px)"), rows)

    for i in range(n_targets):
        d = sess[i]
        run_id = str(uuid.uuid4())
        await conn.execute(text(
            "INSERT INTO portfolio_runs (run_id, source_ranking_run_id, strategy_id, "
            " config_hash, regime, portfolio_date, status, started_at, completed_at) "
            "VALUES (CAST(:r AS uuid), CAST(:s AS uuid), 's1', 'h1', 'bull_calm', "
            "        :d, 'success', NOW(), NOW())"),
            {"r": run_id, "s": RANK_RUN, "d": d})
        await conn.execute(text(
            "INSERT INTO portfolio_holdings (run_id, source_ranking_run_id, strategy_id, "
            " regime, portfolio_date, ticker, position, weight) "
            "VALUES (CAST(:r AS uuid), CAST(:s AS uuid), 's1', 'bull_calm', :d, "
            "        'CH', 1, 1.0)"), {"r": run_id, "s": RANK_RUN, "d": d})
        await conn.execute(text(
            "INSERT INTO shadow_runs (run_date, strategy_id, config_hash, "
            " status, target, n_positions) "
            "VALUES (:d, 's1', 'displaced1', 'success', "
            "        CAST('{\"SH\": 1.0}' AS jsonb), 1)"), {"d": d})
    return sess


class TestPairedSpans:
    async def _call(self, engine, horizon=5, since=str(D0)):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                        "services", "api"))
        from app.main import _paired_spans
        async with engine.connect() as conn:
            return await _paired_spans(conn, "displaced1", since, horizon)

    async def test_pairs_are_returned_with_both_sides_scored(self, engine):
        async with engine.begin() as conn:
            await _seed(conn, champ_ret=0.02, shadow_ret=0.06)
        pairs = await self._call(engine)
        assert len(pairs) == 3
        for champ, disp in pairs:
            assert champ == pytest.approx(0.02, abs=1e-6)
            assert disp == pytest.approx(0.06, abs=1e-6)

    async def test_dates_without_an_elapsed_horizon_are_excluded(self, engine):
        """A partial window scored as a full one is what makes pooled averages
        measure elapsed time instead of performance."""
        async with engine.begin() as conn:
            sess = await _seed(conn, champ_ret=0.01, shadow_ret=0.02)
            # A target on the LAST session: no horizon left.
            run_id = str(uuid.uuid4())
            await conn.execute(text(
                "INSERT INTO portfolio_runs (run_id, source_ranking_run_id, strategy_id, "
                " config_hash, regime, portfolio_date, status, started_at, completed_at) "
                "VALUES (CAST(:r AS uuid), CAST(:s AS uuid), 's1', 'h1', 'bull_calm', "
                "        :d, 'success', NOW(), NOW())"),
                {"r": run_id, "s": RANK_RUN, "d": sess[-1]})
            await conn.execute(text(
                "INSERT INTO portfolio_holdings (run_id, source_ranking_run_id, strategy_id, "
                " regime, portfolio_date, ticker, position, weight) "
                "VALUES (CAST(:r AS uuid), CAST(:s AS uuid), 's1', 'bull_calm', :d, "
                "        'CH', 1, 1.0)"),
                {"r": run_id, "s": RANK_RUN, "d": sess[-1]})
            await conn.execute(text(
                "INSERT INTO shadow_runs (run_date, strategy_id, config_hash, "
                " status, target, n_positions) VALUES (:d, 's1', 'displaced1', "
                "'success', CAST('{\"SH\": 1.0}' AS jsonb), 1)"), {"d": sess[-1]})
        assert len(await self._call(engine)) == 3          # not 4

    async def test_a_day_without_a_shadow_is_not_paired(self, engine):
        """Missing shadow data must drop the day, never compare the champion
        against nothing."""
        async with engine.begin() as conn:
            await _seed(conn, champ_ret=0.01, shadow_ret=0.02)
            await conn.execute(text(
                "DELETE FROM shadow_runs WHERE run_date = :d"), {"d": D0})
        assert len(await self._call(engine)) == 2

    async def test_a_superseded_build_is_not_the_champion_for_its_date(self, engine):
        """A manual re-run supersedes a cron build for the same date. Scoring
        the stale one compares the displaced config against a target that was
        never live."""
        async with engine.begin() as conn:
            sess = await _seed(conn, champ_ret=0.02, shadow_ret=0.06)
            # Mark the real build for sess[0] superseded and add a replacement
            # holding a name that does not move at all.
            await conn.execute(text(
                "INSERT INTO daily_prices (ticker, date, adjusted_close, close) "
                "VALUES ('FLAT', :d, 50, 50)"), [{"d": d} for d in sess])
            await conn.execute(text(
                "UPDATE portfolio_runs SET superseded_at = NOW() "
                "WHERE portfolio_date = :d"), {"d": sess[0]})
            run_id = str(uuid.uuid4())
            await conn.execute(text(
                "INSERT INTO portfolio_runs (run_id, source_ranking_run_id, strategy_id, "
                " config_hash, regime, portfolio_date, status, started_at, completed_at) "
                "VALUES (CAST(:r AS uuid), CAST(:s AS uuid), 's1', 'h1', 'bull_calm', "
                "        :d, 'success', NOW(), NOW())"),
                {"r": run_id, "s": RANK_RUN, "d": sess[0]})
            await conn.execute(text(
                "INSERT INTO portfolio_holdings (run_id, source_ranking_run_id, strategy_id, "
                " regime, portfolio_date, ticker, position, weight) "
                "VALUES (CAST(:r AS uuid), CAST(:s AS uuid), 's1', 'bull_calm', :d, "
                "        'FLAT', 1, 1.0)"),
                {"r": run_id, "s": RANK_RUN, "d": sess[0]})
        pairs = await self._call(engine)
        assert len(pairs) == 3
        assert any(c == pytest.approx(0.0, abs=1e-9) for c, _ in pairs), (
            "the superseded build was scored instead of the live one")

    async def test_no_shadow_rows_yields_nothing_rather_than_raising(self, engine):
        """Fail-closed: an unknown displaced hash must produce no evidence, not
        an exception that a bare `except` upstream could swallow into a revert."""
        async with engine.begin() as conn:
            await _seed(conn, champ_ret=0.01, shadow_ret=0.02)
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                        "services", "api"))
        from app.main import _paired_spans
        async with engine.connect() as conn:
            assert await _paired_spans(conn, "nosuchhash", str(D0), 5) == []
