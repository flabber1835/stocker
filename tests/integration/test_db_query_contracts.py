"""
Schema-contract tests: run the real, type-sensitive service queries against a
real migrated Postgres through async SQLAlchemy + asyncpg (the production stack).

Each test seeds the minimum rows needed and executes the actual query a service
runs. A wrong column name, a uuid/integer mismatch, or a str-bound-to-DATE param
raises here — in CI — instead of silently 500-ing a service in production.

The query that recently broke in deployment is covered explicitly:
  - vetter held-tickers  (live_positions.sync_run_id UUID = alpaca_sync_runs.run_id)
plus the dashboard's rankings/with-overlays join chain.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    # Clean slate per test so row counts are deterministic.
    async with eng.begin() as conn:
        await conn.execute(text(
            "TRUNCATE live_positions, alpaca_sync_runs, "
            "rankings, ranking_runs, universe_tickers, universe_snapshots "
            "RESTART IDENTITY CASCADE"
        ))
    yield eng
    await eng.dispose()


# ── vetter held-tickers query (regression: SELECT id → uuid = integer) ────────

class TestVetterHeldTickersQuery:
    async def test_held_query_runs_and_returns_held_tickers(self, engine):
        sync_run_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO alpaca_sync_runs (run_id, status, completed_at) "
                "VALUES (:rid, 'success', NOW())"
            ), {"rid": sync_run_id})
            await conn.execute(text(
                "INSERT INTO live_positions (sync_run_id, ticker, qty) VALUES "
                "(:rid, 'AAPL', 10), (:rid, 'MSFT', 5), (:rid, 'TSLA', 0)"
            ), {"rid": sync_run_id})

        # The exact query from services/llm-vetter/app/main.py
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "SELECT ticker FROM live_positions "
                "WHERE sync_run_id = ("
                "  SELECT run_id FROM alpaca_sync_runs "
                "  WHERE status = 'success' "
                "  ORDER BY completed_at DESC LIMIT 1"
                ") AND qty > 0"
            ))
            held = {r.ticker for r in rows.fetchall()}

        assert held == {"AAPL", "MSFT"}  # TSLA qty=0 excluded

    async def test_selecting_id_instead_of_run_id_raises(self, engine):
        """Proves the test tier actually catches the original bug: comparing a
        UUID column to alpaca_sync_runs.id (integer) must error."""
        from sqlalchemy.exc import DBAPIError

        sync_run_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO alpaca_sync_runs (run_id, status, completed_at) "
                "VALUES (:rid, 'success', NOW())"
            ), {"rid": sync_run_id})

        with pytest.raises(DBAPIError):
            async with engine.connect() as conn:
                await conn.execute(text(
                    "SELECT ticker FROM live_positions "
                    "WHERE sync_run_id = ("
                    "  SELECT id FROM alpaca_sync_runs "
                    "  WHERE status = 'success' "
                    "  ORDER BY completed_at DESC LIMIT 1"
                    ") AND qty > 0"
                ))


# ── _size_exit latest-sync scoping (the "sells positions not held" bug) ───────

class TestSizeExitLatestSyncScoping:
    """_size_exit must size from the ticker's position in the LATEST sync — not the
    most recent sync that merely CONTAINED the ticker. A position closed since the
    last targeted run is absent from the latest sync; the query must return no row
    so the executor refuses, instead of resurrecting a stale qty and selling a ghost
    (Alpaca "available: 0"). Reproduces the confirmed production incident.
    """

    # Mirror of the production query in services/trade-executor/app/main.py _size_exit.
    _SQL = (
        "SELECT lp.qty, lp.current_price, sr.completed_at "
        "FROM live_positions lp "
        "JOIN alpaca_sync_runs sr ON sr.run_id = lp.sync_run_id "
        "WHERE sr.run_id = ("
        "  SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
        "  ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        ") AND lp.ticker = :t"
    )

    async def _seed_sync(self, conn, completed_at, positions):
        rid = uuid.uuid4()
        await conn.execute(text(
            "INSERT INTO alpaca_sync_runs (run_id, status, completed_at) "
            "VALUES (:rid, 'success', :ca)"
        ), {"rid": rid, "ca": completed_at})
        for ticker, qty in positions.items():
            await conn.execute(text(
                "INSERT INTO live_positions (sync_run_id, ticker, qty, current_price) "
                "VALUES (:rid, :t, :q, 60.0)"
            ), {"rid": rid, "t": ticker, "q": qty})
        return rid

    async def test_closed_position_absent_from_latest_sync_returns_no_row(self, engine):
        """AU held in an OLD sync, gone from the LATEST sync → query returns nothing
        → executor refuses. The naive 'latest sync that contained AU' would wrongly
        return the old qty."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        async with engine.begin() as conn:
            # Old sync: AU held (31 shares).
            await self._seed_sync(conn, now - timedelta(hours=9), {"AU": 31, "MSFT": 10})
            # Latest sync: AU is GONE (sold); MSFT still held.
            await self._seed_sync(conn, now, {"MSFT": 10})

        async with engine.connect() as conn:
            row = (await conn.execute(text(self._SQL), {"t": "AU"})).mappings().first()
        assert row is None, "AU absent from latest sync must yield no row (refuse exit)"

    async def test_still_held_in_latest_sync_returns_qty(self, engine):
        """A position present in the latest sync sizes normally."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        async with engine.begin() as conn:
            await self._seed_sync(conn, now - timedelta(hours=9), {"MSFT": 5})
            await self._seed_sync(conn, now, {"MSFT": 10})  # latest: 10 shares

        async with engine.connect() as conn:
            row = (await conn.execute(text(self._SQL), {"t": "MSFT"})).mappings().first()
        assert row is not None
        assert float(row["qty"]) == 10.0, "must size from the LATEST sync's qty, not the old one"


# ── dashboard rankings/with-overlays core join (the "NO DATA" endpoint) ───────

class TestRankingsWithOverlaysQuery:
    async def test_latest_run_join_returns_rows(self, engine):
        run_id = uuid.uuid4()
        factor_run_id = uuid.uuid4()
        async with engine.begin() as conn:
            # ranking_runs requires a source_factor_run_id FK → seed a factor_run
            await conn.execute(text(
                "INSERT INTO factor_runs (run_id, strategy_id, status, started_at) "
                "VALUES (:frid, 'quality_core_v1', 'success', NOW())"
            ), {"frid": factor_run_id})
            await conn.execute(text(
                "INSERT INTO ranking_runs "
                "(run_id, source_factor_run_id, strategy_id, status, rank_date, regime, "
                " universe_count, ranked_count, completed_at) "
                "VALUES (:rid, :frid, 'quality_core_v1', 'success', :d, 'bull_calm', 2, 2, NOW())"
            ), {"rid": run_id, "frid": factor_run_id, "d": date.today()})
            await conn.execute(text(
                "INSERT INTO rankings "
                "(run_id, source_factor_run_id, strategy_id, regime, rank_date, "
                " ticker, rank, composite_score, percentile) "
                "VALUES (:rid, :frid, 'quality_core_v1', 'bull_calm', :d, 'AAPL', 1, 1.5, 1.0), "
                "       (:rid, :frid, 'quality_core_v1', 'bull_calm', :d, 'MSFT', 2, 1.2, 0.0)"
            ), {"rid": run_id, "frid": factor_run_id, "d": date.today()})

        # Core of get_rankings_with_overlays: latest successful run + rank slopes.
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "WITH recent_runs AS ("
                "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos"
                "  FROM ("
                "    SELECT run_id, rank_date FROM ("
                "      SELECT DISTINCT ON (rank_date) run_id, rank_date"
                "      FROM ranking_runs WHERE status='success'"
                "      ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
                "    ) latest_per_date"
                "    ORDER BY rank_date DESC LIMIT 5"
                "  ) recent_dates"
                "),"
                "ticker_slopes AS ("
                "  SELECT r.ticker,"
                "    REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
                "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
                "  GROUP BY r.ticker"
                ")"
                "SELECT r.ticker, r.rank, ts.rank_slope "
                "FROM rankings r LEFT JOIN ticker_slopes ts ON ts.ticker = r.ticker "
                "WHERE r.run_id = ("
                "  SELECT run_id FROM ranking_runs WHERE status='success' "
                "  ORDER BY rank_date DESC, completed_at DESC NULLS LAST LIMIT 1"
                ") ORDER BY r.rank ASC"
            ))
            ranked = [(r.ticker, r.rank) for r in rows.fetchall()]

        assert ranked == [("AAPL", 1), ("MSFT", 2)]

    async def test_tickers_param_scopes_to_subset(self, engine):
        """The Target tab's tickers= path: `displayed` is the EXPLICIT set (not
        top-N) and the final query returns only those tickers — validated against
        real PG so the scoped SQL fragment can't silently break the join chain."""
        run_id = uuid.uuid4()
        factor_run_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO factor_runs (run_id, strategy_id, status, started_at) "
                "VALUES (:f,'quality_core_v1','success',NOW())"
            ), {"f": factor_run_id})
            await conn.execute(text(
                "INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, "
                " status, rank_date, regime, universe_count, ranked_count, completed_at) "
                "VALUES (:r,:f,'quality_core_v1','success',:d,'bull_calm',3,3,NOW())"
            ), {"r": run_id, "f": factor_run_id, "d": date.today()})
            await conn.execute(text(
                "INSERT INTO rankings (run_id, source_factor_run_id, strategy_id, regime, "
                " rank_date, ticker, rank, composite_score, percentile) VALUES "
                "(:r,:f,'quality_core_v1','bull_calm',:d,'AAPL',1,1.5,1.0),"
                "(:r,:f,'quality_core_v1','bull_calm',:d,'MSFT',2,1.2,0.5),"
                "(:r,:f,'quality_core_v1','bull_calm',:d,'NVDA',3,1.0,0.0)"
            ), {"r": run_id, "f": factor_run_id, "d": date.today()})

        only = ["AAPL", "NVDA"]   # request a subset; MSFT must NOT come back
        async with engine.connect() as conn:
            rows = await conn.execute(text(
                "WITH displayed AS ("
                "  SELECT ticker FROM rankings WHERE run_id = :rid AND ticker = ANY(:only)"
                "),"
                "recent_runs AS ("
                "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos FROM ("
                "    SELECT run_id, rank_date FROM ("
                "      SELECT DISTINCT ON (rank_date) run_id, rank_date FROM ranking_runs "
                "      WHERE status='success' ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
                "    ) lpd ORDER BY rank_date DESC LIMIT 5) rd),"
                "ticker_slopes AS ("
                "  SELECT r.ticker, REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
                "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
                "  WHERE r.ticker IN (SELECT ticker FROM displayed) GROUP BY r.ticker)"
                "SELECT r.ticker, r.rank, ts.rank_slope FROM rankings r "
                "LEFT JOIN ticker_slopes ts ON ts.ticker = r.ticker "
                "WHERE r.run_id = :rid AND r.ticker = ANY(:only) ORDER BY r.rank ASC"
            ), {"rid": run_id, "only": only})
            got = [r.ticker for r in rows.fetchall()]

        assert got == ["AAPL", "NVDA"]   # scoped to the set, MSFT (top-N) excluded


