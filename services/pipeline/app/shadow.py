"""Shadow champion/challenger target construction (closed-loop item 4).

Builds a THEORETICAL daily target under a challenger config from the day's
already-persisted factor scores + the shared canonical rank/select. Pure math
here; DB orchestration lives in main.py (`_run_shadow_build`).

Deliberate scope limits (documented in architecture.md):
- Reuses the ACTIVE config's persisted factor scores — a challenger may vary
  factor WEIGHTS and builder knobs, not raw factor definitions, and it
  inherits the champion's investability-filtered pool.
- No vetter (exclusions are run-time state, not config), no falling-knife
  veto, no beta-target overlay (needs per-ticker betas the shadow doesn't
  load). Vol-target/cash-reserve de-lever IS applied (pure function of the
  covariance already built).
- Output is a paper target only: shadow_runs rows, never intents or orders.
"""
from __future__ import annotations

import pandas as pd

from stock_strategy_shared.strategy_engine.select import (
    book_volatility,
    build_covariance,
    compute_weights,
    correlation_clusters,
    greedy_select,
    vol_target_exposure,
)


def build_challenger_target(ranked: pd.DataFrame, price_df: pd.DataFrame,
                            sector_map: dict[str, str], cfg
                            ) -> tuple[dict[str, float], str | None]:
    """ranked: rank_universe output under the CHALLENGER config (full frame).
    price_df: long [ticker, date, adjusted_close] covering the covariance
    window for the candidate head. Returns ({ticker: weight}, error|None) —
    empty target + reason when construction is infeasible (thin data etc.)."""
    pb = cfg.portfolio_builder
    head = ranked.head(pb.candidate_count)
    scores_map = dict(zip(head["ticker"], head["composite_score"].astype(float)))
    dnb = {t.upper() for t in (pb.do_not_buy or [])}
    candidates = [t for t in head["ticker"].tolist() if t.upper() not in dnb]
    if len(candidates) < 2:
        return {}, "fewer than 2 candidates after do-not-buy"

    cov, _dropped, raw_corr = build_covariance(
        price_df[price_df["ticker"].isin(candidates)],
        window_days=pb.covariance_window_days,
        min_observations=pb.min_covariance_observations,
        shrinkage=pb.covariance_shrinkage)
    if cov is None or len(cov) < 2:
        return {}, "covariance unavailable (insufficient price history)"
    cluster_map = correlation_clusters(raw_corr, threshold=pb.cluster_correlation_threshold)

    available = [t for t in candidates if t in cov.index]
    if pb.require_positive_composite_score:
        available = [t for t in available if scores_map[t] >= 0]
    if len(available) < 2:
        return {}, "fewer than 2 selectable names"
    scores = pd.Series({t: scores_map[t] for t in available})
    cov = cov.loc[available, available]

    selected = greedy_select(
        scores, cov, target=pb.max_positions,
        sector_map=cluster_map, max_sector_weight=pb.max_cluster_weight,
        max_tickers_per_sector=pb.max_tickers_per_cluster,
        av_sector_map=sector_map, max_av_sector_weight=pb.max_sector_weight,
        selection_vol_aversion=pb.selection_vol_aversion)
    if not selected:
        return {}, "greedy selection returned empty"
    weights = compute_weights(
        selected, cov, method=pb.weighting,
        max_position_weight=pb.max_position_weight,
        sector_map=cluster_map, max_sector_weight=pb.max_cluster_weight,
        av_sector_map=sector_map, max_av_sector_weight=pb.max_sector_weight)

    max_pw = pb.max_position_weight
    for _ in range(10):
        weights = {t: min(w, max_pw) for t, w in weights.items()}
        s = sum(weights.values())
        if s > 0:
            weights = {t: w / s for t, w in weights.items()}
        if not any(w > max_pw + 1e-9 for w in weights.values()):
            break

    cash_reserve = getattr(pb, "cash_reserve", 0.0)
    max_exposure = 1.0 - cash_reserve
    if bool(getattr(pb, "vol_target_enabled", False)):
        bvol = book_volatility(weights, cov)
        exposure = vol_target_exposure(bvol, pb.vol_target,
                                       min_exposure=pb.vol_target_min_exposure,
                                       max_exposure=max_exposure)
    else:
        exposure = max_exposure
    if exposure < 1.0 - 1e-12:
        weights = {t: w * exposure for t, w in weights.items()}
    return {t: float(w) for t, w in weights.items()}, None
