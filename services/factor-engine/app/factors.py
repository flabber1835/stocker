import numpy as np
import pandas as pd


def cross_section_zscore(series: pd.Series) -> pd.Series:
    mean = series.mean()
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return ((series - mean) / std).clip(-3, 3)


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
    log_returns = np.log(window / window.shift(1)).dropna()
    vol = log_returns.std() * np.sqrt(252)
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
    fund = fundamentals.set_index("ticker")

    roe = fund["roe"].astype(float) if "roe" in fund.columns else pd.Series(dtype=float)
    dte = fund["debt_to_equity"].astype(float) if "debt_to_equity" in fund.columns else pd.Series(dtype=float)

    def _norm(s: pd.Series) -> pd.Series:
        mn, mx = s.min(), s.max()
        if mx == mn:
            return pd.Series(0.0, index=s.index)
        return (s - mn) / (mx - mn)

    has_roe = roe.notna()
    has_dte = dte.notna()

    norm_roe = _norm(roe[has_roe]) if has_roe.any() else pd.Series(dtype=float)
    norm_neg_dte = _norm(-dte[has_dte]) if has_dte.any() else pd.Series(dtype=float)

    all_tickers = fund.index
    result = pd.Series(index=all_tickers, dtype=float)

    for ticker in all_tickers:
        parts = []
        if ticker in norm_roe.index and pd.notna(norm_roe.get(ticker)):
            parts.append(norm_roe[ticker])
        if ticker in norm_neg_dte.index and pd.notna(norm_neg_dte.get(ticker)):
            parts.append(norm_neg_dte[ticker])
        result[ticker] = np.mean(parts) if parts else np.nan

    result.name = "quality"
    return result


def compute_value(fundamentals: pd.DataFrame) -> pd.Series:
    fund = fundamentals.set_index("ticker")

    pe = fund["pe_ratio"].astype(float) if "pe_ratio" in fund.columns else pd.Series(dtype=float)
    pb = fund["pb_ratio"].astype(float) if "pb_ratio" in fund.columns else pd.Series(dtype=float)

    pe_capped = pe.clip(upper=200)
    pb_capped = pb.clip(upper=200)

    earnings_yield = 1.0 / pe_capped.where(pe_capped > 0)
    book_yield = 1.0 / pb_capped.where(pb_capped > 0)

    all_tickers = fund.index
    result = pd.Series(index=all_tickers, dtype=float)

    for ticker in all_tickers:
        parts = []
        ey = earnings_yield.get(ticker) if ticker in earnings_yield.index else np.nan
        by = book_yield.get(ticker) if ticker in book_yield.index else np.nan
        if pd.notna(ey):
            parts.append(ey)
        if pd.notna(by):
            parts.append(by)
        result[ticker] = np.mean(parts) if parts else np.nan

    result.name = "value"
    return result


def compute_growth(fundamentals: pd.DataFrame) -> pd.Series:
    fund = fundamentals.set_index("ticker")

    rev_g = fund["revenue_growth"].astype(float) if "revenue_growth" in fund.columns else pd.Series(dtype=float)
    eps_g = fund["eps_growth"].astype(float) if "eps_growth" in fund.columns else pd.Series(dtype=float)

    all_tickers = fund.index
    result = pd.Series(index=all_tickers, dtype=float)

    for ticker in all_tickers:
        parts = []
        rg = rev_g.get(ticker) if ticker in rev_g.index else np.nan
        eg = eps_g.get(ticker) if ticker in eps_g.index else np.nan
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
