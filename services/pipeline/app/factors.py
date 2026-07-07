from __future__ import annotations

from datetime import date as _date

import numpy as np
import pandas as pd

from stock_strategy_shared.schemas.strategy import FactorEngineConfig


def compute_earnings_surprise(
    earnings: pd.DataFrame,
    as_of: _date,
    drift_window_days: int = 90,
    min_quarters_for_sue: int = 6,
) -> pd.Series:
    """Per-ticker RAW earnings-surprise signal (SUE) as of `as_of`, point-in-time.

    This is the "buy winners / sell losers" signal: it captures Post-Earnings-
    Announcement Drift (PEAD) — names that BEAT consensus keep drifting up, names
    that MISS drift down, for ~1-3 months after the report. It is partially
    orthogonal to 12-1 price momentum (which skips the most recent ~21 days and so
    misses a fresh beat).

    `earnings` columns: ticker, reported_date (date), reported_eps, estimated_eps.

    Construction (per ticker):
      - POINT-IN-TIME: only quarters with reported_date <= as_of are visible (no
        look-ahead — critical for backtest integrity).
      - DRIFT WINDOW: the signal is used only if the latest visible report is within
        `drift_window_days` of as_of; older than that the drift has played out →
        NaN (neutral). This is what makes it a *leadership* signal, not a stale one.
      - SUE = latest unexpected EPS / stdev of the ticker's unexpected-EPS history,
        where unexpected = reported_eps - estimated_eps. Standardizing by the
        ticker's own surprise volatility (Bernard-Thomas / Foster-Olsen-Shevlin)
        stops a chronically-noisy reporter from dominating. Requires
        `min_quarters_for_sue` non-null quarters; otherwise falls back to a
        normalized surprise (unexpected / |estimated|), so newly-covered names
        still get a (less precise) signal instead of NaN.

    Returns a raw float Series indexed by ticker (NaN where no usable, in-window
    surprise). compute_all_factors percentile-ranks it cross-sectionally, so a
    bigger positive SUE → higher percentile → ranked as a winner.
    """
    if earnings is None or earnings.empty:
        return pd.Series(dtype=float, name="earnings_surprise")

    df = earnings.copy()
    df["reported_date"] = pd.to_datetime(df["reported_date"]).dt.date
    as_of = pd.to_datetime(as_of).date()
    cutoff = as_of - pd.Timedelta(days=drift_window_days).to_pytimedelta()
    df = df[df["reported_date"] <= as_of]                     # POINT-IN-TIME
    for col in ("reported_eps", "estimated_eps"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values(["ticker", "reported_date"])

    out: dict[str, float] = {}
    for ticker, g in df.groupby("ticker", sort=False):
        latest = g.iloc[-1]
        # DRIFT WINDOW: a report older than the window has already drifted → neutral.
        if latest["reported_date"] < cutoff:
            out[ticker] = float("nan")
            continue
        unexpected = g["reported_eps"] - g["estimated_eps"]
        unexpected = unexpected.dropna()
        if unexpected.empty:
            out[ticker] = float("nan")
            continue
        u_latest = float(unexpected.iloc[-1])
        if len(unexpected) >= min_quarters_for_sue:
            sigma = float(unexpected.std(ddof=1))
            out[ticker] = (u_latest / sigma) if sigma > 1e-12 else float("nan")
        else:
            est = latest["estimated_eps"]
            denom = abs(float(est)) if pd.notna(est) and abs(float(est)) > 1e-6 else float("nan")
            out[ticker] = (u_latest / denom) if denom == denom else float("nan")

    return pd.Series(out, name="earnings_surprise", dtype=float)


def drop_fundamentalless(
    prices_long: pd.DataFrame,
    fundamental_tickers,
    require_fundamentals: bool,
) -> tuple[pd.DataFrame, int]:
    """Restrict the rankable price universe to tickers that filed fundamentals.

    ETFs and closed-end funds file no financials, so "has a fundamentals row" is a
    clean proxy for "is an operating company". When ``require_fundamentals`` is True
    this drops index / leveraged ETFs (SOXX, SNXX, QQQ, IWM, …) from the universe
    BEFORE factor computation, so they cannot top a price/volume-only ranking and so
    their extreme vol / near-high values don't distort the cross-sectional percentiles
    for real stocks. Pre-profit STOCKS still have a fundamentals row (market_cap /
    revenue, just no earnings), so genuine story names (e.g. ASTS) survive.

    No-op when the flag is False or the universe is empty. Returns
    ``(filtered_prices, dropped_ticker_count)``.
    """
    if not require_fundamentals or prices_long.empty:
        return prices_long, 0
    keep = set(fundamental_tickers)
    before = prices_long["ticker"].nunique()
    out = prices_long[prices_long["ticker"].isin(keep)].reset_index(drop=True)
    return out, before - out["ticker"].nunique()


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


def neutralized_percentile(
    series: pd.Series,
    sector_map: dict[str, str] | None,
    min_group_size: int = 10,
) -> pd.Series:
    """Industry-neutral cross-sectional percentile: rank each ticker WITHIN its
    own sector instead of against the whole universe.

    This removes structural cross-sector level differences (e.g. banks always
    look "cheap" vs the market) so the factor measures "best within its sector"
    rather than "in a structurally cheap sector" (Asness-Porter-Stevens 2000).
    Used for value/quality only — momentum is partly industry momentum
    (Moskowitz-Grinblatt) so it is never neutralized (enforced by the
    FactorEngineConfig validator, not here).

    `sector_map` maps ticker -> sector label (the AV `Sector` string). A ticker
    falls back to UNIVERSE-WIDE ranking (so coverage never shrinks) when:
      - sector_map is None (feature effectively off), or
      - its sector is NULL/unknown, or
      - its sector has fewer than `min_group_size` tickers with a VALID
        (non-NaN) value — too few to rank against meaningfully.

    Each within-sector group and the fallback pool are ranked with the same
    `cross_section_percentile`, so every output is on the identical [0, 1] scale
    and the downstream weighted sum treats them uniformly.
    """
    if sector_map is None:
        return cross_section_percentile(series)

    result = pd.Series(np.nan, index=series.index, dtype=float)

    # Sector per ticker (only tickers with a non-null value count toward group size).
    sectors = pd.Series({t: sector_map.get(t) for t in series.index})
    valid_sectors = sectors[series.notna() & sectors.notna()]
    group_sizes = valid_sectors.value_counts()
    big_sectors = set(group_sizes[group_sizes >= min_group_size].index)

    neutralizable = sectors.isin(big_sectors)  # NULL sector -> False

    for sec in big_sectors:
        members = sectors.index[sectors == sec]
        result.loc[members] = cross_section_percentile(series.loc[members])

    # Fallback tickers (NULL sector or sector too thin) -> universe-wide rank.
    fallback_idx = series.index[~neutralizable]
    if len(fallback_idx) > 0:
        global_pct = cross_section_percentile(series)
        result.loc[fallback_idx] = global_pct.loc[fallback_idx]

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
    method: str = "raw",
    blend_long_windows: list[int] | None = None,
) -> pd.Series:
    """Momentum factor signal. Single-horizon by default; when `blend_long_windows`
    has >1 entry, compute the chosen `method` at each long horizon (all sharing the
    same `short_window` skip — short-term-reversal protection is preserved), rank
    each cross-sectionally, and average the ranks. A faster horizon (e.g. 126 = 6-1)
    blended with 12-1 makes the factor react sooner to emerging trends without
    chasing the last month. Falls back to single-horizon when blend is None/one."""
    windows = blend_long_windows if blend_long_windows else [long_window]
    windows = [w for w in windows if w]
    if len(windows) <= 1:
        return _momentum_single(prices, short_window, windows[0] if windows else long_window, method)
    ranks = []
    for lw in windows:
        sig = _momentum_single(prices, short_window, lw, method)
        if sig.empty:
            continue
        ranks.append(cross_section_percentile(sig))
    if not ranks:
        return pd.Series(dtype=float)
    blended = pd.concat(ranks, axis=1).mean(axis=1)  # mean of available horizon ranks (skipna)
    blended.name = "momentum"
    return blended


