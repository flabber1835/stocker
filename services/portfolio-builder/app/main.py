import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from app.select import greedy_select, build_covariance
from stock_strategy_shared.schemas.strategy import StrategyConfig

STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

strategy: StrategyConfig
engine: AsyncEngine
config_hash: str = ""


def _load_strategy(path: str) -> StrategyConfig:
    import yaml
    with open(path) as f:
        raw = f.read()
    global config_hash
    config_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return StrategyConfig(**yaml.safe_load(raw))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine
    strategy = _load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE portfolio_runs SET status='failed', completed_at=NOW(), "
                "error_message='Service restarted while run was active' "
                "WHERE status='running'"
            )
        )
    yield
    await engine.dispose()


app = FastAPI(title="portfolio-builder", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "portfolio-builder",
        "strategy": strategy.strategy_id,
        "config_hash": config_hash,
    }


# ── Trace helpers ───────────────────────────────────────────────────────────────────────────────────

async def _log_step(
    conn,
    trace_id: str,
    step_name: str,
    status: str,
    *,
    started_at: Optional[datetime] = None,
    input_summary: Optional[dict] = None,
    output_summary: Optional[dict] = None,
    warnings: Optional[list] = None,
    error_message: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    await conn.execute(
        text(
            "INSERT INTO execution_steps "
            "(step_id, trace_id, service, step_name, status, started_at, completed_at, "
            " input_summary, output_summary, warnings, error_message) "
            "VALUES (:sid, :tid, 'portfolio-builder', :step, :status, :started, :now, "
            "        CAST(:inp AS jsonb), CAST(:out AS jsonb), CAST(:warn AS jsonb), :err)"
        ),
        {
            "sid": str(uuid.uuid4()),
            "tid": trace_id,
            "step": step_name,
            "status": status,
            "started": started_at or now,
            "now": now,
            "inp": json.dumps(input_summary) if input_summary else None,
            "out": json.dumps(output_summary) if output_summary else None,
            "warn": json.dumps(warnings) if warnings else None,
            "err": error_message,
        },
    )


async def _write_trace_file(
    trace_id: str,
    run_id: str,
    status: str,
    started_at: datetime,
    **extra,
) -> None:
    if not ARTIFACTS_PATH:
        return
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT service, step_name, status, started_at, completed_at, "
                    "       input_summary, output_summary, warnings, error_message "
                    "FROM execution_steps WHERE trace_id = :tid ORDER BY started_at ASC"
                ),
                {"tid": trace_id},
            )
            steps = [dict(r) for r in rows.mappings()]

        traces_dir = os.path.join(ARTIFACTS_PATH, "traces")
        os.makedirs(traces_dir, exist_ok=True)
        fname = f"{started_at.strftime('%Y-%m-%d')}_portfolio_run_{trace_id[:8]}.json"
        payload = {
            "trace_id": trace_id,
            "run_id": run_id,
            "job_type": "portfolio_run",
            "status": status,
            "strategy_id": strategy.strategy_id,
            "config_hash": config_hash,
            "started_at": started_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **extra,
            "steps": steps,
        }
        path = os.path.join(traces_dir, fname)
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"[portfolio-builder] trace -> {path} ({len(steps)} steps, status={status})")
    except Exception as exc:
        import traceback
        print(f"[portfolio-builder] WARNING: failed to write trace file: {exc}")
        traceback.print_exc()


# ── Build job ───────────────────────────────────────────────────────────────────────────────────

