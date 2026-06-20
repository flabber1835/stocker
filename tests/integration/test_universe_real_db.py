"""/rankings/universe full-list query — against a REAL migrated Postgres.

Mirrors the production logic in services/api/app/main.py::get_rankings_universe
(the main SQL + the light held-overlay/injection step, kept in sync like the other
contract tests) and runs it on real rows, so a column/join/ordering drift fails in
CI rather than in the screener.

Asserts: the full ranked universe comes back (not just top-N), the cheap columns +
prior_rank arrows + name join are present, NO expensive overlay columns leak in,
held rows are flagged, and a held-but-unranked position is injected.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

# Exact mirror of get_rankings_universe's main query (latest/prior already resolved).
_UNIVERSE_SQL = (
    "WITH prior AS ("
    "  SELECT ticker, rank AS prior_rank FROM rankings WHERE run_id = :prior_run_id"
    "),"
    "names AS ("
    "  SELECT DISTINCT ON (ticker) ticker, name, sector FROM universe_tickers"
    "  WHERE snapshot_id = (SELECT MAX(id) FROM universe_snapshots)"
    "  ORDER BY ticker, id ASC"
    "),"
    "cl AS ("
    "  SELECT ticker, cluster_id FROM candidate_clusters"
    "  WHERE run_id = (SELECT run_id FROM portfolio_runs WHERE status='success'"
    "                  ORDER BY completed_at DESC NULLS LAST LIMIT 1)"
    ")"
    "SELECT r.ticker, r.rank, r.composite_score, r.percentile, r.rank_date, r.regime,"
    "  n.name, n.sector, p.prior_rank, cl.cluster_id "
    "FROM rankings r "
    "LEFT JOIN prior p ON p.ticker = r.ticker "
    "LEFT JOIN names n ON n.ticker = r.ticker "
    "LEFT JOIN cl ON cl.ticker = r.ticker "
    "WHERE r.run_id = :run_id "
    "ORDER BY r.rank ASC LIMIT :limit"
)


@pytest_asyncio.fixture
async def seeded(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    prior_run = uuid.uuid4()
    latest_run = uuid.uuid4()
    f_prior = uuid.uuid4()
    f_latest = uuid.uuid4()
    sync_run = uuid.uuid4()
    today = date.today()
    yday = today - timedelta(days=1)
    # latest run: 5 ranked names. AAPL also held; NEWB is new this run (no prior_rank).
    latest = [("AAPL", 1, "Apple Inc"), ("MSFT", 2, "Microsoft Corp"),
              ("NVDA", 3, "NVIDIA Corp"), ("KEY", 4, "KeyCorp"), ("NEWB", 5, "Newbie Co")]
    prior = [("AAPL", 2), ("MSFT", 1), ("NVDA", 4), ("KEY", 3)]  # NEWB absent → prior_rank NULL

    async with eng.begin() as conn:
        await conn.execute(text(
            "TRUNCATE rankings, ranking_runs, factor_runs, universe_tickers, universe_snapshots, "
            "live_positions, alpaca_sync_runs RESTART IDENTITY CASCADE"))
        for frid in (f_prior, f_latest):
            await conn.execute(text(
                "INSERT INTO factor_runs (run_id, strategy_id, status, started_at) "
                "VALUES (:f,'quality_core_v1','success',NOW())"), {"f": frid})
        await conn.execute(text(
            "INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, status, rank_date,"
            " regime, universe_count, ranked_count, completed_at) "
            "VALUES (:r,:f,'quality_core_v1','success',:d,'bull_calm',4,4, NOW() - INTERVAL '1 day')"),
            {"r": prior_run, "f": f_prior, "d": yday})
        await conn.execute(text(
            "INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, status, rank_date,"
            " regime, universe_count, ranked_count, completed_at) "
            "VALUES (:r,:f,'quality_core_v1','success',:d,'bull_calm',5,5, NOW())"),
            {"r": latest_run, "f": f_latest, "d": today})
        await conn.execute(text(
            "INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count) "
            "VALUES ('TEST', :d, 5)"), {"d": today})
        for t, rk, nm in latest:
            await conn.execute(text(
                "INSERT INTO rankings (run_id, source_factor_run_id, strategy_id, regime, rank_date,"
                " ticker, rank, composite_score, percentile) "
                "VALUES (:r,:f,'quality_core_v1','bull_calm',:d,:t,:rk,1.0,0.5)"),
                {"r": latest_run, "f": f_latest, "d": today, "t": t, "rk": rk})
            await conn.execute(text(
                "INSERT INTO universe_tickers (snapshot_id, ticker, name) "
                "VALUES ((SELECT MAX(id) FROM universe_snapshots), :t, :nm)"), {"t": t, "nm": nm})
        for t, rk in prior:
            await conn.execute(text(
                "INSERT INTO rankings (run_id, source_factor_run_id, strategy_id, regime, rank_date,"
                " ticker, rank, composite_score, percentile) "
                "VALUES (:r,:f,'quality_core_v1','bull_calm',:d,:t,:rk,1.0,0.5)"),
                {"r": prior_run, "f": f_prior, "d": yday, "t": t, "rk": rk})
        # holdings: AAPL (ranked) + ZZZ (held-but-unranked → must be injected)
        await conn.execute(text(
            "INSERT INTO alpaca_sync_runs (run_id, status, completed_at) VALUES (:r,'success',NOW())"),
            {"r": sync_run})
        await conn.execute(text(
            "INSERT INTO live_positions (sync_run_id, ticker, qty, market_value) "
            "VALUES (:r,'AAPL',10,1500),(:r,'ZZZ',3,90)"), {"r": sync_run})
    yield eng, str(latest_run), str(prior_run)
    await eng.dispose()


async def _universe(eng, latest_run, prior_run, limit=5000):
    """Run the endpoint's SQL + mirror its light held-overlay/injection."""
    async with eng.connect() as conn:
        res = await conn.execute(text(_UNIVERSE_SQL),
                                 {"run_id": latest_run, "prior_run_id": prior_run, "limit": limit})
        rows = [dict(m) for m in res.mappings()]
        sync = (await conn.execute(text(
            "SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
            "ORDER BY completed_at DESC NULLS LAST LIMIT 1"))).fetchone()
        held = {}
        if sync:
            pos = await conn.execute(text(
                "SELECT lp.ticker, lp.qty, lp.market_value, ut.name FROM live_positions lp "
                "LEFT JOIN universe_tickers ut ON ut.ticker = lp.ticker "
                "  AND ut.snapshot_id = (SELECT MAX(id) FROM universe_snapshots) "
                "WHERE lp.sync_run_id = :r"), {"r": str(sync.run_id)})
            held = {p["ticker"]: dict(p) for p in pos.mappings()}
    present = set()
    for r in rows:
        r["held"] = r["ticker"] in held
        present.add(r["ticker"])
    for t, h in held.items():
        if t not in present:
            rows.append({"ticker": t, "rank": 9999, "held": True, "name": h["name"],
                         "not_in_universe": True})
    return rows


