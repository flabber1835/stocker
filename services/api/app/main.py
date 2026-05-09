from __future__ import annotations
import os
from typing import Any
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection
from sqlalchemy import text

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

app = FastAPI(title="stocker-api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "api"}


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
            # Latest run
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
    return {
        "snapshot": dict(snapshot),
        "tickers": ticker_list,
    }


@app.get("/factors/{ticker}")
async def get_factors(ticker: str):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT run_id, ticker, score_date, regime, momentum, quality, value, growth, "
                "low_volatility, liquidity, calculated_at "
                "FROM factor_scores WHERE ticker = :ticker ORDER BY calculated_at DESC LIMIT 5"
            ),
            {"ticker": ticker.upper()},
        )
        results = [dict(r) for r in rows.mappings()]
    if not results:
        raise HTTPException(404, f"No factor scores for {ticker}")
    return results
