from __future__ import annotations

import numpy as np
import pandas as pd

from stock_strategy_shared.schemas.strategy import FactorEngineConfig


def cross_section_percentile(series: pd.Series) -> pd.Series:
    """Cross-sectional percentile rank in (0, 1].
    Highest value → 1.0, lowest → 1/N.
    Ties receive average rank. NaN excluded and remain NaN.
    Fewer than 2 valid entries returns all-NaN (can't rank against yourself).
    """
    result = pd.Series(np.nan, index=series.index, dtype=float)
    valid = series.dropna()
    if len(valid) < 2:
        return result
    result.loc[valid.index] = valid.rank(method="average", pct=True)
    return result


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
    This is an accepted approximation: the subsequent cross_section_percentile in compute_all_factors
    re-normalises the composite across the full universe via percentile ranking, so the within-composite
    scale difference is absorbed at that stage. The remaining effect — tickers with only one component
    contributing a full N(0,1) while tickers with both contribute a mean of two N(0,1)s (σ≈0.71) — is
    minor relative to the ranking signal.
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
    # Jegadeesh-Titman 12-1 momentum: skip the most recent month (T-1 to T-21) to avoid
    # short-term reversal contamination. price_long = T-252, price_short = T-21.
    # iloc is 0-indexed from the end, so iloc[-(N+1)] gives the Nth row from the end.
    if len(prices) < long_window + 2:
        return pd.Series(dtype=float)

    price_long = prices.iloc[-(long_window + 1)]
    price_short = prices.iloc[-(short_window + 1)]

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
    log_returns = log_returns.replace([float("inf"), float("-inf")], float("nan"))
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

    Each component is winsorized then ranked via cross_section_percentile so both
    land on [0, 1] relative to the full universe. Using sub-population z-scores
    instead inflated scores for tickers with only one component: a ticker with
    ROE data but no D/E data would receive a full unbounded z-score as its quality,
    while a ticker with both components received a dampened mean of two z-scores.
    With percentile ranking the scale is identical whether a ticker has one or two
    components, so sparse-fundamental stocks no longer rank artificially high.
    """
    fund = fundamentals.set_index("ticker")

    roe = fund["roe"].astype(float) if "roe" in fund.columns else pd.Series(dtype=float)
    dte = fund["debt_to_equity"].astype(float) if "debt_to_equity" in fund.columns else pd.Series(dtype=float)

    has_roe = roe.notna()
    has_dte = dte.notna()

    all_tickers = fund.index
    components = pd.DataFrame(index=all_tickers)
    if has_roe.any():
        components["roe"] = cross_section_percentile(_winsorize(roe[has_roe]).reindex(all_tickers))
    if has_dte.any():
        components["neg_dte"] = cross_section_percentile(_winsorize(-dte[has_dte]).reindex(all_tickers))

    if components.empty:
        result = pd.Series(np.nan, index=all_tickers)
    else:
        # Fill missing components with 0.5 (neutral percentile) for tickers
        # that have at least one valid component.  Without this, a ticker with
        # only one component gets mean = that component's score; a ticker with
        # two components gets the average of both — so the one-component ticker
        # can outscore the two-component ticker just by having the best single
        # metric, which is unfair.  Neutral fill says "we don't know this metric,
        # assume average" rather than silently ignoring the missing dimension.
        has_any = components.notna().any(axis=1)
        filled = components.where(components.notna(), other=0.5)
        result = filled.mean(axis=1)
        result[~has_any] = np.nan

    result.name = "quality"
    return result


def compute_value(fundamentals: pd.DataFrame, pe_pb_cap: float = 50.0) -> pd.Series:
    """
    Mean of earnings yield (1/PE) and book yield (1/PB).

    PE/PB are capped at pe_pb_cap — beyond that the yield signal is economically flat.
    Components are winsorized then ranked via cross_section_percentile so both yields
    land on [0, 1] despite their different raw scales (earnings yield ~0.07,
    book yield ~0.67). This replaces component z-scoring which had the same sparse-data
    inflation problem as quality.
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

    all_tickers = fund.index
    components = pd.DataFrame(index=all_tickers)
    if not ey_w.empty:
        components["earnings_yield"] = cross_section_percentile(ey_w.reindex(all_tickers))
    if not by_w.empty:
        components["book_yield"] = cross_section_percentile(by_w.reindex(all_tickers))

    if components.empty:
        result = pd.Series(np.nan, index=all_tickers)
    else:
        # Same neutral-fill logic as compute_quality: missing components
        # become 0.5 (percentile midpoint) so a PE-only ticker cannot
        # outscore a ticker with both good PE and good PB.
        has_any = components.notna().any(axis=1)
        filled = components.where(components.notna(), other=0.5)
        result = filled.mean(axis=1)
        result[~has_any] = np.nan
    result.name = "value"
    return result


def compute_growth(fundamentals: pd.DataFrame) -> pd.Series:
    """
    Mean of revenue_growth and eps_growth percentile ranks.

    Each component is winsorized then ranked via cross_section_percentile so
    both land on [0, 1] relative to the full universe. Missing components are
    filled with 0.5 (neutral percentile) so a ticker with only one growth
    metric cannot outscore a ticker that is good on both — same pattern as
    compute_quality and compute_value.
    """
    fund = fundamentals.set_index("ticker")

    rev_g = fund["revenue_growth"].astype(float) if "revenue_growth" in fund.columns else pd.Series(dtype=float)
    eps_g = fund["eps_growth"].astype(float) if "eps_growth" in fund.columns else pd.Series(dtype=float)

    rev_g_valid = rev_g[rev_g.notna()]
    eps_g_valid = eps_g[eps_g.notna()]

    rev_g_w = _winsorize(rev_g_valid, lo_pct=0.01, hi_pct=0.99) if not rev_g_valid.empty else rev_g_valid
    eps_g_w = _winsorize(eps_g_valid, lo_pct=0.01, hi_pct=0.99) if not eps_g_valid.empty else eps_g_valid

    all_tickers = fund.index
    components = pd.DataFrame(index=all_tickers)
    if not rev_g_w.empty:
        components["rev_g"] = cross_section_percentile(rev_g_w.reindex(all_tickers))
    if not eps_g_w.empty:
        components["eps_g"] = cross_section_percentile(eps_g_w.reindex(all_tickers))

    if components.empty:
        result = pd.Series(np.nan, index=all_tickers)
    else:
        has_any = components.notna().any(axis=1)
        filled = components.where(components.notna(), other=0.5)
        result = filled.mean(axis=1)
        result[~has_any] = np.nan

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

    # Percentile-rank each factor cross-sectionally to [0, 1].
    # Winsorization before percentile ranking is unnecessary — percentile ranking is
    # already outlier-robust by construction (a z=6 outlier gets percentile=1.0,
    # same ceiling as any other top-ranked ticker).
    result["momentum"]      = cross_section_percentile(_align(momentum_raw))
    result["low_volatility"]= cross_section_percentile(_align(low_vol_raw))
    result["liquidity"]     = cross_section_percentile(_align(liquidity_raw))
    result["quality"]       = cross_section_percentile(_align(quality_raw))
    result["value"]         = cross_section_percentile(_align(value_raw))
    result["growth"]        = cross_section_percentile(_align(growth_raw))

    result = result.reset_index()
    return result
