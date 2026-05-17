import asyncio
import json
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from app.select import greedy_select, build_covariance, compute_weights
from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.schemas.strategy import StrategyConfig
from stock_strategy_shared.tracing import fmt_row, log_step, write_trace_file, mark_orphaned_runs_failed

STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")

_MIN_EIGENVALUE = 1e-8  # numerical zero threshold for PSD matrix repair


def _apply_conviction_boost(
    original_score: float,
    conviction: str,
    boost_map: dict,
    max_boost: float,
) -> float:
    """
    Additive LLM conviction boost: score += abs(score) * boost_factor.
    Using abs() means negative-score stocks are lifted toward zero rather than
    penalised further, and positive-score stocks are amplified proportionally.
    Returns original_score unchanged when conviction is 'none' or unknown.
    """
    boost = min(boost_map.get(conviction, 0.0), max_boost)
    if boost <= 0:
        return original_score
    return original_score + abs(original_score) * boost


_fmt_row = fmt_row


strategy: StrategyConfig
engine: AsyncEngine
config_hash: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine, config_hash
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5)
    async with engine.begin() as conn:
        await mark_orphaned_runs_failed(conn, "portfolio_runs", trace_job_type="portfolio_run")
    yield
    await engine.dispose()


app = FastAPI(title="portfolio-builder", lifespan=lifespan)

_job_lock = asyncio.Lock()


async def _assert_no_running_job(conn) -> None:
    row = await conn.execute(
        text("SELECT run_id FROM portfolio_runs WHERE status='running' LIMIT 1")
    )
    if row.fetchone() is not None:
        raise HTTPException(status_code=409, detail="a portfolio build job is already running")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "portfolio-builder",
        "strategy": strategy.strategy_id,
        "config_hash": config_hash,
    }


# ── Trace helpers ───────────────────────────────────────────────────────────────────────────────────