async def _run_build(run_id: str, trace_id: str, ranking_run_id: Optional[str]) -> None:
    started_at = datetime.now(timezone.utc)
    pb_cfg = strategy.portfolio_builder

    # Resolve the ranking run first so we can fail fast before inserting any DB rows.
    # This prevents the error-handler from trying to UPDATE a portfolio_runs row that
    # was never INSERTed (same bug pattern previously fixed in ranker).
    async with engine.connect() as conn:
        if ranking_run_id:
            row = await conn.execute(
                text("SELECT run_id, regime, rank_date FROM ranking_runs WHERE run_id=:rid AND status='success'"),
                {"rid": ranking_run_id},
            )
        else:
            row = await conn.execute(
                text("SELECT run_id, regime, rank_date FROM ranking_runs WHERE status='success' ORDER BY completed_at DESC LIMIT 1")
            )
        rr = row.fetchone()

    if rr is None:
        msg = (
            f"ranking run {ranking_run_id} not found or not successful"
            if ranking_run_id else "no successful ranking run found — run: make rank first"
        )
        print(f"[portfolio-builder] run {run_id} skipped: {msg}")
        return

    source_ranking_run_id = str(rr.run_id)
    regime = rr.regime
    portfolio_date = rr.rank_date

    # Both DB rows exist from this point forward; the error handler can safely UPDATE them.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO execution_traces "
                "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
                "VALUES (:tid, 'portfolio_run', 'running', :rid, :sid, :ch, :now)"
            ),
            {"tid": trace_id, "rid": run_id, "sid": strategy.strategy_id, "ch": config_hash, "now": started_at},
        )
        await conn.execute(
            text(
                "INSERT INTO portfolio_runs "
                "(run_id, trace_id, source_ranking_run_id, strategy_id, config_hash, "
                " regime, portfolio_date, status, started_at) "
                "VALUES (:rid, :tid, :src, :sid, :ch, :regime, :pd, 'running', :now)"
            ),
            {
                "rid": run_id, "tid": trace_id, "src": source_ranking_run_id,
                "sid": strategy.strategy_id, "ch": config_hash,
                "regime": regime, "pd": portfolio_date, "now": started_at,
            },
        )

    try:
        await _do_build(run_id, trace_id, started_at, source_ranking_run_id, regime, portfolio_date, pb_cfg)
    except Exception as exc:
        err = str(exc)[:1000]
        print(f"[portfolio-builder] run {run_id} FAILED: {exc}")
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE portfolio_runs SET status='failed', completed_at=:now, error_message=:err WHERE run_id=:rid"),
                {"rid": run_id, "now": datetime.now(timezone.utc), "err": err},
            )
            await conn.execute(
                text("UPDATE execution_traces SET status='failed', completed_at=:now, notes=:err WHERE trace_id=:tid"),
                {"tid": trace_id, "now": datetime.now(timezone.utc), "err": err},
            )
        await _write_trace_file(trace_id, run_id, "failed", started_at, error=err)
        raise


