"""G1 — per-config historical simulation.

The persisted-replay backtest (main.py) can only re-score portfolio_runs that
were ALREADY built under whatever config produced them; it cannot answer "what
would THIS candidate config have done?" — the one question a strategy evaluator
actually needs. Config-replay closes that gap: for each historical rebalance
date it re-ranks and re-selects under a CANDIDATE config, using the SAME
deterministic code the live chain runs (vendored byte-identical in app/_vendor),
then feeds the resulting synthetic portfolio_runs to the de-biased run_backtest.

No look-ahead by construction:
  - factor values are the PERSISTED point-in-time factor_scores for each date
    (computed historically on that date; never recomputed with future data);
  - covariance / regime / beta for date D use ONLY prices with date <= D;
  - run_backtest already fills at D+1 (see simulate.py G3).

What config-replay models (all config-driven, so a config change changes the
result): factor_weights (+ regime detection & weighting), required_factors,
min_non_null_factors, min_score_percentile, candidate_count, universe floors
(min_price / min_avg_dollar_volume_20d), do_not_buy, max_positions, weighting,
position/cluster/sector caps, max_tickers_per_cluster, selection_vol_aversion,
require_positive_composite_score, cash_reserve, beta_target, vol_target.

What it deliberately does NOT model (documented, surfaced in the result caveats):
  - vetter exclusions — a RUN-TIME signal (LLM/drawdown), not a config knob; a
    config-replay of the pure config must not bake in one historical vet run.
  - turnover_penalty continuity — replay is holdings-agnostic (matches the
    builder's default turnover_penalty=0 source-of-truth behaviour).
  - as-of sector labels — the latest sector per ticker is used for the sector
    cap (labels are near-static; a per-date as-of join would be marginal).

Pure module: all DB access stays in main.py, which loads the frames and calls
these functions. That keeps the whole composer unit-testable without a database.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from stock_strategy_shared.investability import (
    avg_dollar_volume,
    below_investability_floor,
    DOLLAR_VOLUME_WINDOW,
)
from stock_strategy_shared.schemas.strategy import StrategyConfig

from app._vendor.rank import rank_universe, FACTORS
from app._vendor.regime import detect_regime, resolve_confirmed_regime
from app._vendor.select import (
    greedy_select,
    build_covariance,
    compute_weights,
    correlation_clusters,
    book_volatility,
    vol_target_exposure,
    solve_beta_target_weights,
    _apply_all_caps,
)


def factor_df_from_rows(rows: list[dict]) -> pd.DataFrame:
    """Build the {ticker, <factor>...} frame rank_universe expects from persisted
    factor_scores rows. Mirrors the pipeline rank step's `_factor_dict_from_row`:
    prefer the canonical `scores` JSONB, fall back to per-factor columns; a missing
    factor is NaN (rank_universe renormalizes over the non-null factors)."""
    out = []
    for r in rows:
        raw = r.get("scores")
        if raw:
            d = raw if isinstance(raw, dict) else _loads(raw)
            vals = {f: (float(d[f]) if d.get(f) is not None else float("nan")) for f in FACTORS}
        else:
            vals = {f: (float(r[f]) if r.get(f) is not None else float("nan")) for f in FACTORS}
        out.append({"ticker": r["ticker"], **vals})
    return pd.DataFrame(out)


def _loads(raw):
    import json
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def confirmed_regime_for_date(
    spy_upto: pd.DataFrame,
    config: StrategyConfig,
    raw_history: list[str],
    prior_confirmed: str | None,
) -> tuple[str, str]:
    """(raw_regime, confirmed_regime) for one rebalance date, using only SPY prices
    with date <= that date. `raw_history` is prior raw regimes most-recent-first;
    `prior_confirmed` is the last confirmed regime. Falls back to the first
    configured regime when there is insufficient SPY history for the slow SMA (a
    cold start early in the sample), so the replay never crashes on a short window.
    Confirmation is applied at rebalance-date granularity — inert when
    regime_weighting_enabled is false (regime then only labels periods)."""
    rd = config.regime_detection
    try:
        raw = detect_regime(spy_upto, rd)["raw_regime"]
    except (ValueError, RuntimeError):
        raw = next(iter(rd.regimes.keys()))
    confirmed = resolve_confirmed_regime(
        raw, raw_history, prior_confirmed, rd.confirmation_days
    )
    return raw, confirmed


def _beta_map(prices_upto: pd.DataFrame, tickers: list[str], lookback: int) -> dict[str, float]:
    """Per-ticker OLS beta vs SPY over the trailing `lookback` sessions (prices <=
    the rebalance date), clipped to [0, 3] to match the falling-knife/overlay beta.
    Only needed when beta_target is enabled; missing → solver imputes 1.0."""
    if "SPY" not in prices_upto["ticker"].values:
        return {}
    piv = (
        prices_upto.drop_duplicates(subset=["date", "ticker"], keep="last")
        .pivot(index="date", columns="ticker", values="adjusted_close")
        .sort_index()
        .astype(float)
    )
    if len(piv) > lookback + 1:
        piv = piv.iloc[-(lookback + 1):]
    rets = np.log(piv / piv.shift(1)).dropna(how="all")
    if "SPY" not in rets.columns:
        return {}
    spy = rets["SPY"]
    var_spy = float(spy.var())
    out: dict[str, float] = {}
    if var_spy <= 0:
        return out
    for t in tickers:
        if t not in rets.columns:
            continue
        pair = pd.concat([rets[t], spy], axis=1).dropna()
        if len(pair) < 2:
            continue
        cov_ts = float(pair.iloc[:, 0].cov(pair.iloc[:, 1]))
        out[t] = float(np.clip(cov_ts / var_spy, 0.0, 3.0))
    return out


def build_target_for_date(
    factor_df: pd.DataFrame,
    prices_upto: pd.DataFrame,
    config: StrategyConfig,
    regime: str,
    sector_map: dict[str, str],
) -> list[dict]:
    """Re-rank + re-select for ONE rebalance date under `config`, returning
    [{ticker, weight}] (sums to <= 1.0; < 1.0 when cash_reserve / vol_target
    de-levers). Composes the vendored rank_universe + builder select functions in
    the SAME order and with the SAME parameters as portfolio-builder's _do_build.
    Empty/degenerate selection → [] (the caller skips that date's period)."""
    pb = config.portfolio_builder

    # ── rank under this config ────────────────────────────────────────────────
    ranked = rank_universe(factor_df, regime, config)
    if ranked.empty:
        return []
    ranked = ranked.head(pb.candidate_count)
    candidate_tickers = ranked["ticker"].tolist()
    scores_map = dict(zip(ranked["ticker"], ranked["composite_score"].astype(float)))

    # ── do-not-buy (config) ───────────────────────────────────────────────────
    dnb = {t.upper() for t in (pb.do_not_buy or [])}
    if dnb:
        candidate_tickers = [t for t in candidate_tickers if t.upper() not in dnb]

    # ── keep only priced candidates, then apply the investability floor ───────
    priced = prices_upto[prices_upto["ticker"].isin(candidate_tickers)].sort_values("date")
    if priced.empty:
        return []
    tickers_with_prices = set(priced["ticker"].unique())
    rankable = [t for t in candidate_tickers if t in tickers_with_prices]
    latest_px = priced.groupby("ticker")["adjusted_close"].last().to_dict()
    avg_dv: dict[str, float] = {}
    has_vol = "volume" in priced.columns and "close" in priced.columns
    for t, g in priced.groupby("ticker"):
        if has_vol:
            dv = avg_dollar_volume(g["close"].tolist(), g["volume"].tolist(),
                                   window=DOLLAR_VOLUME_WINDOW)
            if dv is not None:
                avg_dv[t] = dv
    below = {
        t for t in rankable
        if below_investability_floor(
            latest_px.get(t), avg_dv.get(t),
            min_price=config.universe.min_price,
            min_avg_dollar_volume=config.universe.min_avg_dollar_volume_20d,
        )
    }
    filtered = [t for t in rankable if t not in below]
    if len(filtered) < 2:
        return []

    # ── covariance + clusters (prices <= date) ────────────────────────────────
    cov, _dropped, raw_corr = build_covariance(
        prices_upto[prices_upto["ticker"].isin(filtered)],
        window_days=pb.covariance_window_days,
        min_observations=pb.min_covariance_observations,
        shrinkage=pb.covariance_shrinkage,
    )
    if cov is None or len(cov) < 2:
        return []
    available = [t for t in filtered if t in cov.index]
    scores = pd.Series({t: scores_map[t] for t in available})
    cov = cov.loc[available, available]
    cluster_map = correlation_clusters(raw_corr, threshold=pb.cluster_correlation_threshold)

    # ── require-positive-composite (config) ───────────────────────────────────
    if pb.require_positive_composite_score:
        pos = [t for t in available if scores_map[t] >= 0]
        if len(pos) < 2:
            return []
        scores = scores[pos]
        cov = cov.loc[pos, pos]

    # ── greedy select ─────────────────────────────────────────────────────────
    selected = greedy_select(
        scores, cov,
        target=pb.max_positions,
        sector_map=cluster_map,
        max_sector_weight=pb.max_cluster_weight,
        max_tickers_per_sector=pb.max_tickers_per_cluster,
        av_sector_map=sector_map,
        max_av_sector_weight=pb.max_sector_weight,
        selection_vol_aversion=pb.selection_vol_aversion,
    )
    if not selected:
        return []

    weights = compute_weights(
        selected, cov,
        method=pb.weighting,
        max_position_weight=pb.max_position_weight,
        sector_map=cluster_map,
        max_sector_weight=pb.max_cluster_weight,
        av_sector_map=sector_map,
        max_av_sector_weight=pb.max_sector_weight,
    )

    # clip + normalize (H4 loop, verbatim from the builder)
    max_pw = pb.max_position_weight
    for _ in range(10):
        weights = {t: min(w, max_pw) for t, w in weights.items()}
        s = sum(weights.values())
        if s > 0:
            weights = {t: w / s for t, w in weights.items()}
        if not any(w > max_pw + 1e-9 for w in weights.values()):
            break

    # ── beta-target overlay (optional) ────────────────────────────────────────
    if bool(getattr(pb, "beta_target_enabled", False)) and len(weights) > 1:
        beta_map = _beta_map(prices_upto, list(weights.keys()),
                             getattr(pb, "covariance_window_days", 120))
        constraints: list[tuple[dict[str, str], float]] = []
        if pb.max_cluster_weight < 1.0:
            constraints.append((cluster_map, pb.max_cluster_weight))
        if pb.max_sector_weight < 1.0:
            constraints.append((sector_map, pb.max_sector_weight))
        for _ in range(3):
            weights, _info = solve_beta_target_weights(
                weights, beta_map, pb.beta_target, max_position_weight=max_pw)
            if constraints:
                weights = _apply_all_caps(weights, max_pw, constraints)
                s = sum(weights.values())
                if s > 0:
                    weights = {t: w / s for t, w in weights.items()}

    # ── exposure scaling: cash_reserve + optional vol_target ──────────────────
    cash_reserve = getattr(pb, "cash_reserve", 0.0)
    max_exposure = 1.0 - cash_reserve
    if bool(getattr(pb, "vol_target_enabled", False)):
        bvol = book_volatility(weights, cov)
        exposure = vol_target_exposure(
            bvol, pb.vol_target,
            min_exposure=pb.vol_target_min_exposure, max_exposure=max_exposure,
        )
    else:
        exposure = max_exposure
    if exposure < 1.0 - 1e-12:
        weights = {t: w * exposure for t, w in weights.items()}

    return [{"ticker": t, "weight": float(w)} for t, w in weights.items()]


def replay_history(
    factor_rows_by_date: dict[str, list[dict]],
    prices_df: pd.DataFrame,
    config: StrategyConfig,
    sector_map: dict[str, str],
    beta_lookback: int = 120,
) -> tuple[list[dict], list[str]]:
    """Walk rebalance dates ASC, building one synthetic portfolio_run per date.

    factor_rows_by_date: {score_date(str) -> [factor_scores row dicts]} — the
      persisted point-in-time factors for each rebalance date.
    prices_df: long [ticker, date, adjusted_close(, close, volume)] over the whole
      window; sliced to date <= D inside the loop so nothing looks ahead.

    Returns (portfolio_runs, caveats). portfolio_runs feed run_backtest.
    """
    caveats = [
        "config-replay: vetter exclusions NOT applied (run-time signal, not config)",
        "config-replay: sector labels are latest-as-of (near-static), not per-date",
    ]
    if "date" in prices_df.columns:
        prices_df = prices_df.copy()
        prices_df["date"] = pd.to_datetime(prices_df["date"])
    spy_all = prices_df[prices_df["ticker"] == "SPY"].sort_values("date")

    runs: list[dict] = []
    raw_history: list[str] = []
    prior_confirmed: str | None = None

    for d in sorted(factor_rows_by_date.keys()):
        ts = pd.Timestamp(d)
        prices_upto = prices_df[prices_df["date"] <= ts]
        spy_upto = spy_all[spy_all["date"] <= ts][["date", "adjusted_close"]]

        raw, confirmed = confirmed_regime_for_date(
            spy_upto, config, raw_history, prior_confirmed)
        raw_history.insert(0, raw)
        prior_confirmed = confirmed

        factor_df = factor_df_from_rows(factor_rows_by_date[d])
        if factor_df.empty:
            continue
        holdings = build_target_for_date(
            factor_df, prices_upto, config, confirmed, sector_map)
        if not holdings:
            continue
        runs.append({
            "run_id": f"cfgreplay-{d}",
            "portfolio_date": d,
            "regime": confirmed,
            "holdings": holdings,
        })

    return runs, caveats
