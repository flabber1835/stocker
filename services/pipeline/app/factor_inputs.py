"""Assembling the inputs the factor step computes over.

This is a VERBATIM extraction of steps 1-5b of `main._do_calculate` — universe,
sector labels, benchmark history + regime, the investability prefilter, full
price history, last-known-good fundamentals, and earnings. Nothing here writes.

It exists because two callers now need the SAME inputs:

  * `_do_calculate`, which then computes factors and PERSISTS them; and
  * `POST /preview/factors`, which computes factors under a CANDIDATE
    `factor_engine` block and persists nothing.

A preview that assembled its inputs differently from production would score a
different universe than the live chain and report the difference as a config
effect — the class of error the parity manifests exist to prevent. So the
preview does not get its own loaders; it calls these.

`universe_override` is the one behavioural seam. A `factor_engine` diff cannot
change investability (that is `universe.*`), so the preview passes the surviving
tickers of the run it is diffing against and skips the prefilter + gate entirely.
That is both cheaper and strictly more comparable: the candidate is scored over
exactly the population the active ranking was computed over.

Audit logging and progress reporting are INJECTED (`log` / `progress`) rather
than performed here, so the read path is identical for both callers while only
the chain writes `execution_steps` rows.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

import pandas as pd
from sqlalchemy import text

from app.factors import drop_fundamentalless
from app.regime import detect_regime, resolve_confirmed_regime

# ── Constants shared with main.py (imported back there, so `app.main.X` still
# resolves for existing callers and tests) ───────────────────────────────────

# Last-known-good window for the factor step's fundamentals read: each field
# independently takes its latest non-null value among a ticker's rows inside
# this window, bridging a degraded vendor refresh (see the Step 5 comment).
FUND_LKG_WINDOW_DAYS = int(os.getenv("FUND_LKG_WINDOW_DAYS", "45"))

# Numeric fundamentals fields the factor step consumes; each gets the
# latest-non-null treatment. Kept as a module constant so the SQL builder and
# tests share one source.
FUND_FIELDS = (
    "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
    "revenue_growth", "eps_growth", "gross_profit", "total_assets",
    "shares_outstanding", "shares_outstanding_prior", "market_cap",
)

# Market proxy for regime detection, beta, and drawdown-excess. Configurable (default
# SPY) so the engine isn't hardcoded to one index; must be a ticker av-ingestor fetches
# (it's in BENCHMARK_TICKERS). Default SPY = unchanged behavior.
MARKET_BENCHMARK = os.getenv("MARKET_BENCHMARK", "SPY")

# P6a: sentinel regime used when the benchmark history is too short to detect a real
# regime AND regime weighting is OFF (so the regime doesn't drive scoring). Lets the
# chain proceed instead of hard-halting on a missing benchmark window. Safe ONLY when
# regime_weighting_enabled is False — effective_factor_weights ignores the regime then.
REGIME_UNKNOWN = "unknown"

# Column order of the fundamentals frame. Must match _lkg_fundamentals_sql()'s
# projection exactly — a drift here silently mislabels columns.
FUND_DF_COLUMNS = ["ticker", "as_of_date", *FUND_FIELDS]

EARNINGS_COLUMNS = ["ticker", "reported_date", "fiscal_date_ending",
                    "reported_eps", "estimated_eps"]


def lkg_fundamentals_sql() -> str:
    """Per-ticker, PER-FIELD latest non-null fundamentals within the window.

    (ARRAY_REMOVE(ARRAY_AGG(col ORDER BY as_of_date DESC), NULL))[1] is the
    newest non-null value of `col` for the group — one degraded row no longer
    nulls a field that the previous week's row still carries. as_of_date is the
    ticker's newest row date (staleness accounting unchanged)."""
    field_exprs = ", ".join(
        f"(ARRAY_REMOVE(ARRAY_AGG({f} ORDER BY as_of_date DESC), NULL))[1] AS {f}"
        for f in FUND_FIELDS
    )
    return (
        "SELECT ticker, MAX(as_of_date) AS as_of_date, " + field_exprs + " "
        "FROM fundamentals "
        "WHERE ticker = ANY(:tickers) AND source != 'no_data' AND as_of_date >= :cutoff "
        "GROUP BY ticker"
    )


