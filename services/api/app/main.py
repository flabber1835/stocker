from __future__ import annotations
import asyncio
import os
import re
import traceback
import uuid
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
import httpx

from sqlalchemy.ext.asyncio import create_async_engine
from stock_strategy_shared.db import warm_up_db_in_background
from stock_strategy_shared.tracing import fmt_row

DATABASE_URL          = os.getenv("DATABASE_URL", "")
TRADE_EXECUTOR_URL    = os.getenv("TRADE_EXECUTOR_URL",    "http://trade-executor:8000")
ALPACA_SYNC_URL       = os.getenv("ALPACA_SYNC_URL",       "http://alpaca-sync:8000")
PIPELINE_URL          = os.getenv("PIPELINE_URL",          "http://pipeline:8000")
VETTER_URL            = os.getenv("VETTER_URL",            "http://llm-vetter:8000")
AV_INGESTOR_URL       = os.getenv("AV_INGESTOR_URL",       "http://av-ingestor:8000")
PORTFOLIO_BUILDER_URL = os.getenv("PORTFOLIO_BUILDER_URL", "http://portfolio-builder:8000")
SCHEDULER_URL         = os.getenv("SCHEDULER_URL",         "http://scheduler:8000")
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=7,
                             connect_args={"timeout": 60}) if DATABASE_URL else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATABASE_URL:
        raise RuntimeError("Missing required environment variable: DATABASE_URL")
    # Warm up DB in background so /health responds immediately. Blocking here
    # causes docker healthcheck failures + restart loop on slow NAS hardware.
    warm_up_db_in_background(engine, "api")
    yield


app = FastAPI(title="stocker-api", lifespan=lifespan)


_TICKER_RE = re.compile(r'^[A-Z0-9.\-]{1,10}$')


def _validate_ticker(ticker: str) -> str:
    """Normalize and validate a ticker symbol. Raises 400 on invalid format."""
    ticker = ticker.upper().strip()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail=f"Invalid ticker format: {ticker!r}")
    return ticker


def _linear_slope(ranks: list[float]) -> float | None:
    """OLS slope for an ordered sequence of rank values (x = 0, 1, 2, ...).

    Mirrors the SQL REGR_SLOPE(rank, row_number) logic used in /rankings.
    x indices are always equally-spaced integers — actual date gaps (weekends,
    holidays, missed runs) are intentionally collapsed so every recorded run
    counts as one step. Returns None for fewer than 2 points.
    """
    n = len(ranks)
    if n < 2:
        return None
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ranks) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ranks))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api"}