def _momentum_single(
    prices: pd.DataFrame,
    short_window: int = 21,
    long_window: int = 252,
    method: str = "raw",
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

    if method == "raw":
        return momentum

    # ── Enhanced momentum: residual and/or risk-adjusted ─────────────────────
    # Operate on daily returns over the SAME 12-1 formation window (T-long .. T-short,
    # i.e. skipping the last month). Memory-light: the formation slice is ~(long-short)
    # rows × N tickers (a few MB at universe scale), built once and freed on return.
    form = prices.iloc[-(long_window + 1):-short_window]      # prices spanning the window
    rets = form.pct_change().iloc[1:]                          # daily returns within it
    rets = rets.replace([float("inf"), float("-inf")], float("nan"))
    if len(rets) < 2:
        return momentum  # not enough history → fall back to raw

    # Formation-period idiosyncratic volatility (per ticker), used by the risk-adjust legs.
    vol = rets.std(axis=0, ddof=1)
    vol = vol.where(vol > 0)  # 0 vol → NaN (avoid divide-by-zero)

    signal = momentum
    if method in ("residual", "residual_riskadj", "residual_tstat"):
        # Market proxy = equal-weight cross-sectional mean daily return (no SPY plumbing).
        mkt = rets.mean(axis=1)
        m = mkt.to_numpy()
        m_dem = m - m.mean()
        var_m = float((m_dem * m_dem).mean())
        if var_m > 0:
            R = rets.to_numpy()                                # (W, N)
            R_dem = R - np.nanmean(R, axis=0)
            beta = np.nansum(R_dem * m_dem[:, None], axis=0) / (var_m * R.shape[0])
            resid = R - beta[None, :] * m[:, None]             # idiosyncratic daily returns
            resid_cum = np.nansum(resid, axis=0)               # cumulative residual return
            if method == "residual_tstat":
                # Gutierrez-Prinsky (2007) / Blitz-Huij-Martens (2011): standardize the
                # cumulative residual by the STD OF THE RESIDUALS over the window — an
                # information-ratio / t-stat-like measure that rewards CONSISTENT
                # idiosyncratic outperformance rather than a few lucky jumps. (This is
                # the canonical residual-momentum construction; residual_riskadj instead
                # divides by TOTAL-return vol, which is close but not the residual std.)
                # Cross-sectional rank is invariant to the constant sqrt(n), so
                # cum/std_resid ranks identically to the per-day-mean t-stat.
                n_obs = np.sum(~np.isnan(resid), axis=0)
                with np.errstate(invalid="ignore", divide="ignore"):
                    resid_std = np.nanstd(resid, axis=0, ddof=1)
                    tstat = np.where(
                        (resid_std > 0) & (n_obs >= 2),
                        resid_cum / resid_std,
                        np.nan,
                    )
                signal = pd.Series(tstat, index=rets.columns, name="momentum")
            else:
                signal = pd.Series(resid_cum, index=rets.columns, name="momentum")
            # A ticker with no usable returns this window → NaN, not 0.
            signal = signal.where(rets.notna().any(axis=0))
        # var_m == 0 (degenerate flat market) → keep raw momentum as `signal`.

    # residual_tstat is ALREADY standardized (by residual std) above — it must NOT also
    # pass through the total-vol divisor here (that would double-scale it).
    if method in ("risk_adjusted", "residual_riskadj"):
        signal = (signal / vol).replace([float("inf"), float("-inf")], float("nan"))

    signal.name = "momentum"
    return signal


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


def compute_quality(
    fundamentals: pd.DataFrame,
    use_gross_profitability: bool = False,
) -> pd.Series:
    """
    Composite of a PROFITABILITY leg and an inverse-D/E (safety) leg.

    Profitability leg:
      - default (use_gross_profitability=False): ROE — the legacy proxy.
      - use_gross_profitability=True: gross-profits-to-assets
        (gross_profit / total_assets, Novy-Marx 2013), the robust quality signal.
        ROE is the literature's weakest quality proxy and mechanically rewards
        leverage (fighting the inverse-D/E safety leg). Falls back to ROE when
        gross_profit/total_assets columns are absent or all-NaN (pre-backfill or
        a ticker whose BALANCE_SHEET fetch failed), so the factor never breaks.

    Each component is winsorized then ranked via cross_section_percentile so both
    land on [0, 1] relative to the full universe. Using sub-population z-scores
    instead inflated scores for tickers with only one component: a ticker with
    profitability data but no D/E data would receive a full unbounded z-score as
    its quality, while a ticker with both components received a dampened mean of
    two z-scores. With percentile ranking the scale is identical whether a ticker
    has one or two components, so sparse-fundamental stocks no longer rank
    artificially high.
    """
    fund = fundamentals.set_index("ticker")
    all_tickers = fund.index

    # Profitability leg: gross-profits-to-assets when enabled, with a PER-TICKER
    # ROE fallback. Each candidate series is winsorized + percentile-ranked over
    # its OWN population (both land on [0,1]), then the ROE percentile fills the
    # tickers whose GPA inputs are missing — mixing raw GPA and raw ROE in one
    # percentile would corrupt the ordering (different scales).
    # ROOT CAUSE this fixes (the PBR incident): the old fallback was
    # POPULATION-level (`if prof.dropna().empty`) — one ticker whose total_assets
    # a vendor blip nulled got NaN profitability even though its ROE was present
    # in the same row, so quality went null, the required_factors gate ejected
    # BOTH Petrobras listings, and the held one started an orphan-exit countdown.
    prof_pct = pd.Series(np.nan, index=all_tickers)
    if (
        use_gross_profitability
        and "gross_profit" in fund.columns
        and "total_assets" in fund.columns
    ):
        gp = fund["gross_profit"].astype(float)
        ta = fund["total_assets"].astype(float)
        gpa = (gp / ta.where(ta > 0)).replace(  # assets <= 0 is corrupt data -> NaN
            [float("inf"), float("-inf")], float("nan")
        )
        if gpa.notna().any():
            prof_pct = cross_section_percentile(_winsorize(gpa[gpa.notna()]).reindex(all_tickers))
    if "roe" in fund.columns:
        roe = fund["roe"].astype(float)
        if roe.notna().any() and prof_pct.isna().any():
            roe_pct = cross_section_percentile(_winsorize(roe[roe.notna()]).reindex(all_tickers))
            prof_pct = prof_pct.fillna(roe_pct)

    dte = fund["debt_to_equity"].astype(float) if "debt_to_equity" in fund.columns else pd.Series(dtype=float)
    has_dte = dte.notna()

    components = pd.DataFrame(index=all_tickers)
    if prof_pct.notna().any():
        components["profitability"] = prof_pct
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


def compute_issuance(fundamentals: pd.DataFrame) -> pd.Series:
    """Net-share-issuance factor (raw signal, higher = better).

    net_issuance = shares_outstanding / shares_outstanding_prior - 1, computed
    YoY from balance-sheet annual common shares. The factor is the NEGATIVE of
    net issuance, so net repurchasers (shares shrinking → negative issuance) score
    high and dilutive issuers score low — the net-share-issuance anomaly. Returns
    NaN where either share count is missing or non-positive (factor is optional;
    a NaN just means no issuance tilt for that ticker). The downstream
    cross_section_percentile turns this into a [0,1] rank.
    """
    fund = fundamentals.set_index("ticker")
    if "shares_outstanding" not in fund.columns or "shares_outstanding_prior" not in fund.columns:
        return pd.Series(np.nan, index=fund.index, name="issuance")
    cur = fund["shares_outstanding"].astype(float)
    prior = fund["shares_outstanding_prior"].astype(float)
    valid = (cur > 0) & (prior > 0)
    net_issuance = (cur / prior.where(prior > 0)) - 1.0
    factor = (-net_issuance).where(valid)
    factor = factor.replace([float("inf"), float("-inf")], float("nan"))
    factor.name = "issuance"
    return factor


def compute_small_cap(fundamentals: pd.DataFrame) -> pd.Series:
    """Small-cap preference (raw signal, higher = SMALLER). Returns -market_cap so the
    cross-sectional percentile scores the smallest companies highest — the cohort
    speculative moonshots come from. NaN where market_cap is missing/non-positive.
    Optional factor (default weight 0). Pure / dependency-free."""
    fund = fundamentals.set_index("ticker")
    if "market_cap" not in fund.columns:
        return pd.Series(dtype=float, name="small_cap")
    mc = fund["market_cap"].astype(float)
    score = (-mc).where(mc > 0)
    score.name = "small_cap"
    return score


def compute_volume_surge(prices_long: pd.DataFrame, short_window: int = 5,
                         long_window: int = 60, max_staleness_days: int = 7) -> pd.Series:
    """Unusual-volume / accumulation signal (raw, higher = bigger recent surge):
    mean(volume, last short_window) / mean(volume, last long_window). >1 means recent
    volume is running hot vs the ticker's own baseline — a tell for story/breakout
    names. NaN with < long_window rows or zero baseline. Optional factor.

    Fully vectorized (no per-group Python apply, only 3 columns copied) — the factor
    step runs over the whole ~2k-ticker universe under a tight memory cap, so a
    groupby.apply here would be both slow and an OOM risk.

    Staleness guard (matches compute_liquidity / the pipeline _stale pre-filter):
    rn<short/long counts rows by POSITION, so a halted/delisted ticker with old rows
    would surge-score on stale volume. Drop tickers whose most recent real row is
    more than max_staleness_days behind the dataset's reference date (= latest date)."""
    df = prices_long[["ticker", "date", "volume"]].copy()
    df["volume"] = df["volume"].astype(float)
    df.sort_values(["ticker", "date"], inplace=True)
    tk = df["ticker"]
    rn = df.groupby("ticker").cumcount(ascending=False)   # 0 = most recent row per ticker
    short_mean = df["volume"].where(rn < short_window).groupby(tk).mean()
    long_mean = df["volume"].where(rn < long_window).groupby(tk).mean()
    cnt = tk.groupby(tk).size()                           # rows per ticker
    reference_date = df["date"].max()
    latest_by_ticker = df.groupby("ticker")["date"].max()
    not_stale = latest_by_ticker >= (reference_date - pd.Timedelta(days=max_staleness_days))
    not_stale = not_stale.reindex(short_mean.index, fill_value=False)
    score = (short_mean / long_mean).where(
        (cnt >= long_window) & (long_mean > 0) & not_stale
    )
    score.name = "volume_surge"
    return score


def compute_near_high(prices: pd.DataFrame, window: int = 252,
                      max_staleness_days: int = 7) -> pd.Series:
    """Proximity to the trailing high (raw, higher = closer to/at the high) — a
    breakout/strength signal: last_close / max(close over window), in (0, 1]. Takes
    the wide adjusted_close pivot (date × ticker). NaN with < 2 rows or non-positive
    high. Optional factor.

    Staleness guard (matches compute_liquidity / the pipeline _stale pre-filter):
    `ffill().iloc[-1]` forward-fills a halted/delisted ticker's old close to the
    last row, so it would score ~1.0 (at its own stale high) on dead data. Drop any
    ticker whose most recent REAL (non-NaN) date in the pivot is more than
    max_staleness_days behind the pivot's latest date."""
    if len(prices) < 2:
        return pd.Series(dtype=float, name="near_high")
    hist = prices.iloc[-window:] if len(prices) >= window else prices
    high = hist.max(skipna=True)
    last = hist.ffill().iloc[-1]
    score = (last / high).where(high > 0)
    # Per-ticker last date with a real (non-NaN) value vs the pivot's latest date.
    idx = pd.to_datetime(prices.index)
    reference_date = idx.max()
    real_mask = prices.notna()
    last_real = real_mask.apply(lambda col: idx[col.values].max() if col.any() else pd.NaT)
    stale = last_real < (reference_date - pd.Timedelta(days=max_staleness_days))
    score = score.where(~stale.reindex(score.index, fill_value=True))
    score.name = "near_high"
    return score


def compute_all_factors(
    prices_long: pd.DataFrame,
    fundamentals: pd.DataFrame,
    cfg: FactorEngineConfig | None = None,
    copy_input: bool = True,
    sector_map: dict[str, str] | None = None,
    earnings: pd.DataFrame | None = None,
    as_of_date: _date | None = None,
) -> pd.DataFrame:
    if cfg is None:
        cfg = FactorEngineConfig()

    # Peak memory here is the OOM driver on small hosts: the long-form price frame
    # is held while a sorted copy + the wide pivot are also built. copy_input=False
    # lets the pipeline hand off a disposable frame so we mutate/sort it IN PLACE
    # instead of allocating a second universe-scale copy. Default True preserves the
    # no-mutation contract every other caller/test relies on. Output is identical.
    if copy_input:
        prices_long = prices_long.copy()
        prices_long["date"] = pd.to_datetime(prices_long["date"])
        prices_long = prices_long.sort_values(["ticker", "date"])
    else:
        prices_long["date"] = pd.to_datetime(prices_long["date"])
        prices_long.sort_values(["ticker", "date"], inplace=True)

    prices_long["adjusted_close"] = prices_long["adjusted_close"].astype(float)
    # Use pivot() not pivot_table(): pivot() raises ValueError on duplicate (date, ticker) pairs,
    # making data integrity issues visible. pivot_table() silently averages duplicates.
    pivot = prices_long.pivot(index="date", columns="ticker", values="adjusted_close")
    pivot = pivot.sort_index()

    momentum_raw = compute_momentum(pivot, short_window=cfg.momentum_short_window, long_window=cfg.momentum_long_window, method=cfg.momentum_method, blend_long_windows=cfg.momentum_blend_windows)
    low_vol_raw = compute_low_volatility(pivot, window=cfg.volatility_window)
    near_high_raw = compute_near_high(pivot, window=cfg.volatility_window)
    del pivot  # the wide date×ticker matrix is no longer needed — free it before ranking
    liquidity_raw = compute_liquidity(prices_long, window=cfg.liquidity_window)
    quality_raw = compute_quality(fundamentals, use_gross_profitability=cfg.quality_use_gross_profitability)
    value_raw = compute_value(fundamentals, pe_pb_cap=cfg.pe_pb_cap)
    growth_raw = compute_growth(fundamentals)
    issuance_raw = compute_issuance(fundamentals)
    small_cap_raw = compute_small_cap(fundamentals)
    volume_surge_raw = compute_volume_surge(prices_long)
    # Earnings-surprise (PEAD) — point-in-time SUE as of the score date. Null
    # (→ neutral, renormalized out) when no earnings data is loaded or no in-window
    # report exists, so the factor is inert until earnings are ingested.
    if earnings is not None and as_of_date is not None:
        earnings_surprise_raw = compute_earnings_surprise(
            earnings, as_of_date,
            drift_window_days=cfg.earnings_drift_window_days,
        )
    else:
        earnings_surprise_raw = pd.Series(dtype=float, name="earnings_surprise")

    all_tickers = prices_long["ticker"].unique().tolist()
    result = pd.DataFrame(index=all_tickers)
    result.index.name = "ticker"

    def _align(raw: pd.Series) -> pd.Series:
        return raw.reindex(result.index)

    neutral = set(cfg.industry_neutral_factors)

    def _rank(name: str, raw: pd.Series) -> pd.Series:
        # Sector-neutral ranking for factors the config opts in (value/quality/
        # growth only — the validator forbids momentum/low_vol/liquidity); every
        # other factor is ranked universe-wide. neutralized_percentile itself
        # falls back to universe-wide when sector_map is None.
        aligned = _align(raw)
        if name in neutral:
            return neutralized_percentile(aligned, sector_map, cfg.min_sector_group_size)
        return cross_section_percentile(aligned)

    # Percentile-rank each factor cross-sectionally to [0, 1].
    # Winsorization before percentile ranking is unnecessary — percentile ranking is
    # already outlier-robust by construction (a z=6 outlier gets percentile=1.0,
    # same ceiling as any other top-ranked ticker).
    result["momentum"]      = _rank("momentum", momentum_raw)
    result["low_volatility"]= _rank("low_volatility", low_vol_raw)
    result["liquidity"]     = _rank("liquidity", liquidity_raw)
    result["quality"]       = _rank("quality", quality_raw)
    result["value"]         = _rank("value", value_raw)
    result["growth"]        = _rank("growth", growth_raw)
    result["issuance"]      = _rank("issuance", issuance_raw)
    # Speculative-style factors (optional; default weight 0 → no effect on the core
    # model). high_volatility is the inverse percentile of low_volatility (high-vol
    # names score high) — free, no recompute.
    result["small_cap"]       = _rank("small_cap", small_cap_raw)
    result["volume_surge"]    = _rank("volume_surge", volume_surge_raw)
    result["near_high"]       = _rank("near_high", near_high_raw)
    result["high_volatility"] = 1.0 - result["low_volatility"]
    result["earnings_surprise"] = _rank("earnings_surprise", earnings_surprise_raw)

    result = result.reset_index()
    return result
