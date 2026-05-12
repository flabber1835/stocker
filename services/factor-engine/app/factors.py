import numpy as np
import pandas as pd


def cross_section_zscore(series: pd.Series) -> pd.Series:
    valid = series.dropna()
    result = pd.Series(float("nan"), index=series.index)
    if valid.empty:
        return result
    std = valid.std()
    if std == 0 or pd.isna(std):
        result.loc[valid.index] = 0.0
        return result
    result.loc[valid.index] = ((valid - valid.mean()) / std).clip(-2.5, 2.5)
    return result


def _winsorize(s: pd.Series, lo_pct: float = 0.01, hi_pct: float = 0.99) -> pd.Series:
    """Clip to quantile bounds. Skipped for small populations (<10) to avoid over-fitting."""
    if len(s) < 10:
        return s
    lo, hi = s.quantile(lo_pct), s.quantile(hi_pct)
    return s.clip(lo, hi)


def _component_zscore(s: pd.Series) -> pd.Series:
    """Z-score without clipping — used to put factor components on equal scale before combining."""
    std = s.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def compute_momentum(prices: pd.DataFrame) -> pd.Series:
    if len(prices) < 253:
        return pd.Series(dtype=float)

    price_252 = prices.iloc[-252]
    price_21 = prices.iloc[-21]

    momentum = (price_21 / price_252) - 1.0
    momentum.name = "momentum"
    return momentum


def compute_low_volatility(prices: pd.DataFrame) -> pd.Series:
    if len(prices) < 2:
        return pd.Series(dtype=float)

    window = prices.iloc[-252:] if len(prices) >= 252 else prices
    log_returns = np.log(window / window.shift(1))
    vol = log_returns.std(skipna=True) * np.sqrt(252)  # per-ticker std, ignores missing days
    score = -vol
    score.name = "low_volatility"
    return score


def compute_liquidity(prices_long: pd.DataFrame) -> pd.Series:
    recent = prices_long.copy()
    recent = recent.sort_values("date")
    last_20 = recent.groupby("ticker").tail(20)
    last_20 = last_20.copy()
    last_20["dollar_vol"] = last_20["close"].astype(float) * last_20["volume"].astype(float)
    avg_dv = last_20.groupby("ticker")["dollar_vol"].mean()
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
    result = pd.Series(index=all_tickers, dtype=float)

    for ticker in all_tickers:
        parts = []
        if ticker in roe_z.index and pd.notna(roe_z.get(ticker)):
            parts.append(roe_z[ticker])
        if ticker in neg_dte_z.index and pd.notna(neg_dte_z.get(ticker)):
            parts.append(neg_dte_z[ticker])
        result[ticker] = np.mean(parts) if parts else np.nan

    result.name = "quality"
    return result


def compute_value(fundamentals: pd.DataFrame) -> pd.Series:
    """
    Mean of earnings yield (1/PE) and book yield (1/PB).

    PE/PB are capped at 50x — beyond that the yield signal is economically flat.
    The prior 200x cap left headroom for outliers to distort the cross-section
    (88 tickers hit extreme z-scores in the 17500196 run). Yields are additionally
    winsorized at 1st/99th percentile before averaging.
    """
    fund = fundamentals.set_index("ticker")

    pe = fund["pe_ratio"].astype(float) if "pe_ratio" in fund.columns else pd.Series(dtype=float)
    pb = fund["pb_ratio"].astype(float) if "pb_ratio" in fund.columns else pd.Series(dtype=float)

    pe_capped = pe.clip(upper=50)
    pb_capped = pb.clip(upper=50)

    earnings_yield = 1.0 / pe_capped.where(pe_capped > 0)
    book_yield = 1.0 / pb_capped.where(pb_capped > 0)

    ey_valid = earnings_yield[earnings_yield.notna()]
    by_valid = book_yield[book_yield.notna()]
    ey_w = _winsorize(ey_valid) if not ey_valid.empty else ey_valid
    by_w = _winsorize(by_valid) if not by_valid.empty else by_valid

    earnings_yield_final = earnings_yield.copy()
    earnings_yield_final.loc[ey_w.index] = ey_w
    book_yield_final = book_yield.copy()
    book_yield_final.loc[by_w.index] = by_w

    all_tickers = fund.index
    result = pd.Series(index=all_tickers, dtype=float)

    for ticker in all_tickers:
        parts = []
        ey = earnings_yield_final.get(ticker) if ticker in earnings_yield_final.index else np.nan
        by = book_yield_final.get(ticker) if ticker in book_yield_final.index else np.nan
        if pd.notna(ey):
            parts.append(ey)
        if pd.notna(by):
            parts.append(by)
        result[ticker] = np.mean(parts) if parts else np.nan

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
    result = pd.Series(index=all_tickers, dtype=float)

    for ticker in all_tickers:
        parts = []
        rg = rev_g_z.get(ticker) if ticker in rev_g_z.index else np.nan
        eg = eps_g_z.get(ticker) if ticker in eps_g_z.index else np.nan
        if pd.notna(rg):
            parts.append(rg)
        if pd.notna(eg):
            parts.append(eg)
        result[ticker] = np.mean(parts) if parts else np.nan

    result.name = "growth"
    return result


def compute_all_factors(
    prices_long: pd.DataFrame,
    fundamentals: pd.DataFrame,
) -> pd.DataFrame:
    prices_long = prices_long.copy()
    prices_long["date"] = pd.to_datetime(prices_long["date"])
    prices_long = prices_long.sort_values(["ticker", "date"])

    prices_long["adjusted_close"] = prices_long["adjusted_close"].astype(float)
    pivot = prices_long.pivot_table(index="date", columns="ticker", values="adjusted_close")
    pivot = pivot.sort_index()

    momentum_raw = compute_momentum(pivot)
    low_vol_raw = compute_low_volatility(pivot)
    liquidity_raw = compute_liquidity(prices_long)
    quality_raw = compute_quality(fundamentals)
    value_raw = compute_value(fundamentals)
    growth_raw = compute_growth(fundamentals)

    all_tickers = prices_long["ticker"].unique().tolist()
    result = pd.DataFrame(index=all_tickers)
    result.index.name = "ticker"

    def _align(raw: pd.Series) -> pd.Series:
        return raw.reindex(result.index)

    result["momentum"] = cross_section_zscore(_align(momentum_raw))
    result["low_volatility"] = cross_section_zscore(_align(low_vol_raw))
    result["liquidity"] = cross_section_zscore(_align(liquidity_raw))
    result["quality"] = cross_section_zscore(_align(quality_raw))
    result["value"] = cross_section_zscore(_align(value_raw))
    result["growth"] = cross_section_zscore(_align(growth_raw))

    result = result.reset_index()
    return result