@app.get("/data-freshness")
async def data_freshness():
    """Return the latest timestamp for each data layer so the UI can display data age."""
    async with engine.connect() as conn:
        prices_row = (await conn.execute(text(
            "SELECT MAX(date) AS max_date, MAX(fetched_at) AS last_fetched FROM daily_prices"
        ))).mappings().first()

        funds_row = (await conn.execute(text(
            "SELECT MAX(as_of_date) AS max_date, MAX(fetched_at) AS last_fetched FROM fundamentals"
        ))).mappings().first()

        factors_row = (await conn.execute(text(
            "SELECT score_date, completed_at FROM factor_runs "
            "WHERE status='success' ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
        ))).mappings().first()

        rankings_row = (await conn.execute(text(
            "SELECT rank_date, completed_at FROM ranking_runs "
            "WHERE status='success' ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
        ))).mappings().first()

    def _iso(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else (str(v) if v else None)

    return {
        "prices": {
            "max_date":     _iso(prices_row["max_date"])     if prices_row else None,
            "last_fetched": _iso(prices_row["last_fetched"]) if prices_row else None,
        },
        "fundamentals": {
            "max_date":     _iso(funds_row["max_date"])     if funds_row else None,
            "last_fetched": _iso(funds_row["last_fetched"]) if funds_row else None,
        },
        "factors": {
            "score_date":   _iso(factors_row["score_date"])   if factors_row else None,
            "completed_at": _iso(factors_row["completed_at"]) if factors_row else None,
        },
        "rankings": {
            "rank_date":    _iso(rankings_row["rank_date"])    if rankings_row else None,
            "completed_at": _iso(rankings_row["completed_at"]) if rankings_row else None,
        },
    }


# ── Regime ────────────────────────────────────────────────────────────────────────────────────

@app.get("/regime")
async def get_regime():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT regime, spy_price, spy_sma_slow, spy_vs_sma, realized_vol, calculated_at "
                "FROM regime_snapshots ORDER BY snapshot_date DESC, calculated_at DESC LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        return {"regime": None}
    return fmt_row(result)


# ── Rankings ─────────────────────────────────────────────────────────────────────────────────

@app.get("/rankings")
async def get_rankings(limit: int = 50, run_id: str | None = None):
    async with engine.connect() as conn:
        if run_id:
            rows = await conn.execute(
                text(
                    "WITH recent_runs AS ("
                    "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos"
                    "  FROM ranking_runs WHERE status='success' ORDER BY rank_date DESC LIMIT 5"
                    "),"
                    "ticker_slopes AS ("
                    "  SELECT r.ticker,"
                    "    REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
                    "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
                    "  GROUP BY r.ticker"
                    ")"
                    "SELECT r.ticker, r.rank, r.composite_score, r.percentile, r.regime, r.rank_date,"
                    "  r.factor_scores, ts.rank_slope "
                    "FROM rankings r LEFT JOIN ticker_slopes ts ON ts.ticker = r.ticker "
                    "WHERE r.run_id = :run_id ORDER BY r.rank ASC LIMIT :limit"
                ),
                {"run_id": run_id, "limit": limit},
            )
        else:
            rows = await conn.execute(
                text(
                    "WITH recent_runs AS ("
                    "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos"
                    "  FROM ranking_runs WHERE status='success' ORDER BY rank_date DESC LIMIT 5"
                    "),"
                    "ticker_slopes AS ("
                    "  SELECT r.ticker,"
                    "    REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
                    "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
                    "  GROUP BY r.ticker"
                    ")"
                    "SELECT r.ticker, r.rank, r.composite_score, r.percentile, r.regime, r.rank_date,"
                    "  r.factor_scores, ts.rank_slope "
                    "FROM rankings r LEFT JOIN ticker_slopes ts ON ts.ticker = r.ticker "
                    "WHERE r.run_id = ("
                    "  SELECT run_id FROM ranking_runs WHERE status='success'"
                    "  ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
                    ") ORDER BY r.rank ASC LIMIT :limit"
                ),
                {"limit": limit},
            )
        results = [dict(r) for r in rows.mappings()]
    if not results:
        return {"count": 0, "rankings": []}
    return {"count": len(results), "rankings": results}


@app.get("/rankings/with-overlays")
async def get_rankings_with_overlays(limit: int = 100):
    """
    Latest rank run, top `limit` tickers, plus per-ticker overlay flags:
    - prior_rank: rank in the immediately-prior successful rank run (for arrows)
    - rank_slope: REGR_SLOPE over the last 5 runs (existing momentum metric)
    - vetter_excluded: bool, with reason/confidence/risk_type if true
    - positive_catalyst: bool, with positive_reason if true
    - held: bool, with qty and market_value if true

    Single round-trip — assembled in one CTE-based query so the dashboard can
    drop the separate /universe + /rankings calls. Powers the consolidated
    Rankings panel.
    """
    async with engine.connect() as conn:
        # Find the latest successful rank run + its prior peer
        run_rows = (await conn.execute(text(
            "SELECT run_id, rank_date FROM ranking_runs WHERE status='success' "
            "ORDER BY rank_date DESC, completed_at DESC NULLS LAST LIMIT 2"
        ))).fetchall()
        if not run_rows:
            return {"count": 0, "run": None, "prior_run": None, "rankings": []}
        latest_run_id = str(run_rows[0].run_id)
        prior_run_id = str(run_rows[1].run_id) if len(run_rows) > 1 else None

        # Latest vetter run (any status — UI surfaces in-progress info too)
        vetter_row = (await conn.execute(text(
            "SELECT run_id FROM vetter_runs "
            "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
        ))).fetchone()
        vetter_run_id = str(vetter_row.run_id) if vetter_row else None

        # Latest successful alpaca-sync (for live positions)
        sync_row = (await conn.execute(text(
            "SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
            "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        ))).fetchone()
        sync_run_id = str(sync_row.run_id) if sync_row else None

        # Main rankings query
        rows = await conn.execute(
            text(
                "WITH recent_runs AS ("
                "  SELECT run_id, ROW_NUMBER() OVER (ORDER BY rank_date ASC) - 1 AS x_pos"
                "  FROM ranking_runs WHERE status='success' ORDER BY rank_date DESC LIMIT 5"
                "),"
                "ticker_slopes AS ("
                "  SELECT r.ticker,"
                "    REGR_SLOPE(r.rank::double precision, rr.x_pos::double precision) AS rank_slope"
                "  FROM rankings r JOIN recent_runs rr ON rr.run_id = r.run_id"
                "  GROUP BY r.ticker"
                "),"
                "prior_ranks AS ("
                "  SELECT ticker, rank AS prior_rank FROM rankings WHERE run_id = :prior_run_id"
                "),"
                "names AS ("
                "  SELECT ticker, name, sector FROM universe_tickers"
                "  WHERE snapshot_id = (SELECT MAX(id) FROM universe_snapshots)"
                ")"
                "SELECT r.ticker, r.rank, r.composite_score, r.percentile, r.regime, r.rank_date,"
                "  r.factor_scores, ts.rank_slope, pr.prior_rank, n.name, n.sector "
                "FROM rankings r "
                "LEFT JOIN ticker_slopes ts ON ts.ticker = r.ticker "
                "LEFT JOIN prior_ranks pr ON pr.ticker = r.ticker "
                "LEFT JOIN names n ON n.ticker = r.ticker "
                "WHERE r.run_id = :run_id "
                "ORDER BY r.rank ASC LIMIT :limit"
            ),
            {"run_id": latest_run_id, "prior_run_id": prior_run_id or latest_run_id,
             "limit": limit},
        )
        ranking_rows = [dict(r) for r in rows.mappings()]
        tickers = [r["ticker"] for r in ranking_rows]
        if not tickers:
            return {"count": 0, "run": None, "prior_run": None, "rankings": []}

        # Vetter overlay (only for ranked tickers — broker-injected rows get overlaid below)
        vetter_by_ticker = {}
        if vetter_run_id:
            vd_rows = await conn.execute(
                text(
                    "SELECT ticker, exclude, confidence, risk_type, reason, "
                    "  positive_catalyst, positive_reason "
                    "FROM vetter_decisions WHERE run_id = :rid AND ticker = ANY(:tickers)"
                ),
                {"rid": vetter_run_id, "tickers": tickers},
            )
            for v in vd_rows.mappings():
                vetter_by_ticker[v["ticker"]] = dict(v)

        # Holdings overlay — load ALL live broker positions, not just those in rankings.
        # Broker-held tickers that failed universe/ranking filters are injected below
        # so the user can always see what they hold, even if the system can't rank it.
        all_broker_positions: dict[str, dict] = {}
        if sync_run_id:
            pos_rows = await conn.execute(
                text(
                    "SELECT lp.ticker, lp.qty, lp.market_value, lp.unrealized_plpc, "
                    "  ut.name, ut.sector "
                    "FROM live_positions lp "
                    "LEFT JOIN universe_tickers ut ON ut.ticker = lp.ticker "
                    "  AND ut.snapshot_id = (SELECT MAX(id) FROM universe_snapshots) "
                    "WHERE lp.sync_run_id = :rid"
                ),
                {"rid": sync_run_id},
            )
            for p in pos_rows.mappings():
                all_broker_positions[p["ticker"]] = {
                    "qty": float(p["qty"]) if p["qty"] is not None else None,
                    "market_value": float(p["market_value"]) if p["market_value"] is not None else None,
                    "unrealized_plpc": float(p["unrealized_plpc"]) if p["unrealized_plpc"] is not None else None,
                    "name": p["name"],
                    "sector": p["sector"],
                }

        # Inject broker-held tickers absent from rankings as rank=9999 rows.
        # These are positions the pipeline filtered out (no data, below liquidity threshold,
        # insufficient history, etc.). They must still appear so the user can see them.
        ranked_set = set(tickers)
        run_date_val = ranking_rows[0]["rank_date"] if ranking_rows else None
        for broker_ticker, pos in all_broker_positions.items():
            if broker_ticker in ranked_set:
                continue
            injected = {
                "ticker": broker_ticker,
                "rank": 9999,
                "composite_score": None,
                "percentile": None,
                "regime": None,
                "rank_date": run_date_val,
                "factor_scores": None,
                "rank_slope": None,
                "prior_rank": None,
                "name": pos.get("name"),
                "sector": pos.get("sector"),
                "not_in_universe": True,
            }
            ranking_rows.append(injected)

        # Merge vetter + holdings overlays — always set all fields so schema is stable
        for r in ranking_rows:
            t = r["ticker"]
            v = vetter_by_ticker.get(t)
            if v:
                r["vetter_excluded"] = bool(v["exclude"])
                r["vetter_confidence"] = v["confidence"]
                r["vetter_risk_type"] = v["risk_type"]
                r["vetter_reason"] = v["reason"]
                r["positive_catalyst"] = bool(v["positive_catalyst"])
                r["positive_reason"] = v["positive_reason"]
            else:
                r["vetter_excluded"] = False
                r["vetter_confidence"] = None
                r["vetter_risk_type"] = None
                r["vetter_reason"] = None
                r["positive_catalyst"] = False
                r["positive_reason"] = None
            pos = all_broker_positions.get(t)
            r["held"] = pos is not None
            if pos:
                r["qty"] = pos["qty"]
                r["market_value"] = pos["market_value"]
                r["unrealized_plpc"] = pos["unrealized_plpc"]
            # Ensure not_in_universe is always present
            r.setdefault("not_in_universe", False)

    return {
        "count": len(ranking_rows),
        "run": {"run_id": latest_run_id, "rank_date":
                ranking_rows[0]["rank_date"].isoformat() if hasattr(ranking_rows[0]["rank_date"], "isoformat")
                else str(ranking_rows[0]["rank_date"])},
        "prior_run": {"run_id": prior_run_id} if prior_run_id else None,
        "vetter_run_id": vetter_run_id,
        "sync_run_id": sync_run_id,
        "rankings": ranking_rows,
    }


# ── Universe ───────────────────────────────────────────────────────────────────────────────────

@app.get("/universe")
async def get_universe():
    async with engine.connect() as conn:
        snap = await conn.execute(
            text(
                "SELECT id, etf_ticker, snapshot_date, ticker_count, fetched_at "
                "FROM universe_snapshots ORDER BY fetched_at DESC LIMIT 1"
            )
        )
        snapshot = snap.mappings().first()
        if snapshot is None:
            raise HTTPException(404, "No universe data yet. Run: make universe")
        tickers = await conn.execute(
            text(
                "SELECT ticker, name, weight_pct, sector "
                "FROM universe_tickers WHERE snapshot_id = :sid ORDER BY weight_pct DESC NULLS LAST"
            ),
            {"sid": snapshot["id"]},
        )
        ticker_list = [dict(r) for r in tickers.mappings()]
    return {"snapshot": dict(snapshot), "tickers": ticker_list}


@app.get("/universe/investable")
async def get_investable_universe():
    """Return the investable universe — tickers that passed price/liquidity filters in the
    latest successful factor run.  These are the exact tickers whose z-scores were computed
    cross-sectionally together, so this list is the true peer group for ranking purposes.
    Returns 404 when no successful factor run exists yet (cold start)."""
    async with engine.connect() as conn:
        run_row = await conn.execute(
            text(
                "SELECT run_id, score_date, ticker_count, regime "
                "FROM factor_runs WHERE status='success' "
                "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
            )
        )
        run = run_row.mappings().first()
        if run is None:
            raise HTTPException(
                404,
                "No successful factor run yet — run fetch-data then factor-calculate first.",
            )
        tickers_row = await conn.execute(
            text(
                "SELECT fs.ticker, ut.name, ut.sector "
                "FROM factor_scores fs "
                "LEFT JOIN universe_tickers ut "
                "  ON ut.ticker = fs.ticker "
                "  AND ut.snapshot_id = (SELECT MAX(id) FROM universe_snapshots) "
                "WHERE fs.run_id = :rid "
                "ORDER BY fs.ticker ASC"
            ),
            {"rid": run["run_id"]},
        )
        ticker_list = [dict(r) for r in tickers_row.mappings()]
    return {
        "source": "factor_scores",
        "factor_run_id": str(run["run_id"]),
        "score_date": str(run["score_date"]) if run["score_date"] else None,
        "regime": run["regime"],
        "ticker_count": len(ticker_list),
        "tickers": ticker_list,
    }


# ── Factor scores ────────────────────────────────────────────────────────────────────────────

@app.get("/factors/{ticker}")
async def get_factors(ticker: str):
    ticker = _validate_ticker(ticker)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT run_id, ticker, score_date, momentum, quality, value, growth, "
                "low_volatility, liquidity, calculated_at "
                "FROM factor_scores WHERE ticker = :ticker ORDER BY calculated_at DESC LIMIT 5"
            ),
            {"ticker": ticker.upper()},
        )
        results = [dict(r) for r in rows.mappings()]
    if not results:
        raise HTTPException(404, f"No factor scores for {ticker}")
    return results


# ── Factor runs ─────────────────────────────────────────────────────────────────────────────

@app.get("/factor-runs")
async def list_factor_runs(limit: int = 20):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT run_id, trace_id, strategy_id, config_hash, status, regime, "
                "       score_date, ticker_count, warning_count, universe_snapshot_id, "
                "       price_data_max_date, started_at, completed_at, error_message "
                "FROM factor_runs ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        results = rows.mappings().fetchall()
    return [
        {
            "run_id": str(r["run_id"]),
            "trace_id": str(r["trace_id"]) if r["trace_id"] else None,
            "strategy_id": r["strategy_id"],
            "config_hash": r["config_hash"],
            "status": r["status"],
            "regime": r["regime"],
            "score_date": str(r["score_date"]) if r["score_date"] else None,
            "ticker_count": r["ticker_count"],
            "warning_count": r["warning_count"],
            "universe_snapshot_id": r["universe_snapshot_id"],
            "price_data_max_date": str(r["price_data_max_date"]) if r["price_data_max_date"] else None,
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "error_message": r["error_message"],
        }
        for r in results
    ]


# ── Ranking runs ─────────────────────────────────────────────────────────────────────────────

@app.get("/ranking-runs")
async def list_ranking_runs(limit: int = 20):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT run_id, trace_id, source_factor_run_id, strategy_id, config_hash, "
                "       regime, rank_date, status, universe_count, ranked_count, dropped_count, "
                "       started_at, completed_at, error_message "
                "FROM ranking_runs ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        results = rows.mappings().fetchall()
    return [
        {
            "run_id": str(r["run_id"]),
            "trace_id": str(r["trace_id"]) if r["trace_id"] else None,
            "source_factor_run_id": str(r["source_factor_run_id"]),
            "strategy_id": r["strategy_id"],
            "config_hash": r["config_hash"],
            "regime": r["regime"],
            "rank_date": str(r["rank_date"]) if r["rank_date"] else None,
            "status": r["status"],
            "universe_count": r["universe_count"],
            "ranked_count": r["ranked_count"],
            "dropped_count": r["dropped_count"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "error_message": r["error_message"],
        }
        for r in results
    ]


# ── Execution traces ───────────────────────────────────────────────────────────────────────────

@app.get("/traces")
async def list_traces(limit: int = 20):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT trace_id, job_type, status, root_run_id, strategy_id, config_hash, "
                "       started_at, completed_at, notes "
                "FROM execution_traces ORDER BY started_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        results = rows.mappings().fetchall()
    return [
        {
            "trace_id": str(r["trace_id"]),
            "job_type": r["job_type"],
            "status": r["status"],
            "root_run_id": str(r["root_run_id"]) if r["root_run_id"] else None,
            "strategy_id": r["strategy_id"],
            "config_hash": r["config_hash"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "notes": r["notes"],
        }
        for r in results
    ]


@app.get("/traces/{trace_id}")
async def get_trace(trace_id: str):
    try:
        uuid.UUID(trace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid trace_id format: {trace_id!r}")
    async with engine.connect() as conn:
        trace_row = await conn.execute(
            text(
                "SELECT trace_id, job_type, status, root_run_id, strategy_id, config_hash, "
                "       started_at, completed_at, notes "
                "FROM execution_traces WHERE trace_id = :tid"
            ),
            {"tid": trace_id},
        )
        trace = trace_row.mappings().first()
        if trace is None:
            raise HTTPException(404, f"Trace {trace_id} not found")

        steps_rows = await conn.execute(
            text(
                "SELECT step_id, service, step_name, status, started_at, completed_at, "
                "       input_summary, output_summary, warnings, error_message "
                "FROM execution_steps WHERE trace_id = :tid ORDER BY started_at ASC"
            ),
            {"tid": trace_id},
        )
        steps = steps_rows.mappings().fetchall()

        linked_factor_run = None
        linked_ranking_run = None
        linked_portfolio_run = None
        root_run_id = trace["root_run_id"]

        if root_run_id and trace["job_type"] == "factor_run":
            fr = await conn.execute(
                text(
                    "SELECT run_id, status, regime, score_date, ticker_count, warning_count, "
                    "       config_hash, universe_snapshot_id, price_data_max_date "
                    "FROM factor_runs WHERE run_id = :rid"
                ),
                {"rid": str(root_run_id)},
            )
            row = fr.mappings().first()
            if row:
                linked_factor_run = fmt_row(row)
            # Find the ranking run that consumed this factor run as input
            rr = await conn.execute(
                text(
                    "SELECT run_id, status, regime, rank_date, universe_count, ranked_count, dropped_count "
                    "FROM ranking_runs WHERE source_factor_run_id = :frid "
                    "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
                ),
                {"frid": str(root_run_id)},
            )
            rr_row = rr.mappings().first()
            if rr_row:
                linked_ranking_run = fmt_row(rr_row)

        if root_run_id and trace["job_type"] == "rank_run":
            rr = await conn.execute(
                text(
                    "SELECT run_id, status, regime, rank_date, universe_count, ranked_count, "
                    "       dropped_count, source_factor_run_id "
                    "FROM ranking_runs WHERE run_id = :rid"
                ),
                {"rid": str(root_run_id)},
            )
            row = rr.mappings().first()
            if row:
                linked_ranking_run = fmt_row(row)

        if root_run_id and trace["job_type"] == "portfolio_run":
            pr = await conn.execute(
                text(
                    "SELECT run_id, status, regime, portfolio_date, candidate_count, selected_count, "
                    "       avg_pairwise_correlation, portfolio_estimated_vol, source_ranking_run_id "
                    "FROM portfolio_runs WHERE run_id = :rid"
                ),
                {"rid": str(root_run_id)},
            )
            row = pr.mappings().first()
            if row:
                linked_portfolio_run = fmt_row(row)

    def _fmt_step(s):
        return {
            "step_id": str(s["step_id"]),
            "service": s["service"],
            "step_name": s["step_name"],
            "status": s["status"],
            "started_at": s["started_at"].isoformat() if s["started_at"] else None,
            "completed_at": s["completed_at"].isoformat() if s["completed_at"] else None,
            "input_summary": s["input_summary"],
            "output_summary": s["output_summary"],
            "warnings": s["warnings"],
            "error_message": s["error_message"],
        }

    return {
        "trace_id": str(trace["trace_id"]),
        "job_type": trace["job_type"],
        "status": trace["status"],
        "root_run_id": str(trace["root_run_id"]) if trace["root_run_id"] else None,
        "strategy_id": trace["strategy_id"],
        "config_hash": trace["config_hash"],
        "started_at": trace["started_at"].isoformat() if trace["started_at"] else None,
        "completed_at": trace["completed_at"].isoformat() if trace["completed_at"] else None,
        "notes": trace["notes"],
        "factor_run": linked_factor_run,
        "ranking_run": linked_ranking_run,
        "portfolio_run": linked_portfolio_run,
        "steps": [_fmt_step(s) for s in steps],
    }


# ── Portfolio ─────────────────────────────────────────────────────────────────────────────────

@app.get("/portfolio")
async def get_portfolio(run_id: str | None = None):
    async with engine.connect() as conn:
        if run_id:
            run_row = await conn.execute(
                text(
                    "SELECT run_id, trace_id, source_ranking_run_id, strategy_id, config_hash, "
                    "       regime, portfolio_date, status, candidate_count, selected_count, "
                    "       covariance_window_days, avg_pairwise_correlation, portfolio_estimated_vol, "
                    "       error_message, started_at, completed_at "
                    "FROM portfolio_runs WHERE run_id = :rid"
                ),
                {"rid": run_id},
            )
        else:
            run_row = await conn.execute(
                text(
                    "SELECT run_id, trace_id, source_ranking_run_id, strategy_id, config_hash, "
                    "       regime, portfolio_date, status, candidate_count, selected_count, "
                    "       covariance_window_days, avg_pairwise_correlation, portfolio_estimated_vol, "
                    "       error_message, started_at, completed_at "
                    "FROM portfolio_runs WHERE status = 'success' "
                    "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
                )
            )
        run = run_row.mappings().first()
        if run is None:
            return {"run": None, "holdings": []}
        holdings_rows = await conn.execute(
            text(
                "SELECT ticker, position, weight, composite_score, original_rank, "
                "       adj_score, portfolio_vol_at_add "
                "FROM portfolio_holdings WHERE run_id = :rid ORDER BY position ASC"
            ),
            {"rid": str(run["run_id"])},
        )
        holdings = [dict(r) for r in holdings_rows.mappings()]

    return {
        "run": {
            "run_id": str(run["run_id"]),
            "trace_id": str(run["trace_id"]) if run["trace_id"] else None,
            "source_ranking_run_id": str(run["source_ranking_run_id"]),
            "strategy_id": run["strategy_id"],
            "config_hash": run["config_hash"],
            "regime": run["regime"],
            "portfolio_date": str(run["portfolio_date"]) if run["portfolio_date"] else None,
            "status": run["status"],
            "candidate_count": run["candidate_count"],
            "selected_count": run["selected_count"],
            "covariance_window_days": run["covariance_window_days"],
            "avg_pairwise_correlation": float(run["avg_pairwise_correlation"]) if run["avg_pairwise_correlation"] is not None else None,
            "portfolio_estimated_vol": float(run["portfolio_estimated_vol"]) if run["portfolio_estimated_vol"] is not None else None,
            "error_message": run["error_message"],
            "started_at": run["started_at"].isoformat() if run["started_at"] else None,
            "completed_at": run["completed_at"].isoformat() if run["completed_at"] else None,
        },
        "holdings": [
            {
                "ticker": h["ticker"],
                "position": h["position"],
                "weight": float(h["weight"]),
                "composite_score": float(h["composite_score"]) if h["composite_score"] is not None else None,
                "original_rank": h["original_rank"],
                "adj_score": float(h["adj_score"]) if h["adj_score"] is not None else None,
                "portfolio_vol_at_add": float(h["portfolio_vol_at_add"]) if h["portfolio_vol_at_add"] is not None else None,
            }
            for h in holdings
        ],
    }


# ── Live portfolio (broker positions via alpaca-sync) ─────────────────────────

@app.get("/live-portfolio")
async def get_live_portfolio():
    def _iso(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else (str(v) if v else None)

    def _f(v):
        return float(v) if v is not None else None

    try:
        async with engine.connect() as conn:
            sync_row = (await conn.execute(text(
                "SELECT run_id, status, account_value, buying_power, cash, "
                "position_count, completed_at "
                "FROM alpaca_sync_runs WHERE status='success' "
                "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
            ))).mappings().first()

            if sync_row is None:
                return {"connected": False, "positions": [], "sync": None}

            pos_rows = (await conn.execute(text(
                "SELECT ticker, qty, avg_entry_price, current_price, market_value, "
                "cost_basis, unrealized_pl, unrealized_plpc, side, "
                "lastday_price, change_today "
                "FROM live_positions WHERE sync_run_id = :rid "
                "ORDER BY market_value DESC NULLS LAST"
            ), {"rid": str(sync_row["run_id"])})).mappings().fetchall()

        positions = []
        for p in pos_rows:
            qty = _f(p["qty"])
            current_price = _f(p["current_price"])
            lastday_price = _f(p.get("lastday_price"))
            change_today  = _f(p.get("change_today"))
            day_pl = None
            if qty is not None and current_price is not None and lastday_price is not None:
                day_pl = qty * (current_price - lastday_price)
            positions.append({
                "ticker":          p["ticker"],
                "qty":             qty,
                "avg_entry_price": _f(p["avg_entry_price"]),
                "current_price":   current_price,
                "market_value":    _f(p["market_value"]),
                "cost_basis":      _f(p["cost_basis"]),
                "unrealized_pl":   _f(p["unrealized_pl"]),
                "unrealized_plpc": _f(p["unrealized_plpc"]),
                "lastday_price":   lastday_price,
                "change_today":    change_today,
                "day_pl":          day_pl,
                "weight":          None,
                "side":            p["side"],
            })
        total_long_mv = sum(p["market_value"] for p in positions if p["market_value"] is not None and p["market_value"] > 0)
        total_short_mv = sum(abs(p["market_value"]) for p in positions if p["market_value"] is not None and p["market_value"] < 0)
        for p in positions:
            mv = p["market_value"]
            if mv is None:
                p["weight"] = None
            elif mv >= 0:
                p["weight"] = mv / total_long_mv if total_long_mv > 0 else 0.0
            else:
                p["weight"] = -abs(mv) / total_short_mv if total_short_mv > 0 else 0.0
        return {
            "connected": True,
            "sync": {
                "synced_at":     _iso(sync_row["completed_at"]),
                "account_value": _f(sync_row["account_value"]),
                "buying_power":  _f(sync_row["buying_power"]),
                "cash":          _f(sync_row["cash"]),
                "position_count": sync_row["position_count"],
            },
            "positions": positions,
        }
    except Exception:
        print(f"[api] get_live_portfolio error: {traceback.format_exc()}")
        return {"connected": False, "positions": [], "sync": None}


# ── Delta engine intents ───────────────────────────────────────────────────────

@app.get("/delta/latest")
async def get_delta_latest():
    def _iso(v):
        return v.isoformat() if v and hasattr(v, "isoformat") else (str(v) if v else None)
    def _f(v):
        return float(v) if v is not None else None

    try:
        async with engine.connect() as conn:
            run_row = (await conn.execute(text(
                "SELECT run_id, status, run_date, entry_rank, exit_rank, "
                "confirmation_days, max_positions, current_portfolio_size, "
                "entries_count, exits_count, holds_count, watches_count, "
                "at_risk_count, buy_add_count, sell_trim_count, "
                "triggered_by, started_at, completed_at, error_message "
                "FROM delta_runs "
                "ORDER BY CASE WHEN triggered_by = 'scheduler' THEN 0 ELSE 1 END, "
                "  started_at DESC LIMIT 1"
            ))).mappings().first()

            if run_row is None:
                return {"run": None, "intents": []}

            run_id = str(run_row["run_id"])
            intent_rows = (await conn.execute(text(
                "SELECT di.id, di.ticker, di.action, di.rank, di.composite_score, "
                "di.confirmation_days_met, di.current_weight, di.actual_weight, "
                "di.weight_drift, di.reason, "
                "ao.status AS order_status "
                "FROM delta_intents di "
                "LEFT JOIN LATERAL ("
                "  SELECT status FROM alpaca_orders "
                "  WHERE intent_id = di.id "
                "  ORDER BY created_at DESC LIMIT 1"
                ") ao ON true "
                "WHERE di.run_id = :rid "
                "ORDER BY di.action, di.rank ASC NULLS LAST, di.ticker"
            ), {"rid": run_id})).mappings().fetchall()

            # Vetter overlay — join most recent successful vetter run onto each intent.
            vetter_by_ticker: dict[str, dict] = {}
            tickers = [r["ticker"] for r in intent_rows]
            if tickers:
                vr = (await conn.execute(text(
                    "SELECT run_id FROM vetter_runs WHERE status='success' "
                    "ORDER BY started_at DESC LIMIT 1"
                ))).mappings().first()
                if vr:
                    vd_rows = (await conn.execute(text(
                        "SELECT ticker, exclude, confidence, risk_type, reason, "
                        "  positive_catalyst, positive_reason "
                        "FROM vetter_decisions WHERE run_id = :rid AND ticker = ANY(:tickers)"
                    ), {"rid": str(vr["run_id"]), "tickers": tickers})).mappings().fetchall()
                    for v in vd_rows:
                        vetter_by_ticker[v["ticker"]] = dict(v)

        return {
            "run": {
                "run_id":                str(run_row["run_id"]),
                "status":                run_row["status"],
                "run_date":              str(run_row["run_date"]) if run_row["run_date"] else None,
                "entry_rank":            run_row["entry_rank"],
                "exit_rank":             run_row["exit_rank"],
                "confirmation_days":     run_row["confirmation_days"],
                "max_positions":         run_row["max_positions"],
                "current_portfolio_size": run_row["current_portfolio_size"],
                "entries_count":         run_row["entries_count"],
                "exits_count":           run_row["exits_count"],
                "holds_count":           run_row["holds_count"],
                "watches_count":         run_row["watches_count"],
                "at_risk_count":         run_row["at_risk_count"],
                "buy_add_count":         run_row["buy_add_count"],
                "sell_trim_count":       run_row["sell_trim_count"],
                "triggered_by":          run_row["triggered_by"],
                "started_at":            _iso(run_row["started_at"]),
                "completed_at":          _iso(run_row["completed_at"]),
                "error_message":         run_row["error_message"],
            },
            "intents": [
                {
                    "id":                    str(r["id"]),
                    "ticker":                r["ticker"],
                    "action":                r["action"],
                    "rank":                  r["rank"],
                    "composite_score":       _f(r["composite_score"]),
                    "confirmation_days_met": r["confirmation_days_met"],
                    "current_weight":        _f(r["current_weight"]),
                    "actual_weight":         _f(r["actual_weight"]),
                    "weight_drift":          _f(r["weight_drift"]),
                    "reason":                r["reason"],
                    "order_status":          r["order_status"],
                    "vetter_excluded":       vetter_by_ticker.get(r["ticker"], {}).get("exclude"),
                    "vetter_confidence":     vetter_by_ticker.get(r["ticker"], {}).get("confidence"),
                    "vetter_risk_type":      vetter_by_ticker.get(r["ticker"], {}).get("risk_type"),
                    "vetter_reason":         vetter_by_ticker.get(r["ticker"], {}).get("reason"),
                    "vetter_positive_catalyst": vetter_by_ticker.get(r["ticker"], {}).get("positive_catalyst"),
                    "vetter_positive_reason":   vetter_by_ticker.get(r["ticker"], {}).get("positive_reason"),
                }
                for r in intent_rows
            ],
        }
    except Exception:
        print(f"[api] get_delta_latest error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to fetch delta data")


# ── System status aggregation ─────────────────────────────────────────────────

@app.get("/system/status")
async def system_status():
    """Aggregate status from pipeline, vetter, av-ingestor, portfolio-builder, and scheduler.

    Each sub-call is independent: one failure does not affect the others.
    Returns a dict with keys: pipeline, vetter, ingestor, portfolio_builder, scheduler.
    Each value is the parsed JSON from the service's status endpoint, or
    {"error": "unavailable"} on any exception or non-200 response.
    """
    async def _fetch(url: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.json()
                return {"error": "unavailable"}
        except Exception:
            return {"error": "unavailable"}

    pipeline_result, vetter_result, ingestor_result, portfolio_builder_result, scheduler_result = \
        await asyncio.gather(
            _fetch(f"{PIPELINE_URL}/runs/latest"),
            _fetch(f"{VETTER_URL}/runs/latest"),
            _fetch(f"{AV_INGESTOR_URL}/runs/latest"),
            _fetch(f"{PORTFOLIO_BUILDER_URL}/runs/latest"),
            _fetch(f"{SCHEDULER_URL}/status"),
        )

    return {
        "pipeline":         pipeline_result,
        "vetter":           vetter_result,
        "ingestor":         ingestor_result,
        "portfolio_builder": portfolio_builder_result,
        "scheduler":        scheduler_result,
    }


# ── Alpaca sync proxy ──────────────────────────────────────────────────────────
# Routes the dashboard's sync request through the API so the dashboard doesn't
# need its own ALPACA_SYNC_URL env var. Internal services still call alpaca-sync
# directly when they need to.

@app.post("/alpaca/sync")
async def trigger_alpaca_sync():
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{ALPACA_SYNC_URL}/jobs/sync")
            return r.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"alpaca-sync unavailable: {exc}")


# ── Trade approval (thin proxy) ───────────────────────────────────────────────
# All sizing, risk-checking, Alpaca submission, and audit logging live in the
# trade-executor service. The API only validates the request, performs an early
# idempotency check (so duplicate clicks fail fast with a 409 instead of
# touching downstream services), and forwards.

class TradeApproveRequest(BaseModel):
    intent_id: str    # delta_intents.id (UUID)
    mode: Literal["immediate", "scheduled"]


@app.post("/trade/approve")
async def approve_trade(req: TradeApproveRequest):
    try:
        uuid.UUID(req.intent_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="intent_id must be a UUID")

    try:
        async with engine.connect() as conn:
            existing = (await conn.execute(text(
                "SELECT id, status FROM alpaca_orders "
                "WHERE intent_id = :iid AND status IN ('pending','submitted','risk_rejected') "
                "LIMIT 1"
            ), {"iid": req.intent_id})).mappings().first()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"Intent {req.intent_id} already has an open order ({existing['status']})",
                )

        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{TRADE_EXECUTOR_URL}/jobs/submit",
                json={"intent_id": req.intent_id, "mode": req.mode},
            )
        return JSONResponse(content=r.json(), status_code=r.status_code)

    except HTTPException:
        raise
    except Exception:
        print(f"[api] approve_trade error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Trade approval failed")
