import os
import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, timezone, datetime

import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from app.rank import load_strategy, rank_universe, FACTORS
from stock_strategy_shared.schemas.strategy import StrategyConfig

STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
DATABASE_URL = os.getenv("DATABASE_URL", "")

strategy: StrategyConfig
engine: AsyncEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine
    strategy = load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    yield
    await engine.dispose()


app = FastAPI(title="ranker", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ranker", "strategy": strategy.strategy_id}


async def _run_rank_job() -> None:
    async with engine.begin() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, regime FROM factor_runs "
                "WHERE status = 'success' AND ticker_count > 0 "
                "ORDER BY completed_at DESC LIMIT 1"
            )
        )
        latest = row.fetchone()
        if latest is None:
            return

        latest_run_id = str(latest.run_id)
        regime = latest.regime

        rows = await conn.execute(
            text(
                "SELECT ticker, momentum, quality, value, growth, low_volatility, liquidity "
                "FROM factor_scores WHERE run_id = :run_id"
            ),
            {"run_id": latest_run_id},
        )
        records = rows.fetchall()

    if not records:
        return

    factor_scores_df = pd.DataFrame(
        [
            {
                "ticker": r.ticker,
                "momentum": float(r.momentum) if r.momentum is not None else float("nan"),
                "quality": float(r.quality) if r.quality is not None else float("nan"),
                "value": float(r.value) if r.value is not None else float("nan"),
                "growth": float(r.growth) if r.growth is not None else float("nan"),
                "low_volatility": float(r.low_volatility) if r.low_volatility is not None else float("nan"),
                "liquidity": float(r.liquidity) if r.liquidity is not None else float("nan"),
            }
            for r in records
        ]
    )

    ranked_df = rank_universe(factor_scores_df, regime, strategy)

    ranking_run_id = str(uuid.uuid4())
    rank_date = date.today()
    ranked_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        for _, row in ranked_df.iterrows():
            factor_snapshot = {
                f: (None if pd.isna(row[f]) else float(row[f]))
                for f in FACTORS
                if f in ranked_df.columns
            }
            composite = None if pd.isna(row["composite_score"]) else float(row["composite_score"])
            percentile = None if pd.isna(row["percentile"]) else float(row["percentile"])

            await conn.execute(
                text(
                    """
                    INSERT INTO rankings
                        (run_id, strategy_id, regime, rank_date, ticker, rank,
                         composite_score, percentile, factor_scores, ranked_at)
                    VALUES
                        (:run_id, :strategy_id, :regime, :rank_date, :ticker, :rank,
                         :composite_score, :percentile, CAST(:factor_scores AS jsonb), :ranked_at)
                    ON CONFLICT (run_id, ticker) DO UPDATE SET
                        rank            = EXCLUDED.rank,
                        composite_score = EXCLUDED.composite_score,
                        percentile      = EXCLUDED.percentile,
                        factor_scores   = EXCLUDED.factor_scores,
                        ranked_at       = EXCLUDED.ranked_at
                    """
                ),
                {
                    "run_id": ranking_run_id,
                    "strategy_id": strategy.strategy_id,
                    "regime": regime,
                    "rank_date": rank_date,
                    "ticker": str(row["ticker"]),
                    "rank": int(row["rank"]),
                    "composite_score": composite,
                    "percentile": percentile,
                    "factor_scores": json.dumps(factor_snapshot),
                    "ranked_at": ranked_at,
                },
            )


@app.post("/jobs/rank")
async def start_rank_job(background_tasks: BackgroundTasks):
    async with engine.begin() as conn:
        row = await conn.execute(
            text(
                "SELECT regime FROM factor_runs "
                "WHERE status = 'success' AND ticker_count > 0 "
                "ORDER BY completed_at DESC LIMIT 1"
            )
        )
        latest = row.fetchone()

    regime = latest.regime if latest else "unknown"
    background_tasks.add_task(_run_rank_job)
    return {"status": "started", "job": "rank", "strategy": strategy.strategy_id, "regime": regime}


async def _fetch_top_rankings(n: int) -> list[dict]:
    async with engine.begin() as conn:
        run_row = await conn.execute(
            text("SELECT run_id FROM rankings ORDER BY ranked_at DESC LIMIT 1")
        )
        latest_run = run_row.fetchone()
        if latest_run is None:
            return []

        rows = await conn.execute(
            text(
                "SELECT ticker, rank, composite_score, percentile, factor_scores "
                "FROM rankings WHERE run_id = :run_id "
                "ORDER BY rank ASC LIMIT :n"
            ),
            {"run_id": str(latest_run.run_id), "n": n},
        )
        return [
            {
                "ticker": r.ticker,
                "rank": r.rank,
                "composite_score": float(r.composite_score) if r.composite_score is not None else None,
                "percentile": float(r.percentile) if r.percentile is not None else None,
                "factor_scores": r.factor_scores,
            }
            for r in rows.fetchall()
        ]


@app.get("/rankings/latest")
async def get_latest_rankings():
    results = await _fetch_top_rankings(50)
    if not results:
        raise HTTPException(status_code=404, detail="No rankings found")
    return results


@app.get("/rankings/top/{n}")
async def get_top_n_rankings(n: int):
    if n < 1:
        raise HTTPException(status_code=400, detail="n must be >= 1")
    results = await _fetch_top_rankings(n)
    if not results:
        raise HTTPException(status_code=404, detail="No rankings found")
    return results