# ── Result ───────────────────────────────────────────────────────────────────

LogFn = Callable[..., Awaitable[None]]
ProgressFn = Callable[[int], None]


@dataclass
class FactorInputs:
    """Everything `compute_all_factors` needs, plus what the caller reports on.

    The frames are handed over by REFERENCE and are disposable: `_do_calculate`
    passes `prices_df` to `compute_all_factors(copy_input=False)`, which mutates
    it in place. Do not retain them past the compute.
    """
    universe_tickers: list[str]
    sector_map: dict[str, str]
    score_date: _date
    raw_regime: str
    confirmed_regime: str
    regime_info: dict
    prior_confirmed: Optional[str]
    regime_switched: bool
    prices_df: pd.DataFrame
    fundamentals_df: pd.DataFrame
    earnings_df: pd.DataFrame
    snapshot_id: Optional[int] = None
    tickers_with_fund: set[str] = field(default_factory=set)
    stats: dict = field(default_factory=dict)


async def _noop_log(*_args, **_kwargs) -> None:
    return None


def _noop_progress(_pct: int) -> None:
    return None


async def load_factor_inputs(
    engine,
    strategy,
    *,
    universe_override: list[str] | None = None,
    log: LogFn | None = None,
    progress: ProgressFn | None = None,
) -> FactorInputs:
    """Load every input the factor step consumes. Read-only.

    `universe_override` skips the snapshot read AND the investability prefilter,
    scoring exactly the tickers given. Only the preview path uses it — see the
    module docstring for why that is sound for a `factor_engine`-only diff.
    """
    log = log or _noop_log
    progress = progress or _noop_progress

    progress(2)
    stats: dict = {}
    snapshot_id: Optional[int] = None

    # ── Step 1: load universe ─────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        if universe_override is not None:
            raw_tickers = list(universe_override)
        else:
            # Active snapshot = MAX(id) — the SAME selector av-ingestor, llm-vetter,
            # portfolio-builder, and the api use (audit P0 split-brain fix). Previously this
            # ordered by (snapshot_date DESC, fetched_at DESC); snapshot_date is day-grained,
            # so two snapshots written the same day (manual re-run + cron) could resolve to a
            # DIFFERENT row here than MAX(id) elsewhere — the factor step would then score a
            # different universe than the one fetched-for/executed-on. MAX(id) is the single
            # monotonic source of truth for "newest snapshot".
            snap_row = await conn.execute(text("SELECT MAX(id) FROM universe_snapshots"))
            snap = snap_row.fetchone()
            if snap is None or snap[0] is None:
                raise RuntimeError("no universe snapshot — run fetch-universe first")

            snapshot_id = snap[0]
            ticker_rows = await conn.execute(
                text("SELECT ticker FROM universe_tickers WHERE snapshot_id = :sid"),
                {"sid": snapshot_id},
            )
            raw_tickers = [r[0] for r in ticker_rows.fetchall()]

        # ticker -> sector label (AV `Sector`) for industry-neutral factor ranking.
        # Membership comes from the current snapshot (above); the sector LABEL is the
        # latest non-null across snapshots — a fresh weekly snapshot inserts
        # sector=NULL for every row (LISTING_STATUS has no sector), so reading the
        # current snapshot's sector would silently degrade neutralization to
        # universe-wide right after each refresh. neutralized_percentile still falls
        # back to universe-wide for any ticker absent from this map.
        sector_rows = await conn.execute(
            text(
                "SELECT DISTINCT ON (ticker) ticker, sector FROM universe_tickers "
                "WHERE ticker = ANY(:tickers) AND sector IS NOT NULL "
                "ORDER BY ticker, snapshot_id DESC"
            ),
            {"tickers": raw_tickers},
        )
        sector_map = {r[0]: r[1] for r in sector_rows.fetchall()}

    universe_tickers = list(dict.fromkeys(raw_tickers))
    duplicates_removed = len(raw_tickers) - len(universe_tickers)
    total_in_snap = len(raw_tickers)

    await log(
        "load_universe", "success" if universe_tickers else "skipped",
        started_at=t0,
        input_summary={"snapshot_id": snapshot_id},
        output_summary={
            "total_in_snapshot": total_in_snap,
            "duplicates_removed": duplicates_removed,
            "investable_count": len(universe_tickers),
        },
        error_message="empty universe snapshot" if not universe_tickers else None,
    )

    if not universe_tickers:
        raise RuntimeError("empty universe snapshot")

    print(f"[calculate] universe: {len(universe_tickers)} tickers")

    # ── Step 2: load benchmark prices ─────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    fe = strategy.factor_engine
    spy_lookback = fe.spy_price_lookback_days
    async with engine.connect() as conn:
        spy_rows = await conn.execute(
            text(
                # Anchor lookback to MAX(date) in daily_prices, not NOW(), so
                # back-test and harness runs (which use historical dates) work
                # correctly when the wallclock is ahead of the data dates.
                "SELECT date, adjusted_close FROM daily_prices "
                "WHERE ticker = :bench "
                "  AND date >= (SELECT MAX(date) FROM daily_prices WHERE ticker = :bench) "
                "              - (:lookback * INTERVAL '1 day') "
                "ORDER BY date ASC"
            ),
            {"lookback": spy_lookback, "bench": MARKET_BENCHMARK},
        )
        spy_df = pd.DataFrame(spy_rows.fetchall(), columns=["date", "adjusted_close"])

    await log(
        "load_spy_prices", "success" if not spy_df.empty else "skipped",
        started_at=t0,
        output_summary={
            "row_count": len(spy_df),
            "date_min": str(spy_df["date"].min()) if not spy_df.empty else None,
            "date_max": str(spy_df["date"].max()) if not spy_df.empty else None,
        },
    )

    # ── Step 3: detect regime ─────────────────────────────────────────────────
    t0 = datetime.now(timezone.utc)
    insufficient_bench = len(spy_df) < strategy.regime_detection.slow_sma
    if insufficient_bench:
        msg = (f"insufficient market-benchmark ({MARKET_BENCHMARK}) history: {len(spy_df)} rows, "
               f"need {strategy.regime_detection.slow_sma} — is MARKET_BENCHMARK a ticker "
               f"av-ingestor fetches (it must be in BENCHMARK_TICKERS)?")
        # P6a: a missing/short benchmark window must NOT hard-halt the whole chain when
        # regime weighting is OFF — the regime doesn't drive scoring then (static
        # weights are used regardless), so it is disproportionate to block all trading
        # on it. Proceed with a sentinel regime IF we still have at least one benchmark
        # bar (for a score_date). With weighting ENABLED, or NO benchmark at all, we
        # still halt (weights genuinely need the regime / there is no run date).
        if strategy.regime_weighting_enabled or spy_df.empty:
            raise RuntimeError(msg)
        print(f"[calculate] WARNING: {msg} — regime weighting disabled, proceeding with "
              f"sentinel regime '{REGIME_UNKNOWN}'", flush=True)
        score_date = pd.to_datetime(spy_df["date"]).max().date()
        raw_regime = confirmed_regime = REGIME_UNKNOWN
        regime_info = {"raw_regime": REGIME_UNKNOWN, "spy_price": None,
                       "spy_sma_slow": None, "spy_vs_sma": None, "realized_vol": None}
        prior_confirmed = None
        switched = False
    else:
        score_date = pd.to_datetime(spy_df["date"]).max().date()
        print(f"[calculate] score_date={score_date}")

        regime_info = detect_regime(spy_df, strategy.regime_detection)
        raw_regime = regime_info["raw_regime"]

        async with engine.connect() as conn:
            history_rows = await conn.execute(
                text(
                    "SELECT raw_regime, regime FROM ("
                    "  SELECT DISTINCT ON (snapshot_date) snapshot_date, raw_regime, regime, calculated_at"
                    "  FROM regime_snapshots"
                    "  WHERE snapshot_date < :score_date"
                    "  ORDER BY snapshot_date DESC, calculated_at DESC"
                    ") x ORDER BY snapshot_date DESC LIMIT :n"
                ),
                {"n": strategy.regime_detection.confirmation_days, "score_date": score_date},
            )
            history = history_rows.fetchall()

        prior_raw_regimes = [r[0] for r in history]
        prior_confirmed = history[0][1] if history else None
        confirmed_regime = resolve_confirmed_regime(
            raw_regime, prior_raw_regimes, prior_confirmed,
            strategy.regime_detection.confirmation_days,
        )

        switched = prior_confirmed != confirmed_regime
        if switched:
            print(f"[calculate] regime SWITCHED: {prior_confirmed} → {confirmed_regime}")
        else:
            print(f"[calculate] regime={confirmed_regime} (raw={raw_regime})")

    await log(
        "detect_regime", "success",
        started_at=t0,
        input_summary={"spy_history_rows": len(spy_df),
                       "confirmation_days": strategy.regime_detection.confirmation_days},
        output_summary={
            "raw_regime": raw_regime,
            "confirmed_regime": confirmed_regime,
            "prior_confirmed": prior_confirmed,
            "switched": switched,
            "spy_vs_sma": round(float(regime_info["spy_vs_sma"]), 4),
            "realized_vol": round(float(regime_info["realized_vol"]), 4),
        },
    )

    progress(18)
    price_lookback = max(fe.momentum_long_window, fe.volatility_window) + 150
    no_price_data_count = 0
    no_price_tickers: list[str] = []
    price_max_date = None

    if universe_override is None:
        # ── Step 4a: pre-filter using recent prices ───────────────────────────
        # Load only the last 30 days to cheaply determine the investable set
        # before loading a full year of history for the entire universe.
        # This avoids a 1M+ row fetchall() for tickers that will be filtered out.
        t0 = datetime.now(timezone.utc)
        async with engine.connect() as conn:
            prefilter_rows = await conn.execute(
                text(
                    "SELECT ticker, date, adjusted_close, close, volume FROM daily_prices "
                    "WHERE ticker = ANY(:tickers) "
                    "  AND date >= (SELECT MAX(date) FROM daily_prices) - INTERVAL '30 days' "
                    "ORDER BY ticker, date ASC"
                ),
                {"tickers": universe_tickers},
            )
            prefilter_df = pd.DataFrame(
                prefilter_rows.fetchall(),
                columns=["ticker", "date", "adjusted_close", "close", "volume"],
            )

        if prefilter_df.empty:
            raise RuntimeError("no price data found for universe tickers")

        prefilter_df["date"] = pd.to_datetime(prefilter_df["date"])
        tickers_with_recent: set[str] = set(prefilter_df["ticker"].unique())
        no_price_tickers = sorted(t for t in universe_tickers if t not in tickers_with_recent)
        price_max_date = prefilter_df["date"].max().date()

        uni_cfg = strategy.universe
        min_price_filter = uni_cfg.min_price
        min_avg_dv_filter = uni_cfg.min_avg_dollar_volume_20d

        # CANONICAL investability definition (shared.investability): avg dollar volume =
        # mean(close × volume) over the last 20 sessions; below floor = price < min_price OR
        # avg_dv < min_avg_dollar_volume. This factor step is the reference implementation
        # (vectorized for the whole universe); the delta below-floor exit and the
        # portfolio-builder filter use the shared helpers so all three agree.
        pf_sorted = prefilter_df.sort_values("date")
        latest_price = pf_sorted.groupby("ticker")["adjusted_close"].last().fillna(0.0)
        last20 = pf_sorted.groupby("ticker").tail(20).copy()
        last20["dv"] = last20["close"].astype(float) * last20["volume"].astype(float)
        avg_dv_20d = last20.groupby("ticker")["dv"].mean()
        _ref_date = pf_sorted["date"].max()
        _latest_by_ticker = last20.groupby("ticker")["date"].max()
        _stale = _latest_by_ticker[_latest_by_ticker < (_ref_date - pd.Timedelta(days=7))].index
        avg_dv_20d.loc[_stale] = 0.0
        avg_dv_20d = avg_dv_20d.fillna(0.0)

        no_price_data_count = len(no_price_tickers)
        below_price_list = [t for t in tickers_with_recent if latest_price.get(t, 0.0) < min_price_filter]
        below_price_set = set(below_price_list)
        below_dv_list = [
            t for t in tickers_with_recent
            if t not in below_price_set and avg_dv_20d.get(t, 0.0) < min_avg_dv_filter
        ]
        investable_set = tickers_with_recent - below_price_set - set(below_dv_list)

        pre_filter_count = len(universe_tickers)
        universe_tickers = [t for t in universe_tickers if t in investable_set]

        # Free pre-filter data before the full-history load
        del prefilter_df, pf_sorted, last20

        print(
            f"[calculate] universe filter: {pre_filter_count} → {len(universe_tickers)} tickers "
            f"({no_price_data_count} no price data, {len(below_price_list)} below price ${min_price_filter}, "
            f"{len(below_dv_list)} below avg_dv ${min_avg_dv_filter/1e6:.0f}M)"
        )

        await log(
            "apply_universe_filters", "success",
            started_at=t0,
            input_summary={
                "pre_filter_count": pre_filter_count,
                "min_price": min_price_filter,
                "min_avg_dollar_volume_20d": min_avg_dv_filter,
            },
            output_summary={
                "post_filter_count": len(universe_tickers),
                "filtered_count": pre_filter_count - len(universe_tickers),
                "no_price_data_count": no_price_data_count,
                "below_min_price_count": len(below_price_list),
                "below_min_avg_dv_count": len(below_dv_list),
            },
        )

        if not universe_tickers:
            raise RuntimeError(
                "no investable tickers after universe filters — check min_price and min_avg_dollar_volume_20d")

    progress(30)
    # ── Step 4b: load full price history for investable tickers only ──────────
    # Universe is already filtered — only load tickers that passed the
    # price/liquidity gate above, cutting the fetch roughly in half.
    t0 = datetime.now(timezone.utc)
    async with engine.connect() as conn:
        price_rows = await conn.execute(
            text(
                # Anchor lookback to MAX(date) across all price data, not
                # CURRENT_DATE, so harness runs with historical dates work.
                "SELECT ticker, date, adjusted_close, close, volume FROM daily_prices "
                "WHERE ticker = ANY(:tickers) "
                "  AND date >= (SELECT MAX(date) FROM daily_prices) "
                "              - (:lookback * INTERVAL '1 day') "
                "ORDER BY ticker, date ASC"
            ),
            {"tickers": universe_tickers, "lookback": price_lookback},
        )
        prices_df = pd.DataFrame(
            price_rows.fetchall(),
            columns=["ticker", "date", "adjusted_close", "close", "volume"],
        )

    tickers_with_prices: set[str] = set()
    coverage_by_ticker: dict[str, dict] = {}
    price_min_date = None

    if not prices_df.empty:
        prices_df["date"] = pd.to_datetime(prices_df["date"])
        tickers_with_prices = set(prices_df["ticker"].unique())
        price_min_date = prices_df["date"].min().date()
        if price_max_date is None:
            price_max_date = prices_df["date"].max().date()
        cov = (
            prices_df.groupby("ticker")["date"]
            .agg(date_min="min", date_max="max", row_count="count")
            .reset_index()
        )
        coverage_by_ticker = {
            str(r["ticker"]): {
                "date_min": str(r["date_min"].date()),
                "date_max": str(r["date_max"].date()),
                "row_count": int(r["row_count"]),
            }
            for _, r in cov.iterrows()
        }

    await log(
        "load_price_history", "success" if not prices_df.empty else "skipped",
        started_at=t0,
        input_summary={"ticker_count": len(universe_tickers)},
        output_summary={
            "row_count": len(prices_df),
            "ticker_count": len(tickers_with_prices),
            "date_min": str(price_min_date) if price_min_date else None,
            "date_max": str(price_max_date) if price_max_date else None,
            "no_price_data_count": no_price_data_count,
            "no_price_data_tickers": no_price_tickers[:100],
        },
        error_message="no price data found" if prices_df.empty else None,
    )

    if prices_df.empty:
        raise RuntimeError("no price data found for investable tickers")

    print(f"[calculate] loaded {len(prices_df)} price rows for {prices_df['ticker'].nunique()} tickers")

    progress(58)
    # ── Step 5: load fundamentals — LAST-KNOWN-GOOD per field ─────────────────
    # The old `DISTINCT ON (ticker) ... ORDER BY as_of_date DESC` took the
    # latest row VERBATIM, so a single degraded vendor refresh (the PBR
    # incident: AV nulled total_assets in one weekly row while every other
    # field was fine) poisoned that field for ~a week — quality went null,
    # the required_factors gate ejected both Petrobras listings, and the held
    # one started an orphan-exit countdown. Now each FIELD independently takes
    # its latest non-null value within FUND_LKG_WINDOW_DAYS, so a one-row blip
    # is bridged by the previous good row. Tickers with NO row inside the
    # window fall back to the old latest-row-verbatim behavior (no regression
    # for rarely-refreshed names; the >90d staleness warning still applies).
    t0 = datetime.now(timezone.utc)
    _fund_cutoff = score_date - timedelta(days=FUND_LKG_WINDOW_DAYS)
    async with engine.connect() as conn:
        fund_rows = await conn.execute(
            text(lkg_fundamentals_sql()),
            {"tickers": universe_tickers, "cutoff": _fund_cutoff},
        )
        _fund_records = fund_rows.fetchall()
        _lkg_tickers = {r[0] for r in _fund_records}
        _leftover = [t for t in universe_tickers if t not in _lkg_tickers]
        if _leftover:
            older_rows = await conn.execute(
                text(
                    "SELECT DISTINCT ON (ticker) ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity, "
                    "revenue_growth, eps_growth, gross_profit, total_assets, "
                    "shares_outstanding, shares_outstanding_prior, market_cap FROM fundamentals "
                    "WHERE ticker = ANY(:tickers) AND source != 'no_data' "
                    "ORDER BY ticker, as_of_date DESC"
                ),
                {"tickers": _leftover},
            )
            _fund_records = list(_fund_records) + older_rows.fetchall()
    fund_df = pd.DataFrame(_fund_records, columns=list(FUND_DF_COLUMNS))

    tickers_with_fund = set(fund_df["ticker"].unique()) if not fund_df.empty else set()
    tickers_with_fundamentals = len(tickers_with_fund)
    no_fundamentals_tickers = sorted(t for t in universe_tickers if t not in tickers_with_fund)
    tickers_without_fundamentals = len(no_fundamentals_tickers)
    fund_warnings = []
    if tickers_without_fundamentals > 0:
        fund_warnings.append(f"{tickers_without_fundamentals} tickers have no fundamentals — quality/value/growth will be null")
    stale_fund_count = 0
    if not fund_df.empty and "as_of_date" in fund_df.columns:
        fund_df["as_of_date"] = pd.to_datetime(fund_df["as_of_date"]).dt.date
        stale_fund_count = int((fund_df["as_of_date"].apply(lambda d: (score_date - d).days) > 90).sum())
        if stale_fund_count > 0:
            fund_warnings.append(f"{stale_fund_count} tickers have fundamentals older than 90 days")

    await log(
        "load_fundamentals", "success",
        started_at=t0,
        input_summary={"ticker_count": len(universe_tickers)},
        output_summary={
            "tickers_with_fundamentals": tickers_with_fundamentals,
            "tickers_without_fundamentals": tickers_without_fundamentals,
            "stale_fundamentals_count": stale_fund_count,
            "no_fundamentals_tickers": no_fundamentals_tickers,
        },
        warnings=fund_warnings or None,
    )

    print(f"[calculate] loaded fundamentals for {tickers_with_fundamentals} tickers")

    # Drop fundamentals-less securities (ETFs / closed-end funds file no financials)
    # from the rankable universe when the strategy requires fundamentals. This keeps
    # index / leveraged ETFs (SOXX, SNXX, QQQ, IWM, …) out of a price/volume-only
    # ranking — the speculative sleeve uses required_factors=[momentum, liquidity],
    # which a fundamentals-less ETF would otherwise satisfy and top. Filtering BEFORE
    # factor computation also keeps the cross-sectional percentiles clean: leveraged
    # ETFs carry extreme vol / near-high values that would distort the scale for real
    # stocks. Default-False strategies (core) are unaffected.
    prices_df, fund_etf_dropped = drop_fundamentalless(
        prices_df, tickers_with_fund, getattr(strategy.universe, "require_fundamentals", False)
    )
    if fund_etf_dropped:
        print(f"[calculate] require_fundamentals: dropped {fund_etf_dropped} fundamentals-less tickers (ETFs/funds)")

    # ── Step 5b: load earnings (for the earnings-surprise / PEAD factor) ───────
    # Point-in-time is enforced in the factor (only quarters reported_date <=
    # score_date are used). Loading the full per-ticker history lets the factor
    # standardize the surprise by the ticker's own surprise volatility (SUE).
    # Missing/empty → the factor is null everywhere → renormalized out (inert).
    # fiscal_date_ending is REQUIRED by the seasonal-random-walk SUE (the default
    # sue_method): it aligns the year-ago quarter by fiscal PERIOD rather than by
    # row position, so a missing or restated quarter cannot shift the comparison
    # onto the wrong period.
    earnings_df = pd.DataFrame(columns=list(EARNINGS_COLUMNS))
    try:
        async with engine.connect() as conn:
            erows = await conn.execute(
                text("SELECT ticker, reported_date, fiscal_date_ending, reported_eps, "
                     "       estimated_eps "
                     "FROM earnings WHERE ticker = ANY(:tk) AND reported_date IS NOT NULL"),
                {"tk": list(universe_tickers)},
            )
            _erecs = erows.fetchall()
        if _erecs:
            earnings_df = pd.DataFrame(_erecs, columns=list(EARNINGS_COLUMNS))
        print(f"[calculate] loaded {len(earnings_df)} earnings rows "
              f"for {earnings_df['ticker'].nunique() if not earnings_df.empty else 0} tickers")
    except Exception as exc:
        # Earnings are optional: a missing table / load error must not fail factors.
        print(f"[calculate] earnings load skipped (factor will be neutral): {exc}", flush=True)

    stats.update({
        "coverage_by_ticker": coverage_by_ticker,
        "tickers_with_prices": tickers_with_prices,
        "no_price_data_count": no_price_data_count,
        "no_price_data_tickers": no_price_tickers,
        "price_min_date": price_min_date,
        "price_max_date": price_max_date,
        "tickers_with_fundamentals": tickers_with_fundamentals,
        "tickers_without_fundamentals": tickers_without_fundamentals,
        "no_fundamentals_tickers": no_fundamentals_tickers,
        "stale_fundamentals_count": stale_fund_count,
        "fund_warnings": fund_warnings,
        "fund_etf_dropped": fund_etf_dropped,
        "duplicates_removed": duplicates_removed,
        "total_in_snapshot": total_in_snap,
    })

    return FactorInputs(
        universe_tickers=universe_tickers,
        sector_map=sector_map,
        score_date=score_date,
        raw_regime=raw_regime,
        confirmed_regime=confirmed_regime,
        regime_info=regime_info,
        prior_confirmed=prior_confirmed,
        regime_switched=switched,
        prices_df=prices_df,
        fundamentals_df=fund_df,
        earnings_df=earnings_df,
        snapshot_id=snapshot_id,
        tickers_with_fund=tickers_with_fund,
        stats=stats,
    )