async def _do_build(
    run_id: str,
    trace_id: str,
    started_at: datetime,
    source_ranking_run_id: str,
    regime: str,
    portfolio_date,
    pb_cfg,
) -> None:
    # ranking run already resolved and both DB rows already inserted by _run_build

    # ── Step 1: log ranking run context ──────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_ranking_run", "success",
            started_at=t0,
            output_summary={
                "source_ranking_run_id": source_ranking_run_id,
                "regime": regime,
                "portfolio_date": str(portfolio_date),
            },
        )

    # ── Step 2: load top N candidates ────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT ticker, rank, composite_score FROM rankings "
                "WHERE run_id = :rid ORDER BY rank ASC LIMIT :n"
            ),
            {"rid": source_ranking_run_id, "n": pb_cfg.candidate_count},
        )
        candidates = rows.fetchall()

    if not candidates:
        raise RuntimeError("no rankings found for ranking run — run rank first")

    candidate_tickers = [r.ticker for r in candidates]
    scores_map = {r.ticker: float(r.composite_score) for r in candidates}
    rank_map = {r.ticker: int(r.rank) for r in candidates}

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_candidates", "success",
            started_at=t0,
            input_summary={"candidate_count": pb_cfg.candidate_count},
            output_summary={"loaded": len(candidate_tickers), "top_ticker": candidate_tickers[0]},
        )

    # ── Step 3: load price data for covariance ───────────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    lookback_days = int(pb_cfg.covariance_window_days * 1.5)  # extra buffer for weekends/holidays
    async with engine.connect() as conn:
        price_rows = await conn.execute(
            text(
                "SELECT ticker, date, adjusted_close FROM daily_prices "
                "WHERE ticker = ANY(:tickers) "
                "AND date <= :pd "
                "AND date >= :pd - :days * INTERVAL '1 day' "
                "ORDER BY ticker, date ASC"
            ),
            {"tickers": candidate_tickers, "pd": portfolio_date, "days": lookback_days},
        )
        prices_df = pd.DataFrame(
            price_rows.fetchall(),
            columns=["ticker", "date", "adjusted_close"],
        )

    prices_df["date"] = pd.to_datetime(prices_df["date"])
    tickers_with_prices = set(prices_df["ticker"].unique())
    no_price = [t for t in candidate_tickers if t not in tickers_with_prices]

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "load_prices", "success",
            started_at=t0,
            input_summary={"ticker_count": len(candidate_tickers), "lookback_days": lookback_days},
            output_summary={
                "row_count": len(prices_df),
                "tickers_with_prices": len(tickers_with_prices),
                "no_price_tickers": no_price,
            },
            warnings=[f"{len(no_price)} candidates had no price data and will be excluded"] if no_price else None,
        )

    # Only keep candidates we actually have prices for
    rankable_tickers = [t for t in candidate_tickers if t in tickers_with_prices]
    if not rankable_tickers:
        raise RuntimeError("no price data available for any candidates")

    # ── Step 4: build covariance matrix ────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    cov = build_covariance(
        prices_df[prices_df["ticker"].isin(rankable_tickers)],
        window_days=pb_cfg.covariance_window_days,
    )

    # Restrict scores Series to tickers present in cov (some may have been dropped)
    available_tickers = [t for t in rankable_tickers if t in cov.index]
    scores = pd.Series({t: scores_map[t] for t in available_tickers})
    cov = cov.loc[available_tickers, available_tickers]

    # Portfolio-level correlation summary for the audit log
    n_cov = len(available_tickers)
    if n_cov > 1:
        std = np.sqrt(np.diag(cov.values))
        std_outer = np.outer(std, std)
        with np.errstate(invalid="ignore", divide="ignore"):
            corr_matrix = np.where(std_outer > 0, cov.values / std_outer, 0.0)
        upper_idx = np.triu_indices(n_cov, k=1)
        avg_pairwise_corr = float(np.mean(corr_matrix[upper_idx]))
    else:
        avg_pairwise_corr = 0.0

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "build_covariance", "success",
            started_at=t0,
            input_summary={
                "window_days": pb_cfg.covariance_window_days,
                "ticker_count": len(available_tickers),
            },
            output_summary={
                "matrix_size": len(cov),
                "avg_pairwise_correlation": round(avg_pairwise_corr, 4),
            },
        )

    # ── Step 5: greedy selection ────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    selected = greedy_select(scores, cov, target=pb_cfg.max_positions)
    selected_tickers = [s["ticker"] for s in selected]

    # Equal weight
    weight = round(1.0 / len(selected), 6)

    # Final portfolio volatility (equal-weighted)
    w_vec = np.ones(len(selected)) / len(selected)
    final_cov = cov.loc[selected_tickers, selected_tickers].values
    portfolio_vol = float(np.sqrt(max(float(w_vec @ final_cov @ w_vec), 1e-12)))

    # Highest-correlated pair for the trace (informational)
    if len(selected_tickers) > 1:
        sub_std = np.sqrt(np.diag(final_cov))
        sub_outer = np.outer(sub_std, sub_std)
        with np.errstate(invalid="ignore", divide="ignore"):
            sub_corr = np.where(sub_outer > 0, final_cov / sub_outer, 0.0)
        uidx = np.triu_indices(len(selected_tickers), k=1)
        max_corr_idx = int(np.argmax(sub_corr[uidx]))
        i_idx, j_idx = uidx[0][max_corr_idx], uidx[1][max_corr_idx]
        highest_corr_pair = {
            "ticker_a": selected_tickers[i_idx],
            "ticker_b": selected_tickers[j_idx],
            "correlation": round(float(sub_corr[i_idx, j_idx]), 4),
        }
    else:
        highest_corr_pair = None

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "greedy_select", "success",
            started_at=t0,
            input_summary={
                "candidate_count": len(available_tickers),
                "target_positions": pb_cfg.max_positions,
            },
            output_summary={
                "selected_count": len(selected),
                "portfolio_estimated_vol": round(portfolio_vol, 4),
                "avg_candidate_pool_correlation": round(avg_pairwise_corr, 4),
                "highest_corr_pair": highest_corr_pair,
                "selected_tickers": selected_tickers,
            },
        )

    # ── Step 6: write portfolio run + holdings ───────────────────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    completed_at = datetime.now(timezone.utc)

    async with engine.begin() as conn:
        for item in selected:
            ticker = item["ticker"]
            await conn.execute(
                text(
                    "INSERT INTO portfolio_holdings "
                    "(run_id, source_ranking_run_id, strategy_id, regime, portfolio_date, "
                    " ticker, position, weight, composite_score, original_rank, "
                    " adj_score, portfolio_vol_at_add) "
                    "VALUES (:run_id, :src, :sid, :regime, :pd, "
                    "        :ticker, :pos, :weight, :cs, :orank, :adj, :pvol) "
                    "ON CONFLICT (run_id, ticker) DO NOTHING"
                ),
                {
                    "run_id": run_id,
                    "src": source_ranking_run_id,
                    "sid": strategy.strategy_id,
                    "regime": regime,
                    "pd": portfolio_date,
                    "ticker": ticker,
                    "pos": item["position"],
                    "weight": weight,
                    "cs": round(item["composite_score"], 6),
                    "orank": rank_map.get(ticker),
                    "adj": round(item["adj_score"], 6),
                    "pvol": round(item["portfolio_vol_at_add"], 6),
                },
            )

        await conn.execute(
            text(
                "UPDATE portfolio_runs SET "
                "  status='success', completed_at=:now, "
                "  candidate_count=:cc, selected_count=:sc, "
                "  covariance_window_days=:cw, "
                "  avg_pairwise_correlation=:apc, "
                "  portfolio_estimated_vol=:pvol "
                "WHERE run_id=:rid"
            ),
            {
                "rid": run_id,
                "now": completed_at,
                "cc": len(available_tickers),
                "sc": len(selected),
                "cw": pb_cfg.covariance_window_days,
                "apc": round(avg_pairwise_corr, 6),
                "pvol": round(portfolio_vol, 6),
            },
        )
        await conn.execute(
            text(
                "UPDATE execution_traces SET status='success', completed_at=:now "
                "WHERE trace_id=:tid"
            ),
            {"tid": trace_id, "now": completed_at},
        )
        await _log_step(
            conn, trace_id, "write_portfolio", "success",
            started_at=t0,
            output_summary={"written_count": len(selected), "run_id": run_id},
        )

    print(
        f"[portfolio-builder] run {run_id} SUCCESS: {len(selected)} positions, "
        f"vol={portfolio_vol:.4f}, regime={regime}, date={portfolio_date}"
    )

    def _fmt(v):
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(v, 4)

    holdings_detail = [
        {
            "position": item["position"],
            "ticker": item["ticker"],
            "original_rank": rank_map.get(item["ticker"]),
            "composite_score": _fmt(item["composite_score"]),
            "adj_score": _fmt(item["adj_score"]),
            "portfolio_vol_at_add": _fmt(item["portfolio_vol_at_add"]),
            "weight": weight,
        }
        for item in selected
    ]

    await _write_trace_file(
        trace_id, run_id, "success", started_at,
        regime=regime,
        portfolio_date=str(portfolio_date),
        selected_count=len(selected),
        portfolio_estimated_vol=round(portfolio_vol, 4),
        avg_pairwise_correlation=round(avg_pairwise_corr, 4),
        highest_corr_pair=highest_corr_pair,
        source_ranking_run_id=source_ranking_run_id,
        portfolio_config={
            "method": pb_cfg.method,
            "candidate_count": pb_cfg.candidate_count,
            "max_positions": pb_cfg.max_positions,
            "covariance_window_days": pb_cfg.covariance_window_days,
            "weighting": pb_cfg.weighting,
        },
        holdings=holdings_detail,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────────────────────────

@app.post("/jobs/build")
async def start_build(
    background_tasks: BackgroundTasks,
    ranking_run_id: Optional[str] = None,
):
    # Pre-validate that a ranking run exists before issuing a run_id the client will poll.
    # Without this check, _run_build could silently return without ever inserting a
    # portfolio_runs row, making GET /runs/{run_id} return 404 forever.
    async with engine.connect() as conn:
        if ranking_run_id:
            chk = await conn.execute(
                text("SELECT 1 FROM ranking_runs WHERE run_id=:rid AND status='success'"),
                {"rid": ranking_run_id},
            )
        else:
            chk = await conn.execute(
                text("SELECT 1 FROM ranking_runs WHERE status='success' ORDER BY completed_at DESC LIMIT 1")
            )
        if chk.fetchone() is None:
            raise HTTPException(
                status_code=400,
                detail="no successful ranking run found — run: make rank first",
            )

    run_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    background_tasks.add_task(_run_build, run_id, trace_id, ranking_run_id)
    return {
        "status": "started",
        "job": "build",
        "run_id": run_id,
        "trace_id": trace_id,
    }


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, trace_id, source_ranking_run_id, strategy_id, regime, "
                "       portfolio_date, status, candidate_count, selected_count, "
                "       covariance_window_days, avg_pairwise_correlation, "
                "       portfolio_estimated_vol, error_message, started_at, completed_at "
                "FROM portfolio_runs WHERE run_id = :rid"
            ),
            {"rid": run_id},
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {k: (str(v) if hasattr(v, "hex") else (v.isoformat() if hasattr(v, "isoformat") else v))
            for k, v in dict(result._mapping).items()}


