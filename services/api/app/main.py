from __future__ import annotations
import os
import re
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=7)

app = FastAPI(title="stocker-api")


def _fmt_row(row) -> dict:
    """Serialize a DB row: UUIDs and datetimes → str, everything else unchanged."""
    return {k: str(v) if hasattr(v, "hex") or hasattr(v, "isoformat") else v
            for k, v in dict(row).items()}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api"}


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
        result = row.mappings().first()
    if result is None:
        raise HTTPException(404, "No regime data yet. Run: make factors")
    return dict(result)


# ── Rankings ─────────────────────────────────────────────────────────────────────────────────

@app.get("/rankings")
async def get_rankings(limit: int = 50, run_id: str | None = None):
    async with engine.connect() as conn:
        if run_id:
            rows = await conn.execute(
                text(
                    "SELECT ticker, rank, composite_score, percentile, regime, rank_date, factor_scores "
                    "FROM rankings WHERE run_id = :run_id ORDER BY rank ASC LIMIT :limit"
                ),
                {"run_id": run_id, "limit": limit},
            )
        else:
            rows = await conn.execute(
                text(
                    "SELECT ticker, rank, composite_score, percentile, regime, rank_date, factor_scores "
                    "FROM rankings WHERE run_id = ("
                    "  SELECT run_id FROM rankings ORDER BY ranked_at DESC LIMIT 1"
                    ") ORDER BY rank ASC LIMIT :limit"
                ),
                {"limit": limit},
            )
        results = [dict(r) for r in rows.mappings()]
    if not results:
        raise HTTPException(404, "No rankings yet. Run: make pipeline")
    return {"count": len(results), "rankings": results}


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


# ── Factor scores ────────────────────────────────────────────────────────────────────────────

@app.get("/factors/{ticker}")
async def get_factors(ticker: str):
    if not re.match(r'^[A-Z0-9.\-]{1,10}$', ticker):
        raise HTTPException(status_code=400, detail=f"Invalid ticker format: {ticker}")
    ticker = ticker.upper()
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
                linked_factor_run = _fmt_row(row)
            # Find the ranking run that consumed this factor run as input
            rr = await conn.execute(
                text(
                    "SELECT run_id, status, regime, rank_date, universe_count, ranked_count, dropped_count "
                    "FROM ranking_runs WHERE source_factor_run_id = :frid "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"frid": str(root_run_id)},
            )
            rr_row = rr.mappings().first()
            if rr_row:
                linked_ranking_run = _fmt_row(rr_row)

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
                linked_ranking_run = _fmt_row(row)

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
                linked_portfolio_run = _fmt_row(row)

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
                    "ORDER BY completed_at DESC LIMIT 1"
                )
            )
        run = run_row.mappings().first()
        if run is None:
            raise HTTPException(404, "No portfolio yet. Run: make portfolio")
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
                "cost_basis, unrealized_pl, unrealized_plpc, side "
                "FROM live_positions WHERE sync_run_id = :rid "
                "ORDER BY market_value DESC NULLS LAST"
            ), {"rid": str(sync_row["run_id"])})).mappings().fetchall()

        total_mv = sum(float(p["market_value"] or 0) for p in pos_rows)
        return {
            "connected": True,
            "sync": {
                "synced_at":     _iso(sync_row["completed_at"]),
                "account_value": _f(sync_row["account_value"]),
                "buying_power":  _f(sync_row["buying_power"]),
                "cash":          _f(sync_row["cash"]),
                "position_count": sync_row["position_count"],
            },
            "positions": [
                {
                    "ticker":          p["ticker"],
                    "qty":             _f(p["qty"]),
                    "avg_entry_price": _f(p["avg_entry_price"]),
                    "current_price":   _f(p["current_price"]),
                    "market_value":    _f(p["market_value"]),
                    "cost_basis":      _f(p["cost_basis"]),
                    "unrealized_pl":   _f(p["unrealized_pl"]),
                    "unrealized_plpc": _f(p["unrealized_plpc"]),
                    "weight":          float(p["market_value"]) / total_mv if total_mv and p["market_value"] else None,
                    "side":            p["side"],
                }
                for p in pos_rows
            ],
        }
    except Exception:
        # Tables may not exist if alpaca-sync has never run
        return {"connected": False, "positions": [], "sync": None}
