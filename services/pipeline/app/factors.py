from __future__ import annotations

import numpy as np
import pandas as pd

from stock_strategy_shared.schemas.strategy import FactorEngineConfig


def cross_section_zscore(series: pd.Series, clip: float = 2.5) -> pd.Series:
    valid = series.dropna()
    result = pd.Series(float("nan"), index=series.index)
    if valid.empty:
        return result
    std = valid.std()
    if std == 0 or pd.isna(std):
        result.loc[valid.index] = 0.0
        return result
    result.loc[valid.index] = ((valid - valid.mean()) / std).clip(-clip, clip)
    return result


def _winsorize(s: pd.Series, lo_pct: float = 0.01, hi_pct: float = 0.99) -> pd.Series:
    """Clip to quantile bounds. Skipped for small populations (<10) to avoid over-fitting."""
    if len(s) < 10:
        return s
    lo, hi = s.quantile(lo_pct), s.quantile(hi_pct)
    return s.clip(lo, hi)


def _component_zscore(s: pd.Series) -> pd.Series:
    """Z-score without clipping — used to put factor components on equal scale before combining.

    Must be called with a pre-filtered series that contains only non-NaN values (e.g. roe[has_roe]).
    Callers that filter to different-sized valid subsets before calling (e.g. ROE on 800 tickers,
    D/E on 400 tickers) produce component z-scores relative to their own sub-population.
    This is an accepted approximation: the subsequent cross_section_zscore in compute_all_factors
    re-normalises the composite across the full universe, so the within-composite scale difference
    is absorbed at that stage. The remaining effect — tickers with only one component contributing
    a full N(0,1) while tickers with both contribute a mean of two N(0,1)s (σ≈0.71) — is minor
    relative to the ranking signal.
    """
    std = s.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def compute_momentum(
    prices: pd.DataFrame,
    short_window: int = 21,
    long_window: int = 252,
) -> pd.Series:
    # prices must contain only trading-day rows (no weekend/holiday NaN rows);
    # iloc[-long_window] and iloc[-short_window] are positional, so calendar rows would shorten the look-back.
    prices = prices.dropna(how="all")
    if len(prices) < long_window + 1:
        return pd.Series(dtype=float)

    price_long = prices.iloc[-long_window]
    price_short = prices.iloc[-short_window]

    # Guard: price_long <= 0 means corrupt/missing data (e.g. AV returned 0.0 for adjusted_close),
    # not a real price. Replace with NaN so division produces NaN rather than inf.
    valid_long = price_long.where(price_long > 0)
    momentum = (price_short / valid_long) - 1.0
    # Guard: replace any inf/-inf that slipped through with NaN
    momentum = momentum.replace([float("inf"), float("-inf")], float("nan"))
    momentum.name = "momentum"
    return momentum


def compute_low_volatility(prices: pd.DataFrame, window: int = 252) -> pd.Series:
    # Require at least one quarter of data (63 trading days → 62 log-returns).
    # Fewer rows produce an annualized vol estimate with enormous standard error
    # that would be mistaken for a confident low-volatility signal.
    if len(prices) < 63:
        return pd.Series(dtype=float)

    hist = prices.iloc[-window:] if len(prices) >= window else prices
    log_returns = np.log(hist / hist.shift(1))
    vol = log_returns.std(skipna=True) * np.sqrt(252)  # per-ticker std, ignores missing days
    score = -vol
    score.name = "low_volatility"
    return score


def compute_liquidity(prices_long: pd.DataFrame, window: int = 20, max_staleness_days: int = 7) -> pd.Series:
    recent = prices_long.copy()
    recent = recent.sort_values("date")
    last_n = recent.groupby("ticker").tail(window)
    last_n = last_n.copy()
    # Dollar volume must use unadjusted close — adjusted_close is backward-adjusted for
    # splits/dividends and understates the actual amount of money that traded (e.g. a
    # 10:1 split makes adjusted_close 10x smaller than the real transaction price).
    last_n["dollar_vol"] = last_n["close"].astype(float) * last_n["volume"].astype(float)
    avg_dv = last_n.groupby("ticker")["dollar_vol"].mean()

    # tail(window) takes the last N rows by position, not by date. A halted or
    # delisted stock with old rows in the DB would get a valid dollar-vol score
    # computed from stale data. Drop tickers whose most recent data is more than
    # max_staleness_days behind the dataset's reference date (= SPY's latest date).
    reference_date = recent["date"].max()
    latest_by_ticker = last_n.groupby("ticker")["date"].max()
    stale = latest_by_ticker < (reference_date - pd.Timedelta(days=max_staleness_days))
    avg_dv = avg_dv[~stale]

    score = np.log1p(avg_dv)
    score.name = "liquidity"
    return score