async def _log_step(conn, trace_id, step_name, status, *, started_at=None,
                    input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "portfolio-builder", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


async def _write_trace_file(trace_id: str, run_id: str, status: str, started_at: datetime, **extra) -> None:
    await write_trace_file(
        engine, ARTIFACTS_PATH, trace_id, run_id, "portfolio_run", status, started_at,
        service_label="portfolio-builder",
        strategy_id=strategy.strategy_id,
        config_hash=config_hash,
        **extra,
    )


# ── Build job ───────────────────────────────────────────────────────────────────────────────────

async def _run_build(run_id: str, trace_id: str, source_ranking_run_id: Optional[str], vetter_run_id: Optional[str] = None) -> None:
    started_at = datetime.now(timezone.utc)
    pb_cfg = strategy.portfolio_builder

    # Resolve the ranking run first so we can fail fast before inserting any DB rows.
    # This prevents the error-handler from trying to UPDATE a portfolio_runs row that
    # was never INSERTed (same bug pattern previously fixed in ranker).
    async with engine.connect() as conn:
        if source_ranking_run_id:
            row = await conn.execute(
                text("SELECT run_id, regime, rank_date FROM ranking_runs WHERE run_id=:rid AND status='success'"),
                {"rid": source_ranking_run_id},
            )
        else:
            row = await conn.execute(
                text("SELECT run_id, regime, rank_date FROM ranking_runs WHERE status='success' ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1")
            )
        rr = row.fetchone()

    if rr is None:
        msg = (
            f"ranking run {source_ranking_run_id} not found or not successful"
            if source_ranking_run_id else "no successful ranking run found — run: make rank first"
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
                "(run_id, trace_id, source_ranking_run_id, vetter_run_id, strategy_id, config_hash, "
                " regime, portfolio_date, status, started_at) "
                "VALUES (:rid, :tid, :src, :vrid, :sid, :ch, :regime, :pd, 'running', :now)"
            ),
            {
                "rid": run_id, "tid": trace_id, "src": source_ranking_run_id,
                "vrid": vetter_run_id,
                "sid": strategy.strategy_id, "ch": config_hash,
                "regime": regime, "pd": portfolio_date, "now": started_at,
            },
        )

    try:
        await _do_build(run_id, trace_id, started_at, source_ranking_run_id, regime, portfolio_date, pb_cfg, vetter_run_id)
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
    vetter_run_id: Optional[str] = None,
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

    # ── Step 2a: apply do-not-buy list ───────────────────────────────────────────────────────────────────────────────────────────────────
    do_not_buy_set = set(t.upper() for t in (pb_cfg.do_not_buy or []))
    if do_not_buy_set:
        dnb_excluded = [t for t in candidate_tickers if t.upper() in do_not_buy_set]
        candidate_tickers = [t for t in candidate_tickers if t.upper() not in do_not_buy_set]
        scores_map = {t: v for t, v in scores_map.items() if t.upper() not in do_not_buy_set}
        rank_map = {t: v for t, v in rank_map.items() if t.upper() not in do_not_buy_set}
        if dnb_excluded:
            async with engine.begin() as conn:
                await _log_step(
                    conn, trace_id, "apply_do_not_buy", "success",
                    started_at=t0,
                    output_summary={
                        "excluded_count": len(dnb_excluded),
                        "excluded_tickers": dnb_excluded,
                        "remaining_candidates": len(candidate_tickers),
                    },
                    warnings=[f"do-not-buy list excluded {len(dnb_excluded)} tickers: {dnb_excluded}"],
                )

    # ── Step 2b: apply LLM vetter exclusions ─────────────────────────────────────────────────────────────────────────────────────────────
    vetter_excluded: list[str] = []
    if vetter_run_id:
        async with engine.connect() as conn:
            exc_rows = await conn.execute(
                text(
                    "SELECT ticker, confidence, reason FROM vetter_exclusions "
                    "WHERE run_id = :rid ORDER BY confidence DESC, ticker ASC"
                ),
                {"rid": vetter_run_id},
            )
            vetter_excluded = [r.ticker for r in exc_rows.fetchall()]

        if vetter_excluded:
            excluded_set = set(vetter_excluded)
            candidate_tickers = [t for t in candidate_tickers if t not in excluded_set]
            scores_map = {t: v for t, v in scores_map.items() if t not in excluded_set}
            rank_map = {t: v for t, v in rank_map.items() if t not in excluded_set}

        async with engine.begin() as conn:
            await _log_step(
                conn, trace_id, "apply_vetter_exclusions", "success",
                started_at=t0,
                input_summary={"vetter_run_id": vetter_run_id},
                output_summary={
                    "excluded_count": len(vetter_excluded),
                    "excluded_tickers": vetter_excluded,
                    "remaining_candidates": len(candidate_tickers),
                },
                warnings=(
                    [f"LLM vetter excluded {len(vetter_excluded)} tickers: {vetter_excluded}"]
                    if vetter_excluded else None
                ),
            )

    # ── Step 2c: apply LLM vetter conviction boosts ──────────────────────────────────────────────────────────────────────────────────────
    conviction_boosts_applied: dict[str, dict] = {}
    if vetter_run_id:
        vetter_cfg = strategy.vetter
        boost_map = vetter_cfg.conviction_boosts

        async with engine.connect() as conn:
            conv_rows = await conn.execute(
                text(
                    "SELECT ticker, positive_conviction FROM vetter_decisions "
                    "WHERE run_id = :rid AND positive_catalyst = TRUE"
                ),
                {"rid": vetter_run_id},
            )
            conviction_map = {r.ticker: r.positive_conviction for r in conv_rows.fetchall()}

        max_boost = vetter_cfg.conviction_max_boost
        for ticker, conviction in conviction_map.items():
            if ticker not in scores_map:
                continue
            boost = min(boost_map.get(conviction, 0.0), max_boost)
            if boost <= 0:
                continue
            original = scores_map[ticker]
            scores_map[ticker] = _apply_conviction_boost(original, conviction, boost_map, max_boost)
            conviction_boosts_applied[ticker] = {
                "conviction": conviction,
                "boost_factor": boost,
                "original_score": round(original, 6),
                "adjusted_score": round(scores_map[ticker], 6),
            }

        if conviction_boosts_applied:
            async with engine.begin() as conn:
                await _log_step(
                    conn, trace_id, "apply_conviction_boosts", "success",
                    started_at=t0,
                    input_summary={
                        "vetter_run_id": vetter_run_id,
                        "conviction_boosts_config": boost_map,
                        "conviction_max_boost": vetter_cfg.conviction_max_boost,
                    },
                    output_summary={
                        "boosted_count": len(conviction_boosts_applied),
                        "boosted_tickers": conviction_boosts_applied,
                    },
                )
            print(
                f"[portfolio-builder] conviction boosts applied to "
                f"{len(conviction_boosts_applied)} tickers: "
                + ", ".join(
                    f"{t}(+{v['boost_factor']*100:.0f}%)"
                    for t, v in conviction_boosts_applied.items()
                )
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

    # ── Step 3b: apply universe filters before covariance (min_price, min_avg_dollar_volume) ──────────────────────────
    t0 = datetime.now(timezone.utc)
    universe_cfg = strategy.universe
    min_price = universe_cfg.min_price
    min_avg_dv = universe_cfg.min_avg_dollar_volume_20d

    # Latest adjusted_close per ticker using already-loaded prices_df (no extra DB query)
    latest_prices = (
        prices_df[prices_df["ticker"].isin(rankable_tickers)]
        .sort_values("date")
        .groupby("ticker")["adjusted_close"]
        .last()
        .to_dict()
    )

    async with engine.connect() as conn:
        # 20-day avg dollar volume from fundamentals (computed during ingestion)
        avg_dv_rows = await conn.execute(
            text(
                "SELECT DISTINCT ON (ticker) ticker, avg_volume "
                "FROM fundamentals WHERE ticker = ANY(:tickers) "
                "ORDER BY ticker, as_of_date DESC"
            ),
            {"tickers": rankable_tickers},
        )
        avg_dv_map = {r.ticker: float(r.avg_volume) for r in avg_dv_rows.fetchall() if r.avg_volume is not None}

    price_filtered = [t for t in rankable_tickers if latest_prices.get(t, 0) < min_price]
    dv_filtered = [t for t in rankable_tickers if t not in avg_dv_map or avg_dv_map[t] < min_avg_dv]
    universe_filtered = set(price_filtered) | set(dv_filtered)
    filtered_tickers = [t for t in rankable_tickers if t not in universe_filtered]

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "apply_universe_filters", "success",
            started_at=t0,
            input_summary={
                "min_price": min_price,
                "min_avg_dollar_volume_20d": min_avg_dv,
            },
            output_summary={
                "price_filtered": price_filtered,
                "dv_filtered": dv_filtered,
                "remaining": len(filtered_tickers),
            },
            warnings=(
                [f"{len(universe_filtered)} tickers filtered: price<{min_price} or avg_dv<{min_avg_dv}"]
                if universe_filtered else None
            ),
        )

    # ── Step 4: build covariance matrix ────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    cov, tickers_dropped_obs = build_covariance(
        prices_df[prices_df["ticker"].isin(filtered_tickers)],
        window_days=pb_cfg.covariance_window_days,
        min_observations=pb_cfg.min_covariance_observations,
        shrinkage=pb_cfg.covariance_shrinkage,
    )

    if cov is None or len(cov) == 0:
        raise RuntimeError(
            f"Covariance matrix is empty — candidates have insufficient price history. "
            f"Need at least 2 tickers with overlapping price data."
        )

    eigenvalues = np.linalg.eigvalsh(cov.values)
    min_eigenvalue = float(eigenvalues.min())
    if min_eigenvalue < _MIN_EIGENVALUE:
        print(f"[portfolio-builder] WARNING: covariance matrix near rank-deficient (min eigenvalue={min_eigenvalue:.2e}). Portfolio vol estimates may be unreliable.")

    # Restrict scores Series to tickers present in cov (some may have been dropped for insufficient obs)
    available_tickers = [t for t in filtered_tickers if t in cov.index]
    scores = pd.Series({t: scores_map[t] for t in available_tickers})
    cov = cov.loc[available_tickers, available_tickers]

    # Portfolio-level correlation summary for the audit log
    # corr_matrix is reused below for the highest-correlated pair among selected tickers.
    n_cov = len(available_tickers)
    if n_cov > 1:
        std = np.sqrt(np.diag(cov.values))
        std_outer = np.outer(std, std)
        with np.errstate(invalid="ignore", divide="ignore"):
            corr_matrix = np.where(std_outer > 0, cov.values / std_outer, 0.0)
        upper_idx = np.triu_indices(n_cov, k=1)
        avg_pairwise_corr = float(np.mean(corr_matrix[upper_idx]))
    else:
        corr_matrix = None
        avg_pairwise_corr = 0.0

    cov_warnings = []
    if tickers_dropped_obs:
        cov_warnings.append(
            f"{len(tickers_dropped_obs)} tickers dropped: insufficient observations "
            f"(< {pb_cfg.min_covariance_observations}): {tickers_dropped_obs}"
        )

    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "build_covariance", "success",
            started_at=t0,
            input_summary={
                "window_days": pb_cfg.covariance_window_days,
                "min_observations": pb_cfg.min_covariance_observations,
                "shrinkage": pb_cfg.covariance_shrinkage,
                "ticker_count": len(filtered_tickers),
            },
            output_summary={
                "matrix_size": len(cov),
                "tickers_dropped_insufficient_obs": len(tickers_dropped_obs),
                "avg_pairwise_correlation": round(avg_pairwise_corr, 4),
            },
            warnings=cov_warnings or None,
        )

    # ── Step 4c: load sector data for sector cap enforcement ──────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        sector_rows = await conn.execute(
            text(
                "SELECT DISTINCT ON (ut.ticker) ut.ticker, ut.sector "
                "FROM universe_tickers ut "
                "JOIN universe_snapshots us ON ut.snapshot_id = us.id "
                "WHERE ut.ticker = ANY(:tickers) "
                "ORDER BY ut.ticker, us.snapshot_date DESC"
            ),
            {"tickers": available_tickers},
        )
        sector_map = {r.ticker: r.sector for r in sector_rows.fetchall() if r.sector}

    # ── Step 5: greedy selection ────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)

    # Optionally exclude candidates with a negative composite score before selection
    negative_excluded: list[str] = []
    if pb_cfg.require_positive_composite_score:
        negative_excluded = [t for t in available_tickers if scores_map[t] < 0]
        if negative_excluded:
            pos_tickers = [t for t in available_tickers if scores_map[t] >= 0]
            scores = scores[pos_tickers]
            cov = cov.loc[pos_tickers, pos_tickers]

    selected = greedy_select(
        scores, cov,
        target=pb_cfg.max_positions,
        sector_map=sector_map,
        max_sector_weight=pb_cfg.max_sector_weight,
    )
    selected_tickers = [s["ticker"] for s in selected]
    selected_negative_score_count = sum(1 for s in selected if s["composite_score"] < 0)

    # Compute weights according to configured method
    weights = compute_weights(
        selected, cov,
        method=pb_cfg.weighting,
        max_position_weight=pb_cfg.max_position_weight,
    )

    # H4: Re-normalize after cap clipping so weights always sum to 1.0.
    # compute_weights redistributes excess iteratively, but floating-point drift
    # or edge cases (all tickers at cap) can leave the sum below 1.0 (silent
    # under-investment). Log the cash residual before normalization for auditability,
    # then apply the standard iterative clip+normalize until stable (≤10 rounds).
    max_pw = pb_cfg.max_position_weight
    cash_residual_before_normalize = round(1.0 - sum(weights.values()), 8)
    if abs(cash_residual_before_normalize) > 1e-9:
        print(
            f"[portfolio-builder] cash residual before re-normalize: "
            f"{cash_residual_before_normalize:.8f} (sum={sum(weights.values()):.8f})"
        )
    for _clip_round in range(10):
        weights = {t: min(w, max_pw) for t, w in weights.items()}
        _wsum = sum(weights.values())
        if _wsum > 0:
            weights = {t: w / _wsum for t, w in weights.items()}
        if not any(w > max_pw + 1e-9 for w in weights.values()):
            break

    # M5: Compute and log per-sector weights post-build.
    # sector_map is loaded in step 4c and is in scope here.
    sector_weights: dict[str, float] = {}
    for _t, _w in weights.items():
        _sector = sector_map.get(_t, "Unknown")
        sector_weights[_sector] = sector_weights.get(_sector, 0.0) + _w
    print(
        f"[portfolio-builder] sector weights post-build: "
        + ", ".join(f"{s}={w:.3f}" for s, w in sorted(sector_weights.items()))
    )
    max_sw = pb_cfg.max_sector_weight
    for _sector, _sw in sector_weights.items():
        if _sw > max_sw + 1e-6:
            print(
                f"[portfolio-builder] WARNING: sector '{_sector}' weight {_sw:.3f} "
                f"exceeds cap {max_sw}"
            )

    # Final portfolio volatility using actual weights
    w_vec = np.array([weights[t] for t in selected_tickers])
    final_cov = cov.loc[selected_tickers, selected_tickers].values
    portfolio_vol = float(np.sqrt(max(float(w_vec @ final_cov @ w_vec), 1e-12)))

    # Highest-correlated pair for the trace (informational).
    # Reuse corr_matrix computed above; slice it to the selected-ticker indices.
    if len(selected_tickers) > 1 and corr_matrix is not None:
        sel_idx = [available_tickers.index(t) for t in selected_tickers]
        sub_corr = corr_matrix[np.ix_(sel_idx, sel_idx)]
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

    sel_warnings = []
    if selected_negative_score_count:
        sel_warnings.append(
            f"{selected_negative_score_count} selected tickers have negative composite scores"
        )
    if negative_excluded:
        sel_warnings.append(
            f"{len(negative_excluded)} candidates excluded: negative composite score "
            f"(require_positive_composite_score=true)"
        )

    weight_values = [weights[t] for t in selected_tickers]
    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "greedy_select", "success",
            started_at=t0,
            input_summary={
                "candidate_count": len(scores),
                "target_positions": pb_cfg.max_positions,
                "require_positive_composite_score": pb_cfg.require_positive_composite_score,
                "negative_score_excluded": len(negative_excluded),
                "weighting": pb_cfg.weighting,
                "max_position_weight": pb_cfg.max_position_weight,
                "max_sector_weight": pb_cfg.max_sector_weight,
                "sector_map_size": len(sector_map),
            },
            output_summary={
                "selected_count": len(selected),
                "selected_negative_score_count": selected_negative_score_count,
                "portfolio_estimated_vol": round(portfolio_vol, 4),
                "avg_candidate_pool_correlation": round(avg_pairwise_corr, 4),
                "highest_corr_pair": highest_corr_pair,
                "weight_min": round(min(weight_values), 6),
                "weight_max": round(max(weight_values), 6),
                "cash_residual_before_normalize": cash_residual_before_normalize,
                "sector_weights": {s: round(w, 6) for s, w in sorted(sector_weights.items())},
                "selected_tickers": selected_tickers,
            },
            warnings=sel_warnings or None,
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
                    "ON CONFLICT (run_id, ticker) DO UPDATE SET "
                    "  weight=EXCLUDED.weight, position=EXCLUDED.position, "
                    "  composite_score=EXCLUDED.composite_score, original_rank=EXCLUDED.original_rank, "
                    "  adj_score=EXCLUDED.adj_score, portfolio_vol_at_add=EXCLUDED.portfolio_vol_at_add"
                ),
                {
                    "run_id": run_id,
                    "src": source_ranking_run_id,
                    "sid": strategy.strategy_id,
                    "regime": regime,
                    "pd": portfolio_date,
                    "ticker": ticker,
                    "pos": item["position"],
                    "weight": weights[ticker],
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
            "weight": weights[item["ticker"]],
        }
        for item in selected
    ]

    await _write_trace_file(
        trace_id, run_id, "success", started_at,
        regime=regime,
        portfolio_date=str(portfolio_date),
        selected_count=len(selected),
        selected_negative_score_count=selected_negative_score_count,
        tickers_dropped_insufficient_obs=len(tickers_dropped_obs),
        portfolio_estimated_vol=round(portfolio_vol, 4),
        avg_pairwise_correlation=round(avg_pairwise_corr, 4),
        highest_corr_pair=highest_corr_pair,
        cash_residual_before_normalize=cash_residual_before_normalize,
        sector_weights={s: round(w, 6) for s, w in sorted(sector_weights.items())},
        source_ranking_run_id=source_ranking_run_id,
        portfolio_config={
            "method": pb_cfg.method,
            "candidate_count": pb_cfg.candidate_count,
            "max_positions": pb_cfg.max_positions,
            "covariance_window_days": pb_cfg.covariance_window_days,
            "min_covariance_observations": pb_cfg.min_covariance_observations,
            "covariance_shrinkage": pb_cfg.covariance_shrinkage,
            "require_positive_composite_score": pb_cfg.require_positive_composite_score,
            "weighting": pb_cfg.weighting,
            "max_position_weight": pb_cfg.max_position_weight,
            "vetter_conviction_max_boost": strategy.vetter.conviction_max_boost,
        },
        conviction_boosts_applied=conviction_boosts_applied,
        holdings=holdings_detail,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────────────────────────

@app.post("/jobs/build")
async def start_build(
    background_tasks: BackgroundTasks,
    ranking_run_id: Optional[str] = None,
    vetter_run_id: Optional[str] = None,
):
    # Pre-validate that a ranking run exists before issuing a run_id the client will poll.
    async with engine.connect() as conn:
        if ranking_run_id:
            chk = await conn.execute(
                text("SELECT 1 FROM ranking_runs WHERE run_id=:rid AND status='success'"),
                {"rid": ranking_run_id},
            )
        else:
            chk = await conn.execute(
                text("SELECT 1 FROM ranking_runs WHERE status='success' ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1")
            )
        if chk.fetchone() is None:
            raise HTTPException(
                status_code=400,
                detail="no successful ranking run found — run: make rank first",
            )

        if vetter_run_id:
            vchk = await conn.execute(
                text("SELECT status FROM vetter_runs WHERE run_id=:rid"),
                {"rid": vetter_run_id},
            )
            vrow = vchk.fetchone()
            if vrow is None:
                raise HTTPException(status_code=404, detail=f"Vetter run {vetter_run_id} not found")
            if vrow.status != "success":
                raise HTTPException(
                    status_code=400,
                    detail=f"Vetter run status is '{vrow.status}', must be 'success'",
                )

    async with _job_lock:
        async with engine.connect() as inner_conn:
            await _assert_no_running_job(inner_conn)
        run_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        background_tasks.add_task(_run_build, run_id, trace_id, ranking_run_id, vetter_run_id)
    return {
        "status": "started",
        "job": "build",
        "run_id": run_id,
        "trace_id": trace_id,
        "vetter_run_id": vetter_run_id,
    }


@app.get("/runs/latest")
async def get_latest_run():
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT run_id, status, portfolio_date, started_at, completed_at "
                "FROM portfolio_runs ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="No portfolio runs yet")
    return {
        "run_id": str(result.run_id),
        "status": result.status,
        "portfolio_date": str(result.portfolio_date) if result.portfolio_date else None,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
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
    return _fmt_row(result)


@app.get("/portfolio/latest")
async def get_latest_portfolio():
    async with engine.connect() as conn:
        run_row = await conn.execute(
            text(
                "SELECT run_id, regime, portfolio_date, selected_count, "
                "       portfolio_estimated_vol, avg_pairwise_correlation "
                "FROM portfolio_runs WHERE status='success' "
                "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
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
