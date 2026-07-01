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
import redis.asyncio as aioredis
from fastapi import FastAPI, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from app.select import (greedy_select, build_covariance, compute_weights, correlation_clusters,
                        compute_excluded_set, book_volatility, vol_target_exposure,
                        solve_beta_target_weights, _apply_all_caps)
from stock_strategy_shared.loader import load_strategy
from stock_strategy_shared.schemas.strategy import StrategyConfig
from stock_strategy_shared.investability import (
    avg_dollar_volume,
    below_investability_floor,
    DOLLAR_VOLUME_WINDOW,
)
from stock_strategy_shared.tracing import fmt_row, log_step, write_trace_file, mark_orphaned_runs_failed
from stock_strategy_shared.db import wait_for_db

STRATEGY_CONFIG_PATH = os.getenv("STRATEGY_CONFIG_PATH", "/strategies/quality_core_v1.yaml")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ARTIFACTS_PATH = os.getenv("ARTIFACTS_PATH", "")
REDIS_URL = os.getenv("REDIS_URL", "")
PIPELINE_STREAM = "stocker:pipeline_events"

# G6: a build runs in a detached BackgroundTask; an in-request crash (e.g. OOM in
# universe-scale covariance) leaves a 'running' portfolio_runs row that 409-wedges
# ALL future builds until a restart. _assert_no_running_job reclaims a 'running' row
# older than this as 'failed' so the chain self-heals (mirrors av-ingestor's
# STALE_INGEST_HOURS). A real build completes in well under this.
try:
    STALE_BUILD_HOURS = max(0.0, float(os.getenv("STALE_BUILD_HOURS", "3")))
except ValueError:
    STALE_BUILD_HOURS = 3.0

_MIN_EIGENVALUE = 1e-8  # numerical zero threshold for PSD matrix repair


_fmt_row = fmt_row


# Thematic overlay RETIRED — the engine is theme-agnostic. A hot sector is discovered
# organically by the factors and bounded by the correlation-cluster caps, not hard-wired
# to a named theme universe.


strategy: Optional[StrategyConfig] = None
engine: AsyncEngine
config_hash: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global strategy, engine, config_hash
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is required")
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=3,
                                 connect_args={"timeout": 60})

    # Synchronous: block until orphan cleanup done. DB is up in restart scenario,
    # so this completes quickly and prevents re-triggers from racing the cleanup.
    try:
        await wait_for_db(engine)
        async with engine.begin() as conn:
            await mark_orphaned_runs_failed(conn, "portfolio_runs", trace_job_type="portfolio_run")
        print("[portfolio-builder] DB connected; orphan cleanup done", flush=True)
    except Exception as exc:
        print(f"[portfolio-builder] WARN: orphan cleanup skipped: {exc}", flush=True)

    yield
    await engine.dispose()


app = FastAPI(title="portfolio-builder", lifespan=lifespan)

_job_lock = asyncio.Lock()


def _reload_strategy() -> None:
    """Re-read the strategy config at the start of each build so a deployed config
    change takes effect without a restart and all chain services converge on the
    same version — root-cause fix for the startup-cache config-version skew
    (divergent config_hash across a chain's steps). Reassigned under _job_lock."""
    global strategy, config_hash
    strategy, config_hash = load_strategy(STRATEGY_CONFIG_PATH)


async def _assert_no_running_job(conn) -> None:
    # G6: reclaim a STALE 'running' row first — an in-request crash (no except clause
    # fired, e.g. OOM mid-build) leaves a 'running' row that would otherwise 409-wedge
    # every future build until a manual restart. A row older than STALE_BUILD_HOURS is
    # an orphan (a real build finishes in minutes); mark it failed so the chain
    # self-heals. Startup mark_orphaned_runs_failed only covers process restarts.
    if STALE_BUILD_HOURS > 0:
        reclaimed = await conn.execute(
            text(
                "UPDATE portfolio_runs SET status='failed', completed_at=NOW(), "
                "error_message='RECLAIMED: running longer than STALE_BUILD_HOURS "
                "(orphaned in-request build)' "
                "WHERE status='running' "
                "AND started_at < NOW() - (:h * interval '1 hour') "
                "RETURNING run_id"
            ),
            {"h": STALE_BUILD_HOURS},
        )
        for r in reclaimed.fetchall():
            print(f"[portfolio-builder] reclaimed stale running build {r.run_id}", flush=True)

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
        "strategy": strategy.strategy_id if strategy else None,
        "config_hash": config_hash,
    }


# ── Trace helpers ───────────────────────────────────────────────────────────────────────────────────

async def _log_step(conn, trace_id, step_name, status, *, started_at=None,
                    input_summary=None, output_summary=None, warnings=None, error_message=None):
    await log_step(conn, trace_id, "portfolio-builder", step_name, status,
                   started_at=started_at, input_summary=input_summary,
                   output_summary=output_summary, warnings=warnings, error_message=error_message)


async def _write_trace_file(trace_id: str, run_id: str, status: str, started_at: datetime,
                            *, strategy_id: Optional[str] = None,
                            cfg_hash: Optional[str] = None, **extra) -> None:
    # G8: prefer the build's CAPTURED snapshot (strategy_id/cfg_hash) over the module
    # globals — a concurrent _reload_strategy must not change what this build records.
    await write_trace_file(
        engine, ARTIFACTS_PATH, trace_id, run_id, "portfolio_run", status, started_at,
        service_label="portfolio-builder",
        strategy_id=strategy_id if strategy_id is not None else (strategy.strategy_id if strategy else None),
        config_hash=cfg_hash if cfg_hash is not None else config_hash,
        **extra,
    )