def compute_quality(fundamentals: pd.DataFrame) -> pd.Series:
    """
    Composite of ROE and inverse D/E.

    Each component is winsorized at 1st/99th percentile then individually z-scored
    before averaging. This replaces the prior min-max approach, which compressed the
    upside to ~0.5σ because profitable companies clustered in the top of [0, 1].
    Winsorize + component z-score preserves full cross-sectional spread.
    """
    fund = fundamentals.set_index("ticker")

    roe = fund["roe"].astype(float) if "roe" in fund.columns else pd.Series(dtype=float)
    dte = fund["debt_to_equity"].astype(float) if "debt_to_equity" in fund.columns else pd.Series(dtype=float)

    has_roe = roe.notna()
    has_dte = dte.notna()

    roe_z = _component_zscore(_winsorize(roe[has_roe])) if has_roe.any() else pd.Series(dtype=float)
    neg_dte_z = _component_zscore(_winsorize(-dte[has_dte])) if has_dte.any() else pd.Series(dtype=float)

    all_tickers = fund.index
    components = pd.DataFrame(index=all_tickers)
    if not roe_z.empty:
        components["roe"] = roe_z.reindex(all_tickers)
    if not neg_dte_z.empty:
        components["neg_dte"] = neg_dte_z.reindex(all_tickers)

    if components.empty:
        result = pd.Series(np.nan, index=all_tickers)
    else:
        result = components.mean(axis=1, skipna=True)

    result.name = "quality"
    return result


def compute_value(fundamentals: pd.DataFrame, pe_pb_cap: float = 50.0) -> pd.Series:
    """
    Mean of earnings yield (1/PE) and book yield (1/PB).

    PE/PB are capped at pe_pb_cap — beyond that the yield signal is economically flat.
    Yields are additionally winsorized at 1st/99th percentile before averaging.
    """
    fund = fundamentals.set_index("ticker")

    pe = fund["pe_ratio"].astype(float) if "pe_ratio" in fund.columns else pd.Series(dtype=float)
    pb = fund["pb_ratio"].astype(float) if "pb_ratio" in fund.columns else pd.Series(dtype=float)

    pe_capped = pe.clip(upper=pe_pb_cap)
    pb_capped = pb.clip(upper=pe_pb_cap)

    earnings_yield = 1.0 / pe_capped.where(pe_capped > 0)
    book_yield = 1.0 / pb_capped.where(pb_capped > 0)

    ey_valid = earnings_yield[earnings_yield.notna()]
    by_valid = book_yield[book_yield.notna()]
    ey_w = _winsorize(ey_valid) if not ey_valid.empty else ey_valid
    by_w = _winsorize(by_valid) if not by_valid.empty else by_valid

    # Component z-score each yield before averaging so earnings_yield (~0.07)
    # and book_yield (~0.67) contribute equal weight instead of book_yield
    # dominating at ~10x the raw scale.
    ey_z = _component_zscore(ey_w) if not ey_w.empty else ey_w
    by_z = _component_zscore(by_w) if not by_w.empty else by_w

    all_tickers = fund.index
    components = pd.DataFrame(index=all_tickers)
    if not ey_z.empty:
        components["earnings_yield"] = ey_z.reindex(all_tickers)
    if not by_z.empty:
        components["book_yield"] = by_z.reindex(all_tickers)

    if components.empty:
        result = pd.Series(np.nan, index=all_tickers)
    else:
        result = components.mean(axis=1, skipna=True)
    result.name = "value"
    return result