class TestSlopeDedupesSameDayRuns:
    """Re-running the chain multiple times on one session must NOT flush the
    rank-trend window. The slope/prior-rank queries collapse ranking_runs to one
    row per rank_date (most-recent run wins), so manual re-runs preserve the
    arrows that compare distinct sessions.
    """

    # Mirror of the production slope CTE (services/api/app/main.py) — kept in sync
    # so a regression in the dedup logic fails here in CI.
    _SLOPE_SQL = (
        "WITH recent_runs AS ("
        "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos"
        "  FROM ("
        "    SELECT run_id, rank_date FROM ("
        "      SELECT DISTINCT ON (rank_date) run_id, rank_date"
        "      FROM ranking_runs WHERE status='success'"
        "      ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
        "    ) latest_per_date"
        "    ORDER BY rank_date DESC LIMIT 5"
        "  ) recent_dates"
        "),"
        "ticker_slopes AS ("
        "  SELECT r.ticker,"
        "    REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
        "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
        "  GROUP BY r.ticker"
        ")"
        "SELECT ticker, rank_slope FROM ticker_slopes ORDER BY ticker"
    )

    async def _seed_run(self, conn, run_id, factor_run_id, d, ranks, completed_at_sql="NOW()"):
        await conn.execute(text(
            "INSERT INTO factor_runs (run_id, strategy_id, status, started_at) "
            "VALUES (:frid, 'quality_core_v1', 'success', NOW())"
        ), {"frid": factor_run_id})
        await conn.execute(text(
            "INSERT INTO ranking_runs "
            "(run_id, source_factor_run_id, strategy_id, status, rank_date, regime, "
            " universe_count, ranked_count, completed_at) "
            f"VALUES (:rid, :frid, 'quality_core_v1', 'success', :d, 'bull_calm', "
            f" 2, 2, {completed_at_sql})"
        ), {"rid": run_id, "frid": factor_run_id, "d": d})
        for ticker, rank in ranks.items():
            await conn.execute(text(
                "INSERT INTO rankings "
                "(run_id, source_factor_run_id, strategy_id, regime, rank_date, "
                " ticker, rank, composite_score, percentile) "
                "VALUES (:rid, :frid, 'quality_core_v1', 'bull_calm', :d, "
                " :t, :rk, 1.0, 0.5)"
            ), {"rid": run_id, "frid": factor_run_id, "d": d, "t": ticker, "rk": rank})

    async def test_same_day_reruns_do_not_wash_out_slope(self, engine):
        today = date.today()
        yesterday = today - timedelta(days=1)
        async with engine.begin() as conn:
            # Prior session: AAPL was rank 20.
            await self._seed_run(conn, uuid.uuid4(), uuid.uuid4(), yesterday,
                                  {"AAPL": 20}, completed_at_sql="NOW() - INTERVAL '1 day'")
            # Today, FIRST run: AAPL improved to rank 10.
            await self._seed_run(conn, uuid.uuid4(), uuid.uuid4(), today,
                                  {"AAPL": 10}, completed_at_sql="NOW() - INTERVAL '2 hours'")
            # Today, SECOND run (manual re-run): identical data, rank 10 again.
            await self._seed_run(conn, uuid.uuid4(), uuid.uuid4(), today,
                                  {"AAPL": 10}, completed_at_sql="NOW()")

        async with engine.connect() as conn:
            rows = (await conn.execute(text(self._SLOPE_SQL))).fetchall()
        slopes = {r.ticker: r.rank_slope for r in rows}
        # Two distinct dates in the window (20 → 10): a real improving slope of -10,
        # NOT washed to ~0 by the duplicate same-day run.
        assert slopes["AAPL"] is not None
        assert slopes["AAPL"] == pytest.approx(-10.0)

    async def test_window_counts_distinct_dates_not_runs(self, engine):
        """Six runs across three dates must yield a 3-point slope, not be capped to
        the 5 most recent RUNS (which would drop the oldest date entirely)."""
        today = date.today()
        async with engine.begin() as conn:
            # date d-2: rank 30 (two runs)
            for ca in ("NOW() - INTERVAL '2 day 2 hour'", "NOW() - INTERVAL '2 day'"):
                await self._seed_run(conn, uuid.uuid4(), uuid.uuid4(),
                                     today - timedelta(days=2), {"AAPL": 30}, ca)
            # date d-1: rank 20 (two runs)
            for ca in ("NOW() - INTERVAL '1 day 2 hour'", "NOW() - INTERVAL '1 day'"):
                await self._seed_run(conn, uuid.uuid4(), uuid.uuid4(),
                                     today - timedelta(days=1), {"AAPL": 20}, ca)
            # date d-0: rank 10 (two runs)
            for ca in ("NOW() - INTERVAL '2 hour'", "NOW()"):
                await self._seed_run(conn, uuid.uuid4(), uuid.uuid4(),
                                     today, {"AAPL": 10}, ca)

        async with engine.connect() as conn:
            rows = (await conn.execute(text(self._SLOPE_SQL))).fetchall()
        slopes = {r.ticker: r.rank_slope for r in rows}
        # 30 → 20 → 10 over three equally-spaced date points → slope -10.
        assert slopes["AAPL"] == pytest.approx(-10.0)

    async def test_prior_run_is_prior_distinct_date(self, engine):
        """The prior-rank lookup must point at the prior DISTINCT date's latest run,
        not the prior run on the same date (which would give a zero diff)."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        async with engine.begin() as conn:
            await self._seed_run(conn, uuid.uuid4(), uuid.uuid4(), yesterday,
                                 {"AAPL": 20}, "NOW() - INTERVAL '1 day'")
            await self._seed_run(conn, uuid.uuid4(), uuid.uuid4(), today,
                                 {"AAPL": 10}, "NOW() - INTERVAL '2 hours'")
            await self._seed_run(conn, uuid.uuid4(), uuid.uuid4(), today,
                                 {"AAPL": 10}, "NOW()")

        # Mirror of the prior-run selection in get_rankings_with_overlays.
        async with engine.connect() as conn:
            run_rows = (await conn.execute(text(
                "SELECT run_id, rank_date FROM ("
                "  SELECT DISTINCT ON (rank_date) run_id, rank_date"
                "  FROM ranking_runs WHERE status='success'"
                "  ORDER BY rank_date DESC, completed_at DESC NULLS LAST"
                ") latest_per_date "
                "ORDER BY rank_date DESC LIMIT 2"
            ))).fetchall()
            latest_run_id = run_rows[0].run_id
            prior_run_id = run_rows[1].run_id
            # latest is today's most-recent run, prior is yesterday's run.
            assert run_rows[0].rank_date == today
            assert run_rows[1].rank_date == yesterday
            latest_rank = (await conn.execute(text(
                "SELECT rank FROM rankings WHERE run_id = :rid AND ticker='AAPL'"
            ), {"rid": latest_run_id})).scalar()
            prior_rank = (await conn.execute(text(
                "SELECT rank FROM rankings WHERE run_id = :rid AND ticker='AAPL'"
            ), {"rid": prior_run_id})).scalar()
        # prior(20) - latest(10) = +10 → an "up 10" arrow, not 0.
        assert prior_rank - latest_rank == 10