# ── Build job ───────────────────────────────────────────────────────────────────────────────────

async def _run_build(
    run_id: str,
    trace_id: str,
    source_ranking_run_id: str,
    vetter_run_id: Optional[str],
    regime: str,
    portfolio_date,
    started_at: datetime,
    strat: StrategyConfig,
    cfg_hash: str,
    ranking_degraded: bool = False,
) -> None:
    # DB rows (portfolio_runs + execution_traces) were inserted by the handler inside
    # _job_lock before add_task was called — no lookup or INSERT needed here.
    # G8: `strat`/`cfg_hash` are the snapshot captured under the lock; use them (not
    # the module globals) so a concurrent _reload_strategy can't switch this build's
    # assumptions mid-flight.
    pb_cfg = strat.portfolio_builder

    try:
        await _do_build(run_id, trace_id, started_at, source_ranking_run_id, regime,
                        portfolio_date, pb_cfg, vetter_run_id, strat, cfg_hash,
                        ranking_degraded)
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
        await _write_trace_file(trace_id, run_id, "failed", started_at,
                                strategy_id=strat.strategy_id, cfg_hash=cfg_hash, error=err)
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
    strat: Optional[StrategyConfig] = None,
    cfg_hash: Optional[str] = None,
    ranking_degraded: bool = False,
) -> None:
    # G8: bind to the captured snapshot; fall back to the global only if a caller
    # (older test) didn't pass one.
    strat = strat if strat is not None else strategy
    cfg_hash = cfg_hash if cfg_hash is not None else config_hash
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

    # ── Step 2: load candidates (top-N by the quant rank — theme-agnostic) ───────
    t0 = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT ticker, rank, composite_score, factor_scores FROM rankings "
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

    # Per-name market beta (120d OLS vs SPY) for the optional beta-target overlay.
    # Stored display-only in rankings.factor_scores JSONB by the pipeline rank step.
    # Missing/unparseable beta is simply absent here → the solver imputes 1.0.
    beta_map: dict[str, float] = {}
    for r in candidates:
        fs = getattr(r, "factor_scores", None)
        if not fs:
            continue
        try:
            d = fs if isinstance(fs, dict) else json.loads(fs)
        except (ValueError, TypeError):
            continue
        bv = d.get("beta")
        if bv is not None:
            try:
                beta_map[r.ticker] = float(bv)
            except (ValueError, TypeError):
                pass

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
    excluded_risk_type: dict[str, str] = {}
    vetter_candidate_count: int | None = None
    vetter_unvetted_remaining: list[str] = []
    if vetter_run_id:
        async with engine.connect() as conn:
            vrun_row = (await conn.execute(
                text("SELECT candidate_count FROM vetter_runs WHERE run_id=:rid"),
                {"rid": vetter_run_id},
            )).fetchone()
            if vrun_row is not None:
                vetter_candidate_count = (
                    int(vrun_row.candidate_count) if vrun_row.candidate_count is not None else None
                )
            # Tickers the vetter actually evaluated (one decision row per ticker).
            vetted_rows = await conn.execute(
                text("SELECT ticker FROM vetter_decisions WHERE run_id = :rid"),
                {"rid": vetter_run_id},
            )
            vetted_tickers = {r.ticker for r in vetted_rows.fetchall()}
            exc_rows = await conn.execute(
                text(
                    "SELECT ticker, confidence, reason, risk_type FROM vetter_exclusions "
                    "WHERE run_id = :rid ORDER BY confidence DESC, ticker ASC"
                ),
                {"rid": vetter_run_id},
            )
            _exc_fetched = exc_rows.fetchall()
            vetter_excluded = [r.ticker for r in _exc_fetched]
            # risk_type per excluded ticker — only 'drawdown' (the deterministic
            # falling-knife backstop) is allowed to drop a HELD name from the target.
            excluded_risk_type = {r.ticker: (r.risk_type or "") for r in _exc_fetched}

        # Tickers that survived exclusion filtering but the vetter never actually
        # scanned — they could carry undisclosed risk. Surface in the log so an
        # operator can widen the vetter's candidate_count if portfolio-builder is
        # picking from beyond the vetter's coverage window.
        if vetted_tickers:
            vetter_unvetted_remaining = [t for t in candidate_tickers if t not in vetted_tickers]

    # Held-aware exclusion (see compute_excluded_set). LLM-judgement exclusions of
    # held names stay buy-side only; only a falling-knife (drawdown) exclusion may
    # drop a held name from the target so the delta engine orphan-exits it.
    _held_now: set[str] = set()
    async with engine.connect() as conn:
        _hrows = await conn.execute(text(
            "SELECT ticker FROM live_positions WHERE sync_run_id = ("
            "  SELECT run_id FROM alpaca_sync_runs WHERE status='success' "
            "  ORDER BY completed_at DESC NULLS LAST LIMIT 1)"
        ))
        _held_now = {r.ticker for r in _hrows.fetchall()}
    # Drawdown/vetter exclusions are a per-ticker TRADEABILITY overlay, applied at
    # SELECTION time (step 5) — NOT here. The excluded names stay in candidate_tickers
    # so they flow into the covariance + correlation-cluster build and keep acting as
    # single-linkage BRIDGES. Removing a falling-knife bridge before clustering would
    # fragment a real correlated theme (e.g. the golds in a sector-wide selloff) into
    # singletons, letting the survivors escape max_cluster_weight during the very
    # drawdown the cap exists to contain. See docs/architecture.md "Sub-decision:
    # cluster on the full universe, apply drawdown/vetter exclusions AFTER".
    excluded_set = compute_excluded_set(vetter_excluded, _held_now, excluded_risk_type)

    async with engine.begin() as conn:
        warn_lines: list[str] = []
        if vetter_excluded:
            warn_lines.append(f"LLM vetter excluded {len(vetter_excluded)} tickers: {vetter_excluded}")
        if vetter_unvetted_remaining:
            warn_lines.append(
                f"{len(vetter_unvetted_remaining)} candidate tickers were not evaluated by the vetter "
                f"(vetter.candidate_count={vetter_candidate_count}); they will pass through unfiltered. "
                f"Increase vetter.candidate_count to cover the portfolio-builder selection horizon. "
                f"unvetted={vetter_unvetted_remaining[:10]}{'…' if len(vetter_unvetted_remaining) > 10 else ''}"
            )
        await _log_step(
            conn, trace_id, "apply_vetter_exclusions", "success",
            started_at=t0,
            input_summary={"vetter_run_id": vetter_run_id, "vetter_candidate_count": vetter_candidate_count},
            output_summary={
                "excluded_count": len(vetter_excluded),
                "excluded_tickers": vetter_excluded,
                # Excluded names are retained in the candidate pool for the
                # covariance + cluster build and removed only at selection (step 5),
                # so this count still includes them by design.
                "candidates_retained_for_clustering": len(candidate_tickers),
                "selection_excluded_count": len(excluded_set),
                "unvetted_candidates_count": len(vetter_unvetted_remaining),
            },
            warnings=warn_lines or None,
        )

    # ── Step 3: load price data for covariance ───────────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    lookback_days = int(pb_cfg.covariance_window_days * 1.5)  # extra buffer for weekends/holidays
    async with engine.connect() as conn:
        price_rows = await conn.execute(
            text(
                "SELECT ticker, date, adjusted_close, close, volume FROM daily_prices "
                "WHERE ticker = ANY(:tickers) "
                "AND date <= :pd "
                "AND date >= :pd - :days * INTERVAL '1 day' "
                "ORDER BY ticker, date ASC"
            ),
            {"tickers": candidate_tickers, "pd": portfolio_date, "days": lookback_days},
        )
        prices_df = pd.DataFrame(
            price_rows.fetchall(),
            columns=["ticker", "date", "adjusted_close", "close", "volume"],
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
    universe_cfg = strat.universe
    min_price = universe_cfg.min_price
    min_avg_dv = universe_cfg.min_avg_dollar_volume_20d

    # Latest adjusted_close + canonical avg DOLLAR volume (close × volume over the last
    # DOLLAR_VOLUME_WINDOW sessions) from the already-loaded prices_df — the SAME
    # definition the factor universe filter and the delta below-floor exit use
    # (shared.investability), so "investable" means the same in every step. Previously
    # this read fundamentals.avg_volume (adjusted_close × volume, ingestion-time), which
    # could disagree with the factor gate and spuriously drop/keep candidates.
    _sub = prices_df[prices_df["ticker"].isin(rankable_tickers)].sort_values("date")
    latest_prices = _sub.groupby("ticker")["adjusted_close"].last().to_dict()
    avg_dv_map: dict[str, float] = {}
    for _t, _g in _sub.groupby("ticker"):
        _dv = avg_dollar_volume(_g["close"].tolist(), _g["volume"].tolist(),
                                window=DOLLAR_VOLUME_WINDOW)
        if _dv is not None:
            avg_dv_map[_t] = _dv

    # Single shared floor test for the decision; split derived only for the log.
    universe_filtered = {
        t for t in rankable_tickers
        if below_investability_floor(latest_prices.get(t), avg_dv_map.get(t),
                                     min_price=min_price, min_avg_dollar_volume=min_avg_dv)
    }
    price_filtered = [t for t in universe_filtered
                      if latest_prices.get(t) is not None and latest_prices[t] < min_price]
    _price_filtered_set = set(price_filtered)
    dv_filtered = [t for t in universe_filtered if t not in _price_filtered_set]
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
    cov, tickers_dropped_obs, raw_corr = build_covariance(
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

    # Portfolio-level correlation summary for the audit log (avg pairwise correlation
    # across the full selectable universe). The highest-correlated-pair-among-selected
    # stat is computed separately from cov.loc[selected] at step 5, so it stays correct
    # even after the selectable pool is reduced by exclusions.
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

    # ── Step 4b: build correlation clusters (the concentration-cap grouping) ──────────────────────────────────────
    # Clusters replace sector labels for capping concentration. Provider sectors
    # are unreliable for risk grouping (GOOG → Communication Services; gold miners
    # span several sectors), so we group by how names actually co-move, derived
    # from the same covariance matrix the optimizer already built.
    # Cluster on the RAW correlation (pre-shrinkage). Using the shrunk cov here
    # would deflate every pairwise correlation by the shrinkage factor and wrongly
    # split genuine co-movers into singletons (e.g. gold miners correlated 0.79-0.92
    # reading 0.63-0.74 after 0.20 shrinkage, mostly falling below a 0.70 threshold).
    cluster_map = correlation_clusters(raw_corr, threshold=pb_cfg.cluster_correlation_threshold)
    cluster_sizes: dict[str, int] = {}
    for _cid in cluster_map.values():
        cluster_sizes[_cid] = cluster_sizes.get(_cid, 0) + 1
    largest_clusters = sorted(
        ((cid, n) for cid, n in cluster_sizes.items() if n > 1),
        key=lambda kv: (-kv[1], kv[0]),
    )[:10]
    async with engine.begin() as conn:
        await _log_step(
            conn, trace_id, "build_clusters", "success",
            started_at=t0,
            input_summary={
                "cluster_correlation_threshold": pb_cfg.cluster_correlation_threshold,
                "max_cluster_weight": pb_cfg.max_cluster_weight,
                "ticker_count": len(cluster_map),
            },
            output_summary={
                "cluster_count": len(cluster_sizes),
                "multi_member_clusters": len(largest_clusters),
                "largest_clusters": [{"cluster_id": cid, "size": n} for cid, n in largest_clusters],
            },
        )

    # ── Step 4c: load sector data (INFORMATIONAL ONLY — no longer gates selection) ───────────────────────────────
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

    # ── Step 4d: load current portfolio holdings for turnover penalty ─────────────────────────────────────────────────
    # Merge both sources: previous portfolio target AND actual broker positions.
    # A ticker actually held at the broker (live_positions qty > 0) deserves the
    # continuity preference even if it wasn't in the last portfolio target — e.g.
    # positions received via corporate actions, or cases where portfolio_holdings
    # had fewer rows than live_positions after a restart.
    current_holdings: set[str] = set()
    if pb_cfg.turnover_penalty > 0.0:
        async with engine.connect() as conn:
            hold_rows = await conn.execute(text(
                "SELECT ph.ticker FROM portfolio_holdings ph "
                "JOIN portfolio_runs pr ON pr.run_id = ph.run_id "
                "WHERE pr.status = 'success' "
                "ORDER BY pr.completed_at DESC NULLS LAST LIMIT 1"
            ))
            current_holdings = {r.ticker for r in hold_rows.fetchall()}
            live_rows = await conn.execute(text(
                "SELECT ticker FROM live_positions "
                "WHERE sync_run_id = ("
                "  SELECT run_id FROM alpaca_sync_runs "
                "  WHERE status = 'success' "
                "  ORDER BY completed_at DESC LIMIT 1"
                ") AND qty > 0"
            ))
            current_holdings |= {r.ticker for r in live_rows.fetchall()}

    # ── Step 5: greedy selection ────────────────────────────────────────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)

    # Apply drawdown/vetter exclusions HERE — after clustering, before selection.
    # The excluded names stayed in the covariance + cluster build (so they bridge
    # single-linkage clusters and the survivors keep correct cluster identity), but
    # they must never be bought. Drop them from the selectable pool (scores/cov);
    # cluster_map deliberately retains their membership. See docs/architecture.md
    # "Sub-decision: cluster on the full universe, apply ... exclusions AFTER".
    selection_excluded = [t for t in available_tickers if t in excluded_set]
    if selection_excluded:
        available_tickers = [t for t in available_tickers if t not in excluded_set]
        scores = scores[available_tickers]
        cov = cov.loc[available_tickers, available_tickers]

    # Optionally exclude candidates with a negative composite score before selection
    negative_excluded: list[str] = []
    if pb_cfg.require_positive_composite_score:
        negative_excluded = [t for t in available_tickers if scores_map[t] < 0]
        if negative_excluded:
            pos_tickers = [t for t in available_tickers if scores_map[t] >= 0]
            scores = scores[pos_tickers]
            cov = cov.loc[pos_tickers, pos_tickers]

    # Concentration is capped on TWO independent dimensions:
    #   1. correlation CLUSTER (sector_map=cluster_map + max_cluster_weight) — bounds
    #      correlated micro-groups (e.g. tankers);
    #   2. AV SECTOR (av_sector_map=sector_map + max_sector_weight) — bounds a whole
    #      sector spread across several clusters (e.g. energy = tankers+refiners+E&P),
    #      which the cluster cap alone cannot see.
    # The greedy count cap and weight redistribution are group-agnostic.
    selected = greedy_select(
        scores, cov,
        target=pb_cfg.max_positions,
        sector_map=cluster_map,
        max_sector_weight=pb_cfg.max_cluster_weight,
        current_holdings=current_holdings if pb_cfg.turnover_penalty > 0.0 else None,
        turnover_penalty=pb_cfg.turnover_penalty,
        max_tickers_per_sector=pb_cfg.max_tickers_per_cluster,
        av_sector_map=sector_map,
        max_av_sector_weight=pb_cfg.max_sector_weight,
        selection_vol_aversion=pb_cfg.selection_vol_aversion,
    )
    selected_tickers = [s["ticker"] for s in selected]
    selected_negative_score_count = sum(1 for s in selected if s["composite_score"] < 0)

    # Empty-selection guard: greedy_select can return [] (e.g. every candidate
    # blocked by sector/cluster/count caps, or an empty candidate pool that slipped
    # past the earlier guards). compute_weights' equal_weight path does 1.0/n with
    # n=0 → ZeroDivisionError, crashing the build mid-flight. Default to a CONTROLLED
    # no-feasible-portfolio failure: mark the run failed with a clear diagnostic and
    # write NO holdings, rather than crashing with an opaque ZeroDivisionError.
    if not selected:
        raise RuntimeError(
            "no feasible portfolio: greedy_select returned 0 holdings "
            f"(candidates={len(candidate_tickers)}, max_positions={pb_cfg.max_positions}) "
            "— every candidate was blocked by caps or the candidate pool was empty"
        )

    # Compute weights according to configured method
    weights = compute_weights(
        selected, cov,
        method=pb_cfg.weighting,
        max_position_weight=pb_cfg.max_position_weight,
        sector_map=cluster_map,
        max_sector_weight=pb_cfg.max_cluster_weight,
        av_sector_map=sector_map,
        max_av_sector_weight=pb_cfg.max_sector_weight,
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

    # ── Beta-target overlay (optional, reversible via beta_target_enabled) ────────
    # Reweight the sum-to-1 invested book toward a target market beta. Runs AFTER
    # base weighting + caps so it tilts within the SELECTED names only; re-applies
    # the position + cluster + sector caps after each tilt so no concentration limit
    # is breached. Default-OFF → weights are untouched (current behaviour). Placed
    # BEFORE exposure scaling so the target is on the invested relative composition.
    beta_target_enabled = bool(getattr(pb_cfg, "beta_target_enabled", False))
    beta_target_info: dict | None = None
    if beta_target_enabled and len(weights) > 1:
        _beta_constraints: list[tuple[dict[str, str], float]] = []
        if pb_cfg.max_cluster_weight < 1.0:
            _beta_constraints.append((cluster_map, pb_cfg.max_cluster_weight))
        if pb_cfg.max_sector_weight < 1.0:
            _beta_constraints.append((sector_map, pb_cfg.max_sector_weight))
        # Iterate tilt → re-cap to a fixpoint: the caps can pull beta back off target
        # (if the target needs concentrating a capped group), so a few passes settle
        # on the closest cap-respecting book.
        for _bpass in range(3):
            weights, beta_target_info = solve_beta_target_weights(
                weights, beta_map, pb_cfg.beta_target,
                max_position_weight=max_pw,
            )
            if _beta_constraints:
                weights = _apply_all_caps(weights, max_pw, _beta_constraints)
                _s = sum(weights.values())
                if _s > 0:
                    weights = {t: w / _s for t, w in weights.items()}
        # Achieved beta AFTER caps (the number that actually ships).
        _achieved = sum(weights[t] * beta_map.get(t, 1.0) for t in weights)
        _infeasible = abs(_achieved - pb_cfg.beta_target) > pb_cfg.beta_tolerance
        beta_target_info = {
            **(beta_target_info or {}),
            "achieved_beta": round(_achieved, 4),
            "target": pb_cfg.beta_target,
            "tolerance": pb_cfg.beta_tolerance,
            "infeasible": bool(_infeasible),
        }
        print(
            f"[portfolio-builder] beta_target={pb_cfg.beta_target:.3f} "
            f"base_beta={beta_target_info.get('base_beta')} achieved={_achieved:.3f} "
            f"tol={pb_cfg.beta_tolerance:.2f} "
            f"{'INFEASIBLE (closest feasible shipped)' if _infeasible else 'on-target'}",
            flush=True,
        )

    # Exposure scaling = fixed cash_reserve buffer + optional volatility targeting.
    # `weights` sums to 1.0 here (fully-invested relative weights), so its vol IS the
    # book vol we target. cash_reserve sets the max investable exposure (a buffer so
    # broker buying-power reservations don't exhaust capacity); vol-targeting may
    # de-lever FURTHER when the book's ex-ante vol exceeds vol_target.
    cash_reserve = getattr(pb_cfg, "cash_reserve", 0.0)
    max_exposure = 1.0 - cash_reserve
    vol_target_enabled = bool(getattr(pb_cfg, "vol_target_enabled", False))
    book_vol_full_invested = book_volatility(weights, cov) if vol_target_enabled else None
    if vol_target_enabled:
        exposure = vol_target_exposure(
            book_vol_full_invested, pb_cfg.vol_target,
            min_exposure=pb_cfg.vol_target_min_exposure,
            max_exposure=max_exposure,
        )
        if book_vol_full_invested <= 0.0:
            print(
                "[portfolio-builder] WARNING: vol-target enabled but book vol is "
                "0/degenerate — failing OPEN (no de-lever, exposure=max)"
            )
    else:
        exposure = max_exposure
    if exposure < 1.0 - 1e-12:
        weights = {t: w * exposure for t, w in weights.items()}
    if vol_target_enabled:
        print(
            f"[portfolio-builder] vol_target={pb_cfg.vol_target:.3f} "
            f"book_vol={book_vol_full_invested:.4f} min_exp={pb_cfg.vol_target_min_exposure:.2f} "
            f"max_exp={max_exposure:.3f} → exposure={exposure:.3f} "
            f"(cash={1.0 - sum(weights.values()):.3f})"
        )
    elif cash_reserve > 0.0:
        print(f"[portfolio-builder] cash_reserve={cash_reserve:.3f}: weights scaled to sum={sum(weights.values()):.4f}")

    # M5: Compute and log per-sector weights post-build (INFORMATIONAL — sectors
    # no longer gate selection; the binding concentration cap is by cluster below).
    sector_weights: dict[str, float] = {}
    for _t, _w in weights.items():
        _sector = sector_map.get(_t, "Unknown")
        sector_weights[_sector] = sector_weights.get(_sector, 0.0) + _w
    print(
        f"[portfolio-builder] sector weights post-build (informational): "
        + ", ".join(f"{s}={w:.3f}" for s, w in sorted(sector_weights.items()))
    )

    # Per-cluster weights — this is the cap that actually binds.
    cluster_weights: dict[str, float] = {}
    for _t, _w in weights.items():
        _cid = cluster_map.get(_t, _t)
        cluster_weights[_cid] = cluster_weights.get(_cid, 0.0) + _w
    print(
        f"[portfolio-builder] cluster weights post-build: "
        + ", ".join(f"{c}={w:.3f}" for c, w in sorted(cluster_weights.items(), key=lambda kv: -kv[1])[:8])
    )
    max_cw = pb_cfg.max_cluster_weight
    for _cid, _cw in cluster_weights.items():
        if _cw > max_cw + 1e-6:
            _members = [t for t in selected_tickers if cluster_map.get(t, t) == _cid]
            print(
                f"[portfolio-builder] WARNING: cluster '{_cid}' weight {_cw:.3f} "
                f"exceeds cap {max_cw} (members: {_members})"
            )

    # Final portfolio volatility using actual weights
    w_vec = np.array([weights[t] for t in selected_tickers])
    final_cov = cov.loc[selected_tickers, selected_tickers].values
    portfolio_vol = float(np.sqrt(max(float(w_vec @ final_cov @ w_vec), 1e-12)))

    # Highest-correlated pair among the selected names, for the trace (informational).
    # Derive the correlation submatrix straight from the label-indexed cov restricted
    # to selected_tickers — NOT from the module-level `corr_matrix`, whose positional
    # order tracks the pre-selection-exclusion `available_tickers` and would mis-index
    # after that pool is reduced at step 5.
    if len(selected_tickers) > 1:
        sel_cov = cov.loc[selected_tickers, selected_tickers].values
        sel_std = np.sqrt(np.diag(sel_cov))
        sel_outer = np.outer(sel_std, sel_std)
        with np.errstate(invalid="ignore", divide="ignore"):
            sub_corr = np.where(sel_outer > 0, sel_cov / sel_outer, 0.0)
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
    if beta_target_info and beta_target_info.get("infeasible"):
        sel_warnings.append(
            f"beta_target_infeasible: target {pb_cfg.beta_target:.2f} not reachable "
            f"under caps/selected names — shipped closest feasible book "
            f"(achieved {beta_target_info.get('achieved_beta')})"
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
                "selection_vol_aversion": pb_cfg.selection_vol_aversion,
                "max_position_weight": pb_cfg.max_position_weight,
                "max_cluster_weight": pb_cfg.max_cluster_weight,
                "cluster_correlation_threshold": pb_cfg.cluster_correlation_threshold,
                "cluster_count": len(cluster_sizes),
                "sector_map_size": len(sector_map),
                "turnover_penalty": pb_cfg.turnover_penalty,
                "current_holdings_count": len(current_holdings),
            },
            output_summary={
                "selected_count": len(selected),
                "selected_negative_score_count": selected_negative_score_count,
                "portfolio_estimated_vol": round(portfolio_vol, 4),
                "vol_target_enabled": vol_target_enabled,
                "vol_target": pb_cfg.vol_target if vol_target_enabled else None,
                "book_vol_full_invested": round(book_vol_full_invested, 4) if book_vol_full_invested is not None else None,
                "vol_target_exposure": round(exposure, 4),
                "beta_target_enabled": beta_target_enabled,
                "beta_target": pb_cfg.beta_target if beta_target_enabled else None,
                "beta_target_info": beta_target_info,
                "invested_fraction": round(sum(weights.values()), 4),
                "avg_candidate_pool_correlation": round(avg_pairwise_corr, 4),
                "highest_corr_pair": highest_corr_pair,
                "weight_min": round(min(weight_values), 6),
                "weight_max": round(max(weight_values), 6),
                "cash_residual_before_normalize": cash_residual_before_normalize,
                "sector_weights": {s: round(w, 6) for s, w in sorted(sector_weights.items())},
                "cluster_weights": {c: round(w, 6) for c, w in sorted(cluster_weights.items(), key=lambda kv: -kv[1])},
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
                    " adj_score, portfolio_vol_at_add, cluster_id) "
                    "VALUES (:run_id, :src, :sid, :regime, :pd, "
                    "        :ticker, :pos, :weight, :cs, :orank, :adj, :pvol, :cluster) "
                    "ON CONFLICT (run_id, ticker) DO UPDATE SET "
                    "  weight=EXCLUDED.weight, position=EXCLUDED.position, "
                    "  composite_score=EXCLUDED.composite_score, original_rank=EXCLUDED.original_rank, "
                    "  adj_score=EXCLUDED.adj_score, portfolio_vol_at_add=EXCLUDED.portfolio_vol_at_add, "
                    "  cluster_id=EXCLUDED.cluster_id"
                ),
                {
                    "run_id": run_id,
                    "src": source_ranking_run_id,
                    "sid": strat.strategy_id,
                    "regime": regime,
                    "pd": portfolio_date,
                    "ticker": ticker,
                    "pos": item["position"],
                    "weight": weights[ticker],
                    "cs": round(item["composite_score"], 6),
                    "orank": rank_map.get(ticker),
                    "adj": round(item["adj_score"], 6),
                    "pvol": round(item["portfolio_vol_at_add"], 6),
                    # Persist the correlation cluster only when it has co-moving
                    # peers (multi-member); a singleton cluster is "no applicable
                    # cluster" → NULL, so the UI shows a dash rather than the
                    # ticker's own name as a pseudo-cluster.
                    "cluster": (
                        _cid if (_cid := cluster_map.get(ticker, ticker))
                        and cluster_sizes.get(_cid, 1) > 1 else None
                    ),
                },
            )

        # Persist the FULL candidate-pool cluster map (not just selected holdings) so
        # the screener can show a cluster for every ranked candidate, not only the
        # ~max_positions held names. Only multi-member memberships are stored; a
        # missing row reads as "no applicable cluster" (singleton).
        for _t, _cid in cluster_map.items():
            if cluster_sizes.get(_cid, 1) <= 1:
                continue
            await conn.execute(
                text(
                    "INSERT INTO candidate_clusters (run_id, portfolio_date, ticker, cluster_id) "
                    "VALUES (:rid, :pd, :ticker, :cid) "
                    "ON CONFLICT (run_id, ticker) DO UPDATE SET cluster_id=EXCLUDED.cluster_id"
                ),
                {"rid": run_id, "pd": portfolio_date, "ticker": _t, "cid": _cid},
            )

        # G2 degraded gate: a build that selects FEWER than min_selected names is the
        # signature of a transiently thin ranking. Record success (don't halt the
        # chain) but FLAG it degraded so the delta engine treats the target like an
        # empty one (holds the book) — a bad-data day can never mass-orphan-exit.
        min_selected = getattr(pb_cfg, "min_selected", 0) or 0
        degraded = bool(min_selected > 0 and len(selected) < min_selected) or bool(ranking_degraded)
        if degraded:
            _why = ("source ranking degraded" if ranking_degraded
                    else f"selected {len(selected)} < min_selected {min_selected}")
            print(
                f"[portfolio-builder] run {run_id} DEGRADED ({_why}) — delta will hold the book",
                flush=True
            )
        await conn.execute(
            text(
                "UPDATE portfolio_runs SET "
                "  status='success', completed_at=:now, "
                "  candidate_count=:cc, selected_count=:sc, degraded=:deg, "
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
                "deg": degraded,
                "cw": pb_cfg.covariance_window_days,
                "apc": round(avg_pairwise_corr, 6),
                "pvol": round(portfolio_vol, 6),
            },
        )

        # G5 supersede: this build is now the authoritative target for its ranking.
        # Stamp any PRIOR successful build for the SAME source_ranking_run_id as
        # superseded so "latest" is explicit (a manual re-run supersedes a cron run)
        # rather than implied by completed_at ordering alone.
        await conn.execute(
            text(
                "UPDATE portfolio_runs SET superseded_at=:now "
                "WHERE source_ranking_run_id=:src AND run_id<>:rid "
                "AND status='success' AND superseded_at IS NULL"
            ),
            {"now": completed_at, "src": source_ranking_run_id, "rid": run_id},
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
        strategy_id=strat.strategy_id, cfg_hash=cfg_hash,
        regime=regime,
        portfolio_date=str(portfolio_date),
        degraded=degraded,
        selected_count=len(selected),
        selected_negative_score_count=selected_negative_score_count,
        tickers_dropped_insufficient_obs=len(tickers_dropped_obs),
        portfolio_estimated_vol=round(portfolio_vol, 4),
        avg_pairwise_correlation=round(avg_pairwise_corr, 4),
        highest_corr_pair=highest_corr_pair,
        cash_residual_before_normalize=cash_residual_before_normalize,
        sector_weights={s: round(w, 6) for s, w in sorted(sector_weights.items())},
        cluster_weights={c: round(w, 6) for c, w in sorted(cluster_weights.items(), key=lambda kv: -kv[1])},
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
            "max_cluster_weight": pb_cfg.max_cluster_weight,
            "cluster_correlation_threshold": pb_cfg.cluster_correlation_threshold,
        },
        holdings=holdings_detail,
    )

    await _publish_portfolio_complete(run_id, str(portfolio_date))


async def _publish_portfolio_complete(run_id: str, portfolio_date: str) -> None:
    """Publish portfolio_builder.complete to the pipeline Redis stream.

    Non-blocking: failures are logged and swallowed so they never affect
    the portfolio run's own success/failure status.
    """
    if not REDIS_URL:
        print("[portfolio-builder] REDIS_URL not set — skipping pipeline event publish")
        return
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            await r.xadd(
                PIPELINE_STREAM,
                {
                    "event": "portfolio_builder.complete",
                    "run_id": run_id,
                    "portfolio_date": portfolio_date,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
            print(f"[portfolio-builder] published portfolio_builder.complete (run_id={run_id})", flush=True)
        finally:
            await r.aclose()
    except Exception as exc:
        print(f"[portfolio-builder] WARNING: failed to publish pipeline event: {exc}", flush=True)


# ── Endpoints ───────────────────────────────────────────────────────────────────────────────────

@app.post("/jobs/build")
async def start_build(
    background_tasks: BackgroundTasks,
    ranking_run_id: Optional[str] = None,
    vetter_run_id: Optional[str] = None,
):
    # Pre-validate UUIDs before touching the DB.
    if ranking_run_id:
        try:
            uuid.UUID(ranking_run_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="ranking_run_id must be a valid UUID")
    if vetter_run_id:
        try:
            uuid.UUID(vetter_run_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="vetter_run_id must be a valid UUID")

    # Pre-validate ranking + vetter runs outside the lock so errors return fast.
    async with engine.connect() as conn:
        if ranking_run_id:
            chk = await conn.execute(
                text("SELECT run_id, regime, rank_date, degraded, config_hash FROM ranking_runs WHERE run_id=:rid AND status='success'"),
                {"rid": ranking_run_id},
            )
        else:
            chk = await conn.execute(
                text("SELECT run_id, regime, rank_date, degraded, config_hash FROM ranking_runs WHERE status='success' ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1")
            )
        rr = chk.fetchone()
        if rr is None:
            raise HTTPException(
                status_code=400,
                detail="no successful ranking run found — run: make rank first",
            )
        source_ranking_run_id = str(rr.run_id)
        regime = rr.regime
        portfolio_date = rr.rank_date
        ranking_config_hash = rr.config_hash
        # P2: propagate a degraded ranking into the portfolio so the delta engine holds
        # the book (the degraded gate at its source — a thin ranking must not rotate).
        ranking_degraded = bool(rr.degraded)

        if vetter_run_id:
            vchk = await conn.execute(
                text("SELECT status, source_ranking_run_id FROM vetter_runs WHERE run_id=:rid"),
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
            # Seam guard: the explicit vetter_run_id MUST be bound to the SAME ranking
            # run we're building from. The auto-select path below scopes by
            # source_ranking_run_id; the explicit path used to skip that check, so a
            # mismatched id (manual API call) would apply exclusions computed against a
            # DIFFERENT ranking's candidate pool — a silent vetter/builder split brain.
            v_src = str(vrow.source_ranking_run_id) if vrow.source_ranking_run_id else None
            if v_src != source_ranking_run_id:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Vetter run {vetter_run_id} was produced for ranking run "
                        f"{v_src}, not the ranking run being built ({source_ranking_run_id}). "
                        "Pass a vetter run bound to this ranking, or omit vetter_run_id "
                        "to auto-select the correct one."
                    ),
                )
        else:
            # Auto-select the latest successful vetter run for this same ranking run.
            # The vetter is not optional: if it has not run for today's ranking,
            # portfolio construction is blocked so exclusions are always applied.
            vauto = await conn.execute(
                text(
                    "SELECT run_id FROM vetter_runs "
                    "WHERE status='success' AND source_ranking_run_id=:src "
                    "ORDER BY completed_at DESC NULLS LAST, started_at DESC LIMIT 1"
                ),
                {"src": source_ranking_run_id},
            )
            vauto_row = vauto.fetchone()
            if vauto_row is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"No successful vetter run found for ranking run {source_ranking_run_id}. "
                        "The vetter must complete before the portfolio can be built. "
                        "Run the vetter first (POST /jobs/vet on the llm-vetter service)."
                    ),
                )
            vetter_run_id = str(vauto_row.run_id)

    async with _job_lock:
        _reload_strategy()  # pick up any deployed config change; converge across services
        # G8: snapshot the reloaded config under the lock and thread it through the
        # detached build, so a concurrent _reload_strategy can never switch this
        # build's strategy/config_hash mid-flight (the globals are no longer read
        # inside _do_build).
        strat_snap = strategy
        cfg_hash_snap = config_hash
        # Config-consistency guard (root-cause fix for the delta config-skew deadlock):
        # NEVER build a portfolio under one config from a ranking scored under a
        # DIFFERENT config. That cross-config portfolio (new-config caps/weights applied
        # to an old-config ranking) is exactly what made the delta's config-skew guard
        # fail-close (ranking d9630 vs delta a1bffda) — a silent deadlock after a config
        # edit while an old ranking was still "latest". Refuse LOUDLY instead so the
        # operator re-ranks under the current config first. In a normal chain the rank
        # step runs under the same current config, so this only trips on a stale-ranking
        # race / mid-chain edit.
        if ranking_config_hash and cfg_hash_snap and ranking_config_hash != cfg_hash_snap:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"ranking {source_ranking_run_id} was scored under config "
                    f"{ranking_config_hash} but the builder's current config is "
                    f"{cfg_hash_snap} — refusing to build a cross-config portfolio "
                    "(re-run the pipeline rank step under the current config first)."
                ),
            )
        async with engine.connect() as inner_conn:
            await _assert_no_running_job(inner_conn)
        run_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO execution_traces "
                    "(trace_id, job_type, status, root_run_id, strategy_id, config_hash, started_at) "
                    "VALUES (:tid, 'portfolio_run', 'running', :rid, :sid, :ch, :now)"
                ),
                {"tid": trace_id, "rid": run_id, "sid": strat_snap.strategy_id, "ch": cfg_hash_snap, "now": started_at},
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
                    "sid": strat_snap.strategy_id, "ch": cfg_hash_snap,
                    "regime": regime, "pd": portfolio_date, "now": started_at,
                },
            )
        background_tasks.add_task(
            _run_build, run_id, trace_id,
            source_ranking_run_id, vetter_run_id,
            regime, portfolio_date, started_at,
            strat_snap, cfg_hash_snap, ranking_degraded,
        )
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
                "SELECT run_id, status, portfolio_date, error_message, started_at, completed_at "
                "FROM portfolio_runs ORDER BY portfolio_date DESC, completed_at DESC NULLS LAST LIMIT 1"
            )
        )
        result = row.fetchone()
    if result is None:
        raise HTTPException(status_code=404, detail="No portfolio runs yet")
    return {
        "run_id": str(result.run_id),
        "status": result.status,
        "portfolio_date": str(result.portfolio_date) if result.portfolio_date else None,
        "error_message": result.error_message,
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
    }


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="run_id must be a valid UUID")
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
                "WITH names AS ("
                "  SELECT DISTINCT ON (ticker) ticker, name FROM universe_tickers "
                "  ORDER BY ticker, snapshot_id DESC"
                ") "
                "SELECT ph.ticker, n.name, ph.position, ph.weight, ph.cluster_id, "
                "       ph.composite_score, ph.original_rank, "
                "       ph.adj_score, ph.portfolio_vol_at_add "
                "FROM portfolio_holdings ph "
                "LEFT JOIN names n ON n.ticker = ph.ticker "
                "WHERE ph.run_id = :rid ORDER BY ph.position ASC"
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