class TestUniverseRealDB:
    async def test_full_list_light_columns_and_order(self, seeded):
        eng, latest, prior = seeded
        rows = await _universe(eng, latest, prior)
        ranked = [r for r in rows if r["rank"] != 9999]
        assert [r["ticker"] for r in ranked] == ["AAPL", "MSFT", "NVDA", "KEY", "NEWB"]  # full, by rank
        a = next(r for r in rows if r["ticker"] == "AAPL")
        assert a["name"] == "Apple Inc"          # name join
        assert a["prior_rank"] == 2              # ▲▼ arrow data from prior run
        assert "cluster_id" in a                 # cheap column present (NULL here)
        # NO expensive overlay columns leaked into the light list:
        for heavy in ("rank_slope", "vetter_excluded", "excess_dd_21d", "market_cap"):
            assert heavy not in a

    async def test_new_ticker_has_null_prior_rank(self, seeded):
        eng, latest, prior = seeded
        rows = await _universe(eng, latest, prior)
        newb = next(r for r in rows if r["ticker"] == "NEWB")
        assert newb["prior_rank"] is None        # not in prior run → no arrow

    async def test_held_flagged_and_unranked_injected(self, seeded):
        eng, latest, prior = seeded
        rows = await _universe(eng, latest, prior)
        assert next(r for r in rows if r["ticker"] == "AAPL")["held"] is True
        zzz = next((r for r in rows if r["ticker"] == "ZZZ"), None)
        assert zzz is not None and zzz["rank"] == 9999 and zzz["not_in_universe"] is True