def compute_growth(fundamentals: pd.DataFrame) -> pd.Series:
    """
    Mean of revenue_growth and eps_growth, each individually winsorized
    then component-z-scored before averaging.

    Without component z-scoring, a single ticker with explosive growth (e.g.
    10x revenue) compresses the entire cross-section to near-zero z-scores
    even after winsorization, because the raw-value gap remains enormous.
    Component z-scoring at 1%/99% bounds mirrors the quality/value pattern
    and eliminates this collapse regardless of outlier magnitude.
    """
    fund = fundamentals.set_index("ticker")

    rev_g = fund["revenue_growth"].astype(float) if "revenue_growth" in fund.columns else pd.Series(dtype=float)
    eps_g = fund["eps_growth"].astype(float) if "eps_growth" in fund.columns else pd.Series(dtype=float)

    rev_g_valid = rev_g[rev_g.notna()]
    eps_g_valid = eps_g[eps_g.notna()]

    rev_g_w = _winsorize(rev_g_valid, lo_pct=0.01, hi_pct=0.99) if not rev_g_valid.empty else rev_g_valid
    eps_g_w = _winsorize(eps_g_valid, lo_pct=0.01, hi_pct=0.99) if not eps_g_valid.empty else eps_g_valid

    rev_g_z = _component_zscore(rev_g_w) if not rev_g_w.empty else rev_g_w
    eps_g_z = _component_zscore(eps_g_w) if not eps_g_w.empty else eps_g_w

    all_tickers = fund.index
    components = pd.DataFrame(index=all_tickers)
    if not rev_g_z.empty:
        components["rev_g"] = rev_g_z.reindex(all_tickers)
    if not eps_g_z.empty:
        components["eps_g"] = eps_g_z.reindex(all_tickers)

    if components.empty:
        result = pd.Series(np.nan, index=all_tickers)
    else:
        result = components.mean(axis=1, skipna=True)

    result.name = "growth"
    return result


def compute_all_factors(
    prices_long: pd.DataFrame,
    fundamentals: pd.DataFrame,
    cfg: FactorEngineConfig | None = None,
) -> pd.DataFrame:
    if cfg is None:
        cfg = FactorEngineConfig()

    prices_long = prices_long.copy()
    prices_long["date"] = pd.to_datetime(prices_long["date"])
    prices_long = prices_long.sort_values(["ticker", "date"])

    prices_long["adjusted_close"] = prices_long["adjusted_close"].astype(float)
    # Use pivot() not pivot_table(): pivot() raises ValueError on duplicate (date, ticker) pairs,
    # making data integrity issues visible. pivot_table() silently averages duplicates.
    pivot = prices_long.pivot(index="date", columns="ticker", values="adjusted_close")
    pivot = pivot.sort_index()

    momentum_raw = compute_momentum(pivot, short_window=cfg.momentum_short_window, long_window=cfg.momentum_long_window)
    low_vol_raw = compute_low_volatility(pivot, window=cfg.volatility_window)
    liquidity_raw = compute_liquidity(prices_long, window=cfg.liquidity_window)
    quality_raw = compute_quality(fundamentals)
    value_raw = compute_value(fundamentals, pe_pb_cap=cfg.pe_pb_cap)
    growth_raw = compute_growth(fundamentals)

    all_tickers = prices_long["ticker"].unique().tolist()
    result = pd.DataFrame(index=all_tickers)
    result.index.name = "ticker"

    def _align(raw: pd.Series) -> pd.Series:
        return raw.reindex(result.index)

    # Winsorize raw momentum and low_volatility using 0.1%/99.9% tails before z-scoring.
    # The 1%/99% band was a bug: with a 2000-ticker universe it clips the top 20 tickers
    # to the same value, giving them all identical z-scores and destroying rank
    # differentiation among top performers. The 0.1%/99.9% band clips at most 2 tickers
    # per 1000 — enough to suppress genuine extreme outliers (spinoff repricing, data
    # errors) without collapsing a cluster of legitimate top-momentum stocks.
    momentum_w = _winsorize(momentum_raw.dropna(), lo_pct=0.001, hi_pct=0.999).reindex(momentum_raw.index) if not momentum_raw.empty else momentum_raw
    low_vol_w  = _winsorize(low_vol_raw.dropna(), lo_pct=0.001, hi_pct=0.999).reindex(low_vol_raw.index)   if not low_vol_raw.empty else low_vol_raw

    # No additional clip — the 0.1%/99.9% winsorize handles extremes without
    # flattening the top tier to a single score.
    result["momentum"] = cross_section_zscore(_align(momentum_w), clip=float("inf"))
    result["low_volatility"] = cross_section_zscore(_align(low_vol_w), clip=float("inf"))
    result["liquidity"] = cross_section_zscore(_align(liquidity_raw), clip=cfg.zscore_clip)
    result["quality"] = cross_section_zscore(_align(quality_raw), clip=cfg.zscore_clip)
    result["value"] = cross_section_zscore(_align(value_raw), clip=cfg.zscore_clip)
    result["growth"] = cross_section_zscore(_align(growth_raw), clip=cfg.zscore_clip)

    result = result.reset_index()
    return result