@app.get("/portfolio/latest")
async def get_latest_portfolio():
    async with engine.connect() as conn:
        run_row = await conn.execute(
            text(
                "SELECT run_id, regime, portfolio_date, selected_count, "
                "       portfolio_estimated_vol, avg_pairwise_correlation "
                "FROM portfolio_runs WHERE status='success' "
                "ORDER BY completed_at DESC LIMIT 1"
            )
        )
        run = run_row.fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail="No portfolio run yet. Run: make portfolio")

        holdings_rows = await conn.execute(
            text(
                "SELECT ticker, position, weight, composite_score, original_rank, "
                "       adj_score, portfolio_vol_at_add "
                "FROM portfolio_holdings WHERE run_id = :rid ORDER BY position ASC"
            ),
            {"rid": str(run.run_id)},
        )
        holdings = [dict(r._mapping) for r in holdings_rows.fetchall()]

    return {
        "run_id": str(run.run_id),
        "regime": run.regime,
        "portfolio_date": str(run.portfolio_date),
        "selected_count": run.selected_count,
        "portfolio_estimated_vol": float(run.portfolio_estimated_vol) if run.portfolio_estimated_vol else None,
        "avg_pairwise_correlation": float(run.avg_pairwise_correlation) if run.avg_pairwise_correlation else None,
        "holdings": holdings,
    }
