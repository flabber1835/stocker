"""/rankings/suggest typeahead query — against a REAL migrated Postgres.

Mirrors the production SQL in services/api/app/main.py::suggest_rankings (kept in
sync, like the other contract tests) and runs it on real rows so a column/type/
ordering drift fails here in CI rather than silently in the screener typeahead.

Covers: ticker-contains AND company-name-contains matching, the exact→prefix→rank
ordering, and the limit.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

# Exact mirror of suggest_rankings' match query (latest run already resolved → :run_id).
_SUGGEST_SQL = (
    "WITH names AS ("
    "  SELECT DISTINCT ON (ticker) ticker, name FROM universe_tickers"
    "  WHERE snapshot_id = (SELECT MAX(id) FROM universe_snapshots)"
    "  ORDER BY ticker, id ASC"
    ")"
    "SELECT r.ticker, n.name, r.rank "
    "FROM rankings r "
    "LEFT JOIN names n ON n.ticker = r.ticker "
    "WHERE r.run_id = :run_id "
    "  AND (UPPER(r.ticker) LIKE '%' || UPPER(:q) || '%' "
    "       OR UPPER(n.name) LIKE '%' || UPPER(:q) || '%') "
    "ORDER BY "
    "  (UPPER(r.ticker) = UPPER(:q)) DESC, "
    "  (UPPER(r.ticker) LIKE UPPER(:q) || '%') DESC, "
    "  r.rank ASC "
    "LIMIT :limit"
)


@pytest_asyncio.fixture
async def seeded(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    run_id = uuid.uuid4()
    factor_run_id = uuid.uuid4()
    # (ticker, rank, company name)
    rows = [
        ("AAPL", 1, "Apple Inc"),
        ("MSFT", 2, "Microsoft Corp"),
        ("KEY", 5, "KeyCorp"),
        ("KEYS", 10, "Keysight Technologies"),
        ("KEX", 20, "Kirby Corp"),
    ]
    async with eng.begin() as conn:
        await conn.execute(text(
            "TRUNCATE rankings, ranking_runs, factor_runs, universe_tickers, "
            "universe_snapshots RESTART IDENTITY CASCADE"))
        await conn.execute(text(
            "INSERT INTO factor_runs (run_id, strategy_id, status, started_at) "
            "VALUES (:f,'quality_core_v1','success',NOW())"), {"f": factor_run_id})
        await conn.execute(text(
            "INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, status, "
            " rank_date, regime, universe_count, ranked_count, completed_at) "
            "VALUES (:r,:f,'quality_core_v1','success',:d,'bull_calm',:n,:n,NOW())"),
            {"r": run_id, "f": factor_run_id, "d": date.today(), "n": len(rows)})
        await conn.execute(text(
            "INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count) "
            "VALUES ('TEST', :d, :n)"), {"d": date.today(), "n": len(rows)})
        for t, rk, nm in rows:
            await conn.execute(text(
                "INSERT INTO rankings (run_id, source_factor_run_id, strategy_id, regime, "
                " rank_date, ticker, rank, composite_score, percentile) "
                "VALUES (:r,:f,'quality_core_v1','bull_calm',:d,:t,:rk,1.0,0.5)"),
                {"r": run_id, "f": factor_run_id, "d": date.today(), "t": t, "rk": rk})
            await conn.execute(text(
                "INSERT INTO universe_tickers (snapshot_id, ticker, name) "
                "VALUES ((SELECT MAX(id) FROM universe_snapshots), :t, :nm)"),
                {"t": t, "nm": nm})
    yield eng, str(run_id)
    await eng.dispose()


async def _suggest(eng, run_id, q, limit=20):
    async with eng.connect() as conn:
        res = await conn.execute(text(_SUGGEST_SQL), {"run_id": run_id, "q": q, "limit": limit})
        return [(m["ticker"], m["name"], m["rank"]) for m in res.mappings()]


class TestSuggestRealDB:
    async def test_ticker_contains(self, seeded):
        eng, run_id = seeded
        got = [t for t, _, _ in await _suggest(eng, run_id, "KE")]
        # all three contain "KE"; none is an exact/none-better prefix, so rank order
        assert got == ["KEY", "KEYS", "KEX"]

    async def test_name_contains_when_ticker_doesnt(self, seeded):
        eng, run_id = seeded
        # "AAPL" does NOT contain "APPL", but the company name "Apple Inc" does.
        got = [t for t, _, _ in await _suggest(eng, run_id, "APPL")]
        assert "AAPL" not in (s for s in ["AAPL"] if "APPL" in "AAPL")  # sanity: ticker miss
        assert got == ["AAPL"]

    async def test_exact_ticker_orders_first(self, seeded):
        eng, run_id = seeded
        got = [t for t, _, _ in await _suggest(eng, run_id, "KEY")]
        # exact "KEY" first (despite rank 5), then prefix "KEYS"
        assert got == ["KEY", "KEYS"]

    async def test_limit_caps_results(self, seeded):
        eng, run_id = seeded
        got = await _suggest(eng, run_id, "KE", limit=1)
        assert got == [("KEY", "KeyCorp", 5)]

    async def test_no_match_empty(self, seeded):
        eng, run_id = seeded
        assert await _suggest(eng, run_id, "ZZZZ") == []
