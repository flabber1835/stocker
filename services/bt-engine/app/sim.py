"""bt-engine core: point-in-time day-stepping strategy simulator (Phase 2).

Re-runs the LIVE chain's own logic day by day (docs/backtester-v2-plan.md):

    regime  = detect_regime(spy ≤ D)
    factors = compute_all_factors(prices ≤ D, fundamentals known-as-of ≤ D)
    ranks   = rank_universe(factors, regime, strategy)
    candidates -= falling_knife(prices ≤ D)          # deterministic veto, at selection
    target  = greedy_select + compute_weights (+ overlays)   # builder composition
    intents = evaluate_target_vs_live(target, sim_positions, rank_history, …)
    apply intents at the modeled fill price (+ tx cost); mark-to-market at D close

No look-ahead BY CONSTRUCTION: every computation for day D slices `date <= D`
(fundamentals by their point-in-time `as_of_date`); the gold-standard test runs
the sim on full data vs data truncated at K and asserts identical state at K.

Fill model (prices are Sharadar SEP: open/close unadjusted, adjusted_close
split+div adjusted). All accounting runs in the ADJUSTED price space so splits
never corrupt qty×price math:
    next_open (default, live-faithful): a rebalance decided after D's close fills
        at D+1's open, approximated in adjusted space as
        open(D+1) × adjusted_close(D+1)/close(D+1).
    close: fills at D's adjusted_close (idealized same-close fill).

This module is PURE (no DB, no env): main.py loads frames and persists results.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from stock_strategy_shared.drawdown import (
    excess_drawdown, recent_drawdown, falling_knife_verdict)
from stock_strategy_shared.drawdown import realized_vol as _realized_vol
from stock_strategy_shared.investability import (
    DOLLAR_VOLUME_WINDOW,
    avg_dollar_volume,
    below_investability_floor,
)
from stock_strategy_shared.schemas.strategy import StrategyConfig

from app import live
from app.bootstrap import bootstrap_terminal_wealth, daily_returns
from app.coverage import CoverageError, CoverageObserver
from app.coverage import enforcement_enabled as coverage_enforcement_enabled
from app.calibration import (aggregate_calibration, decile_forward_returns,
                             sample_evenly, space_out)

# Score calibration (closed-loop item 3): decile-of-score → forward return over
# this many sessions, on up to CALIB_MAX_DATES sampled rebalance dates, spaced at
# least one horizon apart so the observations are INDEPENDENT (overlapping
# windows share most of their return path, so a bootstrap over them understates
# the interval — 12 overlapping anchors are closer to 3 samples than to 12).
# 12 was far too few to settle a noisy one-month cross-sectional relationship;
# a 20-year corpus supports ~250 non-overlapping anchors, so take what fits.
CALIB_HORIZON_SESSIONS = 20
CALIB_MAX_DATES = int(os.getenv("BT_CALIB_MAX_DATES", "60"))

# Env-default falling-knife thresholds (mirror the vetter's DRAWDOWN_* defaults);
# a config's vetter.falling_knife overrides field-by-field, exactly like live.
_FK_DEFAULTS = dict(backstop_pct=0.25, window_days=21, excess_pct=0.15,
                    beta_lookback=120, vol_scaling=True, vol_anchor=0.35,
                    excess_min=0.10, excess_max=0.30)

# Trailing price history handed to the factor step per rebalance (calendar days).
# Momentum 12-1 needs ~370; covariance/regime ≤ 252 trading days. 420 covers all.
FACTOR_LOOKBACK_DAYS = 420
# A held name with no price for this many TRADING SESSIONS is treated as delisted
# and force-exited. Measured in real session indices against `all_days`, NOT in
# calendar days: the previous `(D - last_seen).days > DELIST_GAP_DAYS * 2` was a
# calendar approximation that landed nearer 10 sessions than 7 and drifted with
# holidays, so the constant did not mean what its name said.
DELIST_GAP_DAYS = 7

# Fraction of the last mark recovered on a delist exit. 1.0 (the old behaviour)
# assumed a company that stops printing at $2 is worth the full $2, which
# flatters exactly the speculative/distressed strategies most likely to be
# proposed. 0.70 follows the delisting-return literature (Shumway 1997: ≈ −30%
# for NYSE/AMEX performance-related delistings; worse on NASDAQ).
#
# HONEST: a FLAT rate over every delist exit, including mergers where recovery is
# typically at or above the last mark. A bias correction, not a model. Separating
# acquisition from failure needs the delisting REASON — available once the
# point-in-time universe carries `isdelisted`, and the natural follow-up.
DEFAULT_DELIST_RECOVERY_PCT = 0.70


def eligible_on(as_of: date, window: tuple | None) -> bool:
    """Was this ticker listed on `as_of`?

    POINT-IN-TIME eligibility from Sharadar's firstpricedate/lastpricedate.
    Previously the engine had ONE universe snapshot and inferred history from
    price presence alone, which cannot see when-issued securities, ticker reuse,
    reorganizations or temporary listing gaps.

    An UNKNOWN bound is not a constraint: a missing first_price_date must not
    erase a ticker from all of history, and a missing last_price_date is the
    normal representation of "still trading". Only a bound that is present AND
    violated excludes."""
    if not window:
        return True
    first, last = window
    if first is not None and as_of < first:
        return False
    if last is not None and as_of > last:
        return False
    return True


class TargetStatus:
    """Why the builder returned what it returned.

    `if target:` conflated "the builder failed" with "the strategy wants zero
    exposure". Both hold the book today only because the builder never
    intentionally returns an empty one — an assumption a future evaluator-authored
    config could invalidate in silence. Making the distinction explicit means a
    deliberate risk-off target is OBEYED while a degraded build is not."""
    SUCCESS_WITH_TARGET = "success_with_target"
    SUCCESS_EMPTY_TARGET = "success_empty_target"   # deliberate zero exposure
    DEGRADED = "degraded"                           # partial inputs → hold
    FAILED = "failed"                               # nothing rankable → hold

    ALL = (SUCCESS_WITH_TARGET, SUCCESS_EMPTY_TARGET, DEGRADED, FAILED)
    # Statuses that must NOT be acted on — the book is held as-is.
    HOLD = (DEGRADED, FAILED)


@dataclass
class SimParams:
    start: date
    end: date
    tx_cost_bps: int = 10
    fill_timing: str = "next_open"          # 'next_open' | 'close'
    starting_capital: float = 100_000.0
    rebalance_every: int = 1                # trading days between rebalances (1 = live-faithful)
    drawdown_backstop_pct: float | None = None   # optional override of config/env default
    # Proceeds fraction of the last mark on a delist exit; 1.0 restores the old
    # full-recovery behaviour. See DEFAULT_DELIST_RECOVERY_PCT.
    delist_recovery_pct: float = DEFAULT_DELIST_RECOVERY_PCT


@dataclass
class SimResult:
    summary: dict
    equity: list = field(default_factory=list)      # [{date, portfolio_value, spy_value, drawdown}]
    trades: list = field(default_factory=list)      # [{date, ticker, action, qty, price, tx_cost, reason}]
    positions: list = field(default_factory=list)   # EOD on rebalance days [{date, ticker, qty, weight, market_value}]
    caveats: list = field(default_factory=list)


def _is_ticker_date_sorted(px: pd.DataFrame) -> bool:
    """Cheap check that a price frame is already (ticker, date) ordered — the
    loader guarantees it, so the sim can skip a full-frame sort_values copy.
    Fails fast on the ticker column before touching the per-ticker dates."""
    if not px["ticker"].is_monotonic_increasing:
        return False
    d = px["date"]
    if d.is_monotonic_increasing:      # single ticker, or globally ordered
        return True
    # dates must be non-decreasing WITHIN each ticker block
    same_ticker = px["ticker"].to_numpy()[1:] == px["ticker"].to_numpy()[:-1]
    return bool(((d.to_numpy()[1:] >= d.to_numpy()[:-1]) | ~same_ticker).all())


def _pivot(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """date × ticker matrix. pivot() is a reshape; pivot_table() would run a
    groupby-mean over every row. (ticker, date) is the bt_prices PK so there is
    nothing to aggregate — but fall back if a caller's frame has duplicates."""
    try:
        return df.pivot(index="date", columns="ticker", values=value_col)
    except ValueError:
        return df.pivot_table(index="date", columns="ticker", values=value_col)


def _fk_params(config: StrategyConfig, override_backstop: float | None) -> dict:
    fk = getattr(config.vetter, "falling_knife", None)
    out = dict(_FK_DEFAULTS)
    if fk is not None:
        for k in out:
            v = getattr(fk, k, None)
            if v is not None:
                out[k] = v
    if override_backstop is not None:
        out["backstop_pct"] = override_backstop
    return out


def falling_knife_excluded(closes_by_ticker: dict[str, list[float]],
                           spy_closes: list[float], fk: dict) -> set[str]:
    """Deterministic falling-knife veto over candidates, from prices ≤ D only.
    Mirrors the vetter's two OR'd triggers: beta-adjusted excess (vol-scaled) +
    absolute floor. A name with no data trips neither (data-gap exemption)."""
    excluded: set[str] = set()
    window = int(fk["window_days"])
    for t, closes in closes_by_ticker.items():
        detail = excess_drawdown(closes, spy_closes, window=window,
                                 beta_lookback=int(fk["beta_lookback"]))
        if detail is None:
            # No beta path (insufficient aligned history) → absolute floor only,
            # off the stock-only raw drawdown (mirrors the vetter's raw_dd source).
            raw, exc, idio = recent_drawdown(closes, window=window), None, None
        else:
            raw, exc, idio = detail.get("raw_dd"), detail.get("excess_dd"), detail.get("idio_vol")
        # ONE shared decision — provably the live vetter's veto (audit-pattern:
        # the two-trigger logic used to be duplicated here and in llm-vetter).
        if falling_knife_verdict(
            raw, exc, idio,
            excess_pct=fk["excess_pct"], backstop_pct=fk["backstop_pct"],
            vol_scaling=fk["vol_scaling"], vol_anchor=fk["vol_anchor"],
            excess_min=fk["excess_min"], excess_max=fk["excess_max"],
        )["excluded"]:
            excluded.add(t)
    return excluded


def build_target(day_prices: pd.DataFrame, fundamentals_asof: pd.DataFrame,
                 sector_map: dict[str, str], config: StrategyConfig, regime: str,
                 fk: dict, spy_closes: list[float],
                 factor_cache=None, factor_key: str | None = None,
                 coverage_observer=None,
                 current_holdings: set | None = None,
                 listing_windows: dict | None = None,
                 earnings: pd.DataFrame | None = None,
                 blocked_tickers: set | None = None) -> tuple:
    """One rebalance: factors → rank → falling-knife → builder composition.
    Returns ({ticker: weight}, ranked_df, TargetStatus) — weights sum ≤ 1
    (cash_reserve / vol-target de-lever).
    Faithful to portfolio-builder _do_build ordering (cluster on the full pool,
    exclusions dropped from the selectable pool AFTER clustering).

    The STATUS is what distinguishes "the builder could not produce a book" from
    "the strategy wants no exposure" — see TargetStatus. The caller must not
    infer that from an empty dict.

    current_holdings feeds the turnover penalty, exactly as live does. An AST
    diff of the two greedy_select call sites found these were the only live-only
    kwargs, so a config with turnover_penalty > 0 was previously simulated as
    though it were 0.

    factor_cache/factor_key (sweeps): the factor frame depends only on
    (as_of_date, factor_engine config, loaded data), so across a sweep's many
    configs it is memoized per (date, factor-config) — see factor_cache.py."""
    pb = config.portfolio_builder
    as_of = day_prices["date"].max().date()
    fdf = None
    if factor_cache is not None and factor_key is not None:
        fdf = factor_cache.get(as_of, factor_key)
    if fdf is None:
        # copy_input=False: run_simulation already hands us a FRESH per-rebalance
        # slice (.copy() at the call site), so letting the factor step copy it
        # again doubled the transient allocation on every one of ~1000 rebalances.
        fdf = live.compute_all_factors(
            day_prices, fundamentals_asof, cfg=config.factor_engine,
            copy_input=False, sector_map=sector_map,
            as_of_date=as_of,
            # The factor enforces point-in-time itself (reported_date <= as_of),
            # so the whole history is passed once rather than sliced per date.
            earnings=earnings,
        )
        if factor_cache is not None and factor_key is not None:
            factor_cache.put(as_of, factor_key, fdf)
    # Observe the RAW factor frame, not `ranked`: rank_universe drops rows whose
    # composite is NaN, so a factor could look "never present" merely because the
    # rows carrying it were filtered out for an unrelated reason.
    if coverage_observer is not None:
        coverage_observer.observe(fdf)
    ranked = live.rank_universe(fdf, regime, config)
    if ranked.empty:
        # Nothing in the universe scored at all — inputs are unusable, not a
        # strategy decision.
        return {}, None, TargetStatus.FAILED
    # full_ranked (whole scored universe) is what callers get back — the score-
    # calibration diagnostic needs the full spectrum, not just the investable
    # head; selection below still works on the candidate_count head.
    full_ranked = ranked
    ranked = ranked.head(pb.candidate_count)
    candidates = ranked["ticker"].tolist()
    scores_map = dict(zip(ranked["ticker"], ranked["composite_score"].astype(float)))

    dnb = {t.upper() for t in (pb.do_not_buy or [])}
    candidates = [t for t in candidates if t.upper() not in dnb]

    sub = day_prices[day_prices["ticker"].isin(candidates)].sort_values("date")
    latest_px = sub.groupby("ticker", observed=True)["adjusted_close"].last().to_dict()
    avg_dv: dict[str, float] = {}
    if "close" in sub.columns and "volume" in sub.columns:
        for t, g in sub.groupby("ticker", observed=True):
            dv = avg_dollar_volume(g["close"].tolist(), g["volume"].tolist(),
                                   window=DOLLAR_VOLUME_WINDOW)
            if dv is not None:
                avg_dv[t] = dv
    # POINT-IN-TIME eligibility, applied at the same seam as the investability
    # floor: a name not listed on this date is not a candidate, whatever prices
    # happen to exist for its symbol.
    if listing_windows:
        candidates = [t for t in candidates
                      if eligible_on(as_of, listing_windows.get(t))]
    candidates = [t for t in candidates if t in latest_px and not below_investability_floor(
        latest_px.get(t), avg_dv.get(t),
        min_price=config.universe.min_price,
        min_avg_dollar_volume=config.universe.min_avg_dollar_volume_20d)]
    if len(candidates) < 2:
        # Fewer than two investable names survived the liquidity/price floor.
        return {}, None, TargetStatus.DEGRADED

    # Falling-knife veto at selection (plan decision #1): computed from prices ≤ D.
    closes_by_ticker = {t: g["adjusted_close"].astype(float).tolist()
                        for t, g in sub[sub["ticker"].isin(candidates)]
                        .sort_values("date").groupby("ticker", observed=True)}
    vetoed = falling_knife_excluded(closes_by_ticker, spy_closes, fk)

    cov, _dropped, raw_corr = live.build_covariance(
        day_prices[day_prices["ticker"].isin(candidates)],
        window_days=pb.covariance_window_days,
        min_observations=pb.min_covariance_observations,
        shrinkage=pb.covariance_shrinkage)
    if cov is None or len(cov) < 2:
        # Not enough overlapping price history to estimate covariance.
        return {}, None, TargetStatus.DEGRADED
    available = [t for t in candidates if t in cov.index]
    cluster_map = live.correlation_clusters(raw_corr, threshold=pb.cluster_correlation_threshold)

    # Exclusions after clustering, exactly like the builder.
    available = [t for t in available if t not in vetoed]
    # Trailing-stop re-entry blocks are an exclusion of exactly the same kind, so
    # they are applied at the same seam — AFTER clustering, so a blocked name still
    # acts as a single-linkage bridge and cannot fragment a real correlated theme.
    #
    # Applied HERE rather than to the finished target, which is what the first cut
    # did: removing names from a composed target left nothing in their place, so
    # the book shrank below max_positions AND the removed weight fell to cash. The
    # stop silently became a market-timing overlay nobody configured (observed:
    # 35 names → 26 during a drawdown). Excluding from the selectable pool lets
    # greedy_select backfill with the next-best candidate, so the stop changes
    # WHICH names are held, never HOW MANY or how invested the book is.
    if blocked_tickers:
        available = [t for t in available if t not in blocked_tickers]
    if pb.require_positive_composite_score:
        available = [t for t in available if scores_map[t] >= 0]
    if len(available) < 2:
        # Vetoes/score filters left nothing selectable. DEGRADED rather than a
        # deliberate flat book: the strategy asked for positions and could not
        # get them.
        return {}, None, TargetStatus.DEGRADED
    scores = pd.Series({t: scores_map[t] for t in available})
    cov = cov.loc[available, available]

    selected = live.greedy_select(
        scores, cov, target=pb.max_positions,
        sector_map=cluster_map, max_sector_weight=pb.max_cluster_weight,
        # Turnover-penalty parity with live. The `> 0` guard mirrors the builder
        # exactly, so a zero penalty passes None and the holdings-agnostic
        # behaviour is bit-identical to before this was wired.
        current_holdings=current_holdings if pb.turnover_penalty > 0.0 else None,
        turnover_penalty=pb.turnover_penalty,
        max_tickers_per_sector=pb.max_tickers_per_cluster,
        av_sector_map=sector_map, max_av_sector_weight=pb.max_sector_weight,
        selection_vol_aversion=pb.selection_vol_aversion)
    if not selected:
        return {}, full_ranked, TargetStatus.DEGRADED
    weights = live.compute_weights(
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

    if bool(getattr(pb, "beta_target_enabled", False)) and len(weights) > 1:
        # betas from the shared drawdown helper (same OLS as live display/veto).
        beta_map: dict[str, float] = {}
        for t in weights:
            closes = closes_by_ticker.get(t)
            if closes:
                detail = excess_drawdown(closes, spy_closes,
                                         window=int(fk["window_days"]),
                                         beta_lookback=int(fk["beta_lookback"]))
                b = detail.get("beta") if detail else None
                if b is not None:
                    beta_map[t] = float(b)
        constraints = []
        if pb.max_cluster_weight < 1.0:
            constraints.append((cluster_map, pb.max_cluster_weight))
        if pb.max_sector_weight < 1.0:
            constraints.append((sector_map, pb.max_sector_weight))
        for _ in range(3):
            weights, _info = live.solve_beta_target_weights(
                weights, beta_map, pb.beta_target, max_position_weight=max_pw)
            if constraints:
                weights = live.apply_all_caps(weights, max_pw, constraints)
                s = sum(weights.values())
                if s > 0:
                    weights = {t: w / s for t, w in weights.items()}

    cash_reserve = getattr(pb, "cash_reserve", 0.0)
    max_exposure = 1.0 - cash_reserve
    if bool(getattr(pb, "vol_target_enabled", False)):
        bvol = live.book_volatility(weights, cov)
        exposure = live.vol_target_exposure(bvol, pb.vol_target,
                                            min_exposure=pb.vol_target_min_exposure,
                                            max_exposure=max_exposure)
    else:
        exposure = max_exposure
    if exposure < 1.0 - 1e-12:
        weights = {t: w * exposure for t, w in weights.items()}
    out = {t: float(w) for t, w in weights.items()}
    # An empty book HERE is a real answer: everything upstream succeeded and the
    # composition step chose no exposure. That is obeyed, not overridden.
    status = (TargetStatus.SUCCESS_WITH_TARGET if out
              else TargetStatus.SUCCESS_EMPTY_TARGET)
    return out, full_ranked, status


def run_simulation(prices: pd.DataFrame, fundamentals: pd.DataFrame,
                   sector_map: dict[str, str], config: StrategyConfig,
                   params: SimParams, progress_cb=None, factor_cache=None,
                   listing_windows: dict | None = None,
                   earnings: pd.DataFrame | None = None) -> SimResult:
    """prices: long [ticker, date, open, close, adjusted_close, volume] covering
    [start − FACTOR_LOOKBACK_DAYS, end] incl. SPY. fundamentals: long
    [ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity, revenue_growth,
    eps_growth] with as_of_date = point-in-time known date."""
    caveats = [
        # earnings_surprise is the ONE remaining gap; the coverage contract
        # (app/coverage.py) refuses to score any config that weights it, so this
        # is a statement of scope rather than a silent degradation. issuance /
        # small_cap are now covered (bt_fundamentals carries market_cap and
        # shares_outstanding[_prior]); volume_surge never needed fundamentals at
        # all — it reads bt_prices.volume, and the old caveat claiming otherwise
        # was simply wrong.
        "earnings_surprise is not computable from the Sharadar corpus "
        "(no analyst estimates) — configs weighting it are refused, not degraded",
        # Listing/delisting WINDOWS are now point-in-time; the sector LABEL is
        # not, and Sharadar TICKERS has no historical classification to make it
        # so. Stated separately so the remaining gap is not mistaken for the
        # whole one having been closed.
        "sector labels are CURRENT-STATE (Sharadar TICKERS carries no historical "
        "classification) — listing/delisting windows ARE point-in-time",
    ]
    coverage = CoverageObserver(config)
    # Memory-lean input handling (full-history runs): data.load_prices already
    # delivers datetime64 dates, float price dtypes and (ticker, date) ordering,
    # so each of these full-frame copies is SKIPPED on the production path and
    # only taken when a caller (tests, synthetic data) hands us a raw frame.
    # Three avoided copies of a ~1GB frame is the difference between fitting the
    # 4g cap and OOM-killing the host.
    px = prices
    if not pd.api.types.is_datetime64_any_dtype(px["date"]):
        px = px.copy()
        px["date"] = pd.to_datetime(px["date"])
    if not _is_ticker_date_sorted(px):
        px = px.sort_values(["ticker", "date"], kind="stable")
    if not pd.api.types.is_float_dtype(px["adjusted_close"]):
        px = px.copy() if px is prices else px
        px["adjusted_close"] = pd.to_numeric(px["adjusted_close"], errors="coerce")

    fnd = fundamentals.copy()
    if not fnd.empty:
        fnd["as_of_date"] = pd.to_datetime(fnd["as_of_date"])
        fnd = fnd.sort_values(["ticker", "as_of_date"])

    spy = px[px["ticker"] == "SPY"][["date", "adjusted_close"]].rename(
        columns={"adjusted_close": "close"}).reset_index(drop=True)
    if spy.empty:
        raise ValueError("SPY prices required (regime + benchmark) but absent")

    all_days = spy["date"][(spy["date"] >= pd.Timestamp(params.start))
                           & (spy["date"] <= pd.Timestamp(params.end))].tolist()
    if len(all_days) < 2:
        raise ValueError("fewer than 2 trading days in range")

    # Session index for every trading day, so staleness is counted in real
    # SESSIONS rather than approximated from calendar days.
    day_index = {d: k for k, d in enumerate(all_days)}

    fk = _fk_params(config, params.drawdown_backstop_pct)
    factor_key = None
    if factor_cache is not None:
        from app.factor_cache import factor_cfg_key
        # factor_engine carries sue_method, so two configs differing only in SUE
        # method get different cache keys — the frames genuinely differ.
        factor_key = factor_cfg_key(config.factor_engine)
    rd_cfg = config.regime_detection

    # ── state ────────────────────────────────────────────────────────────────
    cash = float(params.starting_capital)
    qty: dict[str, float] = {}
    last_px: dict[str, float] = {}
    last_seen_i: dict[str, int] = {}            # ticker → session INDEX of last print
    unfilled: list[dict] = []                   # orders dropped for want of a price
    # Trailing stop (inert unless config.trailing_stop.enabled). These mirror the
    # live position_episodes table: opened_i is the episode's open date, peak_adj
    # the highest close since then, stop_peaks the peak that stopped a name (the
    # re-entry gate). Cleared when a position goes flat — a re-buy opens a NEW
    # episode with a fresh peak, exactly as live does.
    opened_i: dict[str, int] = {}               # ticker → session INDEX position opened
    peak_adj: dict[str, float] = {}             # ticker → highest close since opened_i
    stop_peaks: dict[str, float] = {}           # ticker → peak that triggered its stop
    n_stop_exits = 0
    filled_notional_today: float = 0.0
    n_rebalances = 0                            # rebalance EVALUATIONS
    n_rebalances_with_trades = 0
    status_counts: dict[str, int] = {}
    rank_history: dict[str, list] = {}          # ticker → [RankObservation] newest-first
    target_history: list[set] = []              # newest-first target membership
    raw_regimes: list[str] = []                 # newest-first
    confirmed_regime: str | None = None
    pending: list[dict] = []                    # trades decided at D, filling at D+1 open
    equity_rows, trade_rows, position_rows = [], [], []
    turnover_samples: list[float] = []
    spy_start = float(spy[spy["date"] == all_days[0]]["close"].iloc[0])

    # Per-day price lookup (adjusted) and adjusted-open factor.
    # _pivot uses DataFrame.pivot (a reshape) rather than pivot_table (which
    # runs a needless groupby-mean over 35M rows); (ticker, date) is the source
    # PK so duplicates can't occur, and it falls back if a caller's frame has
    # any. The adjusted-open column is built in a TEMPORARY frame instead of
    # being assigned onto px — assigning would both duplicate the whole frame
    # and mutate a caller's input (the sweep reuses one frame across configs).
    day_close = _pivot(px, "adjusted_close")
    if "open" in px.columns and px["open"].notna().any():
        adj_factor = px["adjusted_close"] / px["close"].replace(0, np.nan)
        tmp = pd.DataFrame({"date": px["date"], "ticker": px["ticker"],
                            "_adj_open": px["open"] * adj_factor})
        del adj_factor
        day_open = _pivot(tmp, "_adj_open")
        del tmp
    else:
        day_open = day_close   # no opens (synthetic data) → degrade to close fills
        caveats.append("no open prices — next_open fills degraded to close prices")

    def _price(ticker: str, d: pd.Timestamp, opens: bool) -> float | None:
        table = day_open if opens else day_close
        if ticker not in table.columns or d not in table.index:
            return None
        v = table.at[d, ticker]
        return float(v) if pd.notna(v) else None

    def _mtm(d: pd.Timestamp) -> float:
        total = cash
        for t, q in qty.items():
            p = _price(t, d, opens=False)
            if p is not None:
                last_px[t], last_seen_i[t] = p, day_index.get(d, last_seen_i.get(t, -1))
                if t in opened_i:
                    peak_adj[t] = max(peak_adj.get(t, p), p)
            total += q * (p if p is not None else last_px.get(t, 0.0))
        return total

    def _mark_close(d: pd.Timestamp) -> None:
        """Refresh marks + ratchet peaks from THIS session's close.

        _mtm does the same as a side effect, but it only runs on rebalance dates
        and at end-of-day. The trailing stop is checked EVERY session, before the
        rebalance gate, so the peak has to be current by then — otherwise on a
        rebalance_every=5 sweep the stop would compare today's close against a
        peak up to five sessions stale. Idempotent: same inputs, same values, so
        the later _mtm call is a no-op refresh and truncation invariance holds.
        """
        for t in qty:
            p = _price(t, d, opens=False)
            if p is None:
                continue
            last_px[t], last_seen_i[t] = p, day_index.get(d, last_seen_i.get(t, -1))
            if t in opened_i:
                peak_adj[t] = max(peak_adj.get(t, p), p)

    def _fill(trades: list[dict], d: pd.Timestamp, opens: bool):
        nonlocal cash, filled_notional_today
        # sells first (frees cash), then buys best-rank first, capped by cash
        for tr in sorted(trades, key=lambda x: 0 if x["side"] == "sell" else 1):
            p = _price(tr["ticker"], d, opens)
            if p is None or p <= 0:
                # NO PRINT, NO FILL. This used to fall back to last_px, which
                # executed trades against a security that had no market that day
                # (halt, delisting, vendor gap) — buying at a frozen, usually
                # lower price and exiting positions that could not be exited.
                # Not a conservative degradation: optimistic or pessimistic
                # depending on what happened after the last print.
                #
                # It also compounded with the stale-price fix below: a phantom
                # fill stamped last_seen, resetting the delisting countdown, so a
                # dead name could be kept alive indefinitely by fills at a frozen
                # price.
                #
                # Dropped, not queued: the next rebalance re-decides from current
                # state, which is what live does with an unfilled day order.
                unfilled.append({"date": d.date(), "ticker": tr["ticker"],
                                 "action": tr.get("action", tr["side"]),
                                 "qty": float(tr.get("qty") or 0.0),
                                 "reason": "no price on fill date (halt/delist/data gap)"})
                continue
            if tr["side"] == "sell":
                q = min(tr["qty"], qty.get(tr["ticker"], 0.0))
                if q <= 0:
                    continue
                cost = q * p * params.tx_cost_bps / 10_000.0
                cash += q * p - cost
                qty[tr["ticker"]] = qty.get(tr["ticker"], 0.0) - q
                if qty[tr["ticker"]] <= 1e-9:
                    qty.pop(tr["ticker"], None)
                    # Episode closed. A later re-buy opens a NEW one with a fresh
                    # peak — the stop measures the trend the CURRENT position has
                    # lived through, not a previous one. stop_peaks is deliberately
                    # NOT cleared here: it is what blocks re-entry until the close
                    # exceeds the peak that stopped the name.
                    opened_i.pop(tr["ticker"], None)
                    peak_adj.pop(tr["ticker"], None)
            else:
                q = tr["qty"]
                if tr.get("notional") is not None:   # size at the actual fill price
                    q = math.floor(tr["notional"] / p)
                afford = math.floor(cash / (p * (1 + params.tx_cost_bps / 10_000.0)))
                q = min(q, afford)
                if q < 1:
                    continue
                cost = q * p * params.tx_cost_bps / 10_000.0
                cash -= q * p + cost
                was_flat = qty.get(tr["ticker"], 0.0) <= 1e-9
                qty[tr["ticker"]] = qty.get(tr["ticker"], 0.0) + q
                if was_flat:
                    # Episode opens at the FILL date, and this fill price seeds the
                    # peak — matching live, where opened_on is the fill date and
                    # that session's close counts toward the peak. A buy_add into an
                    # existing position deliberately does NOT reset either: the peak
                    # belongs to the episode, not to the most recent purchase.
                    opened_i[tr["ticker"]] = day_index.get(d, 0)
                    peak_adj[tr["ticker"]] = p
                    stop_peaks.pop(tr["ticker"], None)  # re-entered ⇒ block cleared
            # A FILL IS PROOF OF A PRINT (and, since the no-price branch above
            # now refuses to fill, only a REAL print can reach here).
            # last_seen_i/last_px are otherwise refreshed
            # only by _mtm, which walks HELD tickers — so a name's timestamp froze
            # the moment it left the book. On re-entry weeks later that stale
            # timestamp tripped the delist sweep below, which instantly
            # liquidated the fresh position at the stale last_px. With an
            # upward-drifting series the stale price is LOWER, so every re-entry
            # booked an immediate loss: cost-independent, scaling with rebalance
            # frequency, and compounding to -92% on a book whose every holding
            # rose. (Reproduced with 7 tickers all trending UP.)
            last_px[tr["ticker"]] = p
            last_seen_i[tr["ticker"]] = day_index.get(d, last_seen_i.get(tr["ticker"], -1))
            # REALIZED notional — what actually traded, at the actual fill
            # price. Turnover used to be computed from decision-time intended
            # notional at last_px, before fills, so it could never reconcile with
            # the costs that hit equity.
            filled_notional_today += float(q) * float(p)
            trade_rows.append({"date": d.date(), "ticker": tr["ticker"],
                               "action": tr["action"], "qty": float(q), "price": p,
                               "tx_cost": round(q * p * params.tx_cost_bps / 10_000.0, 4),
                               "reason": tr.get("reason", "")[:300]})

    prev_equity = params.starting_capital
    win_days = cmp_days = 0
    prev_spy = spy_start
    peak = params.starting_capital

    # Score calibration: which rebalance indices to sample (their forward
    # window must fit inside the sim range — no partial horizons).
    calib_eligible = [j for j in range(0, len(all_days), max(1, params.rebalance_every))
                      if j + CALIB_HORIZON_SESSIONS < len(all_days)]
    # space_out first (independence), THEN thin evenly if still over the cap, so
    # a long run keeps anchors spread across its whole span rather than clustered.
    _spaced = [calib_eligible[k] for k in
               space_out(calib_eligible, CALIB_HORIZON_SESSIONS)]
    calib_idx = set(sample_evenly(_spaced, CALIB_MAX_DATES))
    calib_samples: list[tuple[int, dict[str, float], str | None]] = []

    ts_cfg = getattr(config, "trailing_stop", None)
    ts_on = bool(getattr(ts_cfg, "enabled", False))
    ts_scaled = ts_on and getattr(ts_cfg, "width_method", "fixed") == "vol_scaled"
    ts_vol_lb = int(getattr(ts_cfg, "vol_lookback", 120) or 120)

    for i, D in enumerate(all_days):
        # 1. fill pending next_open trades at today's open
        if pending:
            _fill(pending, D, opens=True)
            pending = []

        # 1b. TRAILING STOP — evaluated EVERY session, deliberately outside the
        # rebalance gate below. Live checks the stop on every chain run (daily);
        # if it rode the rebalance cadence instead, a sweep at rebalance_every=5
        # would check it a fifth as often and any swept stop_pct would carry that
        # latency baked in — the number would not transfer to production. Sells
        # queue into `pending` like every other decision, filling at D+1's open,
        # which mirrors live's decide-after-close / trade-at-next-open.
        stopped_today: set[str] = set()
        stop_trades: list[dict] = []
        if ts_on:
            _mark_close(D)   # peaks must be current before the check
            states = {
                t: live.StopState(
                    peak_close=peak_adj[t],
                    last_close=last_px[t],
                    sessions_held=i - opened_i[t],
                    sessions_since_close=i - last_seen_i.get(t, i),
                    # Realised vol over the trailing window ENDING AT TODAY — the
                    # slice is [i - lookback + 1 : i + 1], never past i, so
                    # truncation invariance holds. Computed only when the width is
                    # actually scaled by it. Uses the same helper as live, so the
                    # two cannot drift.
                    vol=(_realized_vol(
                        [v for v in day_close[t].iloc[max(0, i - ts_vol_lb + 1):i + 1]
                         if v == v],
                        lookback=ts_vol_lb)
                         if ts_scaled and t in day_close.columns else None),
                )
                for t in qty
                if t in opened_i and t in peak_adj and t in last_px
            }
            plan = live.plan_trailing_stops(
                states, enabled=True, stop_pct=ts_cfg.stop_pct,
                arm_after_sessions=ts_cfg.arm_after_sessions,
                max_stale_sessions=ts_cfg.max_stale_sessions,
                max_stops_per_run=ts_cfg.max_stops_per_run,
                width_method=getattr(ts_cfg, "width_method", "fixed"),
                vol_anchor=getattr(ts_cfg, "vol_anchor", 0.35),
                stop_pct_min=getattr(ts_cfg, "stop_pct_min", 0.08),
                stop_pct_max=getattr(ts_cfg, "stop_pct_max", 0.35))
            for t, peak in plan.stopped.items():
                stopped_today.add(t)
                stop_peaks[t] = peak
                stop_trades.append({
                    "ticker": t, "side": "sell", "qty": qty[t], "action": "exit",
                    "reason": f"trailing stop: close {last_px[t]:.2f} is "
                              f"{(last_px[t] / peak - 1) * 100:.1f}% below peak {peak:.2f}",
                })
            n_stop_exits += len(stop_trades)

        # Names whose stop peak has not been recovered. Computed HERE, before the
        # rebalance gate, so it can reach the builder's candidate pool — the
        # builder must not be able to select a name the stop would then have to
        # remove, because removing it after composition shrinks the book and
        # strands its weight in cash.
        blocked: set[str] = set()
        if ts_on and stop_peaks:
            blocked = {t for t, pk in stop_peaks.items()
                       if t not in qty
                       and live.reentry_blocked(_price(t, D, opens=False), pk)}

        rebalance = (i % max(1, params.rebalance_every)) == 0
        if rebalance:
            window_start = D - pd.Timedelta(days=FACTOR_LOOKBACK_DAYS)
            day_prices = px[(px["date"] <= D) & (px["date"] >= window_start)][
                ["ticker", "date", "close", "adjusted_close", "volume"]
                if "volume" in px.columns else ["ticker", "date", "adjusted_close"]].copy()
            spy_upto = spy[spy["date"] <= D]
            try:
                raw = live.detect_regime(
                    spy_upto.rename(columns={"close": "adjusted_close"}), rd_cfg)["raw_regime"]
            except Exception:
                raw = next(iter(rd_cfg.regimes))
            confirmed_regime = live.resolve_confirmed_regime(
                raw, raw_regimes, confirmed_regime, rd_cfg.confirmation_days)
            raw_regimes.insert(0, raw)
            del raw_regimes[10:]

            fnd_asof = pd.DataFrame(columns=["ticker", "pe_ratio", "pb_ratio", "roe",
                                             "debt_to_equity", "revenue_growth", "eps_growth"])
            if not fnd.empty:
                cut = fnd[fnd["as_of_date"] <= D]
                if not cut.empty:
                    fnd_asof = cut.groupby("ticker").last().reset_index().drop(
                        columns=["as_of_date"], errors="ignore")

            spy_closes = spy_upto["close"].astype(float).tolist()
            n_rebalances += 1
            target, ranked, target_status = build_target(
                day_prices[day_prices["ticker"] != "SPY"], fnd_asof, sector_map,
                config, confirmed_regime, fk, spy_closes,
                factor_cache=factor_cache, factor_key=factor_key,
                coverage_observer=coverage,
                current_holdings=set(qty),
                listing_windows=listing_windows,
                earnings=earnings,
                blocked_tickers=blocked)
            status_counts[target_status] = status_counts.get(target_status, 0) + 1

            if ranked is not None:
                obs_date = D.date()
                # rank_history stays scoped to the investable head (unchanged
                # delta-engine input); the FULL ranked frame feeds calibration.
                for r in ranked.head(config.portfolio_builder.candidate_count).itertuples():
                    rank_history.setdefault(r.ticker, []).insert(
                        0, live.RankObservation(run_date=obs_date, rank=int(r.rank),
                                                composite_score=float(r.composite_score)))
                for t in rank_history:
                    del rank_history[t][8:]
                if i in calib_idx:
                    calib_samples.append((i, dict(zip(
                        ranked["ticker"], ranked["composite_score"].astype(float))),
                        confirmed_regime))

            # Act on the STATUS, not on dict truthiness. DEGRADED/FAILED hold the
            # book (a partial build must never mass-liquidate); an empty target
            # that came back SUCCESS is a deliberate risk-off instruction and is
            # obeyed — the delta engine will exit into cash.
            if target_status not in TargetStatus.HOLD:
                target_history.insert(0, set(target))
                del target_history[10:]
                equity_now = _mtm(D)
                actual_w = {t: (qty.get(t, 0.0) * (last_px.get(t) or 0.0)) / equity_now
                            for t in qty} if equity_now > 0 else {}
                delta_cfg = config.delta_engine
                # Re-entry-blocked names never reached the candidate pool (see
                # build_target), so the target is already backfilled around them.
                # Only names stopped THIS session still need removing: the target
                # above was composed before the stop was known, so it can contain
                # a name that is being sold at D+1's open. Stripping it from the
                # target as well as from live_positions is required — leaving it
                # in the target with the position gone makes Loop 1 read an
                # in-target un-held ticker as an ENTRY and buy back the very name
                # the stop just sold, at the same open.
                #
                # This one name is NOT backfilled, and that is correct: the build
                # had no way to know. The next build fills the slot properly, so
                # the gap is one cycle and self-correcting — unlike the blocked
                # set, which persists for as long as the block does and therefore
                # must be handled at the pool.
                if stopped_today:
                    target = {k: v for k, v in target.items() if k not in stopped_today}
                decisions = live.evaluate_target_vs_live(
                    target_portfolio=target,
                    live_positions=set(qty) - stopped_today,
                    inflight_exits=stopped_today or None,
                    universe=rank_history,
                    confirmation_days=delta_cfg.confirmation_days,
                    max_positions=config.portfolio_builder.max_positions,
                    actual_weights=actual_w,
                    drift_threshold=delta_cfg.rebalance_drift_threshold,
                    min_relative_drift=getattr(delta_cfg, "rebalance_min_relative_drift", 0.0),
                    min_trade_value=getattr(delta_cfg, "rebalance_min_trade_value", 0.0),
                    account_value=equity_now,
                    target_history=target_history,
                    orphan_confirmation_days=delta_cfg.orphan_confirmation_days,
                    cash_fraction=cash / equity_now if equity_now > 0 else None,
                    # Same two primitives live passes, from the same config, so a
                    # stop-only candidate is scored on the policy it declares.
                    suppress_target_exits=(
                        getattr(delta_cfg, "exit_policy", "target_diff")
                        == "trailing_stop_only"),
                    drift_rebalance=bool(
                        getattr(delta_cfg, "drift_rebalance_enabled", True)),
                )
                trades: list[dict] = []
                for dcs in sorted(decisions.values(), key=lambda x: x.rank):
                    if dcs.action == "exit":
                        trades.append({"ticker": dcs.ticker, "side": "sell",
                                       "qty": qty.get(dcs.ticker, 0.0),
                                       "action": "exit", "reason": dcs.reason})
                    elif dcs.action == "entry":
                        trades.append({"ticker": dcs.ticker, "side": "buy", "qty": 0,
                                       "notional": (dcs.current_weight or 0.0) * equity_now,
                                       "action": "entry", "reason": dcs.reason})
                    elif dcs.action in ("buy_add", "sell_trim"):
                        tgt_n = (dcs.current_weight or 0.0) * equity_now
                        cur_n = qty.get(dcs.ticker, 0.0) * (last_px.get(dcs.ticker) or 0.0)
                        diff = tgt_n - cur_n
                        if dcs.action == "buy_add" and diff > 0:
                            trades.append({"ticker": dcs.ticker, "side": "buy", "qty": 0,
                                           "notional": diff, "action": "buy_add",
                                           "reason": dcs.reason})
                        elif dcs.action == "sell_trim" and diff < 0:
                            # NO $1 PLACEHOLDER. qty = floor(-diff / p), so a
                            # fallback price of 1.0 turns a dollar drift into a
                            # share count ~100x too large; _fill then caps it at
                            # the held quantity, silently converting a TRIM into
                            # a FULL LIQUIDATION. Same class as the delist bug
                            # fixed above: a placeholder default that quietly
                            # changes what the trade means. No known price ⇒ no
                            # trade (the name is marked at last_px anyway).
                            p = last_px.get(dcs.ticker)
                            if not p or p <= 0:
                                continue
                            trades.append({"ticker": dcs.ticker, "side": "sell",
                                           "qty": math.floor(-diff / p),
                                           "action": "sell_trim", "reason": dcs.reason})
                if trades:
                    n_rebalances_with_trades += 1
                # Turnover is NOT recorded here. It used to be summed from
                # decision-time intended notional at last_px — before fills, and
                # therefore unable to reconcile with the costs that actually hit
                # equity, or with orders that never filled at all. It is now
                # accumulated inside _fill from REALIZED notional and sampled
                # against realized equity below.
                # Stop sells lead: they free cash for whatever the rebalance buys,
                # and _fill sorts sells first anyway.
                trades = stop_trades + trades
                stop_trades = []
                if params.fill_timing == "close":
                    _fill(trades, D, opens=False)
                else:
                    pending = trades

        # 1c. Stop sells still have to trade on a session the rebalance block did
        # not run — a non-rebalance day, or a DEGRADED/FAILED build that held the
        # book. That is the normal case at rebalance_every>1 and the whole point
        # of checking the stop daily; dropping them here would silently restore
        # the rebalance cadence.
        if stop_trades:
            if params.fill_timing == "close":
                _fill(stop_trades, D, opens=False)
            else:
                pending = pending + stop_trades

        # 2. delist sweep: held names with no print for DELIST_GAP_DAYS trading days
        for t in list(qty):
            if t in last_seen_i and (i - last_seen_i[t]) > DELIST_GAP_DAYS:
                # Never book a delist exit at a ZERO price: `.get(t, 0.0)` would
                # hand the whole position to the void and call it a sale. A held
                # name always has a last_px (every fill stamps one), so a missing
                # price means something is wrong — hold and let the next sweep
                # retry rather than silently destroying the position.
                p = last_px.get(t)
                if not p or p <= 0:
                    continue
                # RECOVERY HAIRCUT. Booking the full last mark assumed a company
                # that stops printing at $2 is worth $2 — which flatters exactly
                # the speculative/distressed strategies most likely to be
                # proposed. Transaction cost applies too; it used to be written
                # as a literal 0.0.
                recovery = max(0.0, float(params.delist_recovery_pct))
                px_eff = p * recovery
                gross = qty[t] * px_eff
                cost = gross * params.tx_cost_bps / 10_000.0
                cash += gross - cost
                filled_notional_today += gross
                trade_rows.append({"date": D.date(), "ticker": t, "action": "exit",
                                   "qty": qty[t], "price": px_eff,
                                   "tx_cost": round(cost, 4),
                                   "reason": (f"delisted — exited at {recovery:.0%} of last "
                                              f"available price ({p:.4f})")})
                qty.pop(t)
                # Episode closed by delisting, not by a stop — so no stop_peaks
                # entry and no re-entry block. Leaving opened_i/peak_adj behind
                # would carry a dead peak into a later re-listing.
                opened_i.pop(t, None)
                peak_adj.pop(t, None)

        # 3. mark to market
        equity = _mtm(D)
        # Realized turnover for the day: what actually traded, over what the book
        # was actually worth. /2 keeps the one-sided convention (a buy funded by
        # a sell is one unit of turnover, not two).
        if filled_notional_today > 0 and equity > 0:
            turnover_samples.append(filled_notional_today / equity / 2)
        filled_notional_today = 0.0
        spy_now = float(spy[spy["date"] == D]["close"].iloc[0])
        spy_val = params.starting_capital * spy_now / spy_start
        peak = max(peak, equity)
        equity_rows.append({"date": D.date(), "portfolio_value": round(equity, 2),
                            "spy_value": round(spy_val, 2),
                            "drawdown": round(equity / peak - 1.0, 6)})
        if i > 0:
            port_r = equity / prev_equity - 1.0
            spy_r = spy_now / prev_spy - 1.0
            cmp_days += 1
            if port_r > spy_r:
                win_days += 1
        prev_equity, prev_spy = equity, spy_now

        if rebalance:
            for t, q in qty.items():
                mv = q * (last_px.get(t) or 0.0)
                position_rows.append({"date": D.date(), "ticker": t, "qty": q,
                                      "weight": round(mv / equity, 6) if equity > 0 else 0.0,
                                      "market_value": round(mv, 2)})
        if progress_cb and (i % 5 == 0 or i == len(all_days) - 1):
            # Interim stats so a long run is INFORMATIVE while it runs, not just
            # a percentage: return so far, annualised, drawdown, trade count and
            # how the benchmark is doing over the same elapsed span.
            elapsed_days = (D - all_days[0]).days or 1
            tot = equity / params.starting_capital - 1.0
            ann = ((1.0 + tot) ** (365.25 / elapsed_days) - 1.0) if tot > -1 else -1.0
            progress_cb(i + 1, len(all_days), {
                "as_of": str(D.date()),
                "equity": round(equity, 2),
                "total_return": round(tot, 6),
                "annualized_return": round(ann, 6),
                "max_drawdown": round(min((r["drawdown"] for r in equity_rows),
                                          default=0.0), 4),
                "benchmark_total_return": round(spy_val / params.starting_capital - 1.0, 6),
                "n_trades": len(trade_rows),
                "n_positions": len(qty),
            })

    # ── summary ──────────────────────────────────────────────────────────────
    total_return = equity_rows[-1]["portfolio_value"] / params.starting_capital - 1.0
    n_days = (all_days[-1] - all_days[0]).days or 1
    ann = (1.0 + total_return) ** (365.25 / n_days) - 1.0 if total_return > -1 else -1.0
    spy_total = equity_rows[-1]["spy_value"] / params.starting_capital - 1.0
    spy_ann = (1.0 + spy_total) ** (365.25 / n_days) - 1.0 if spy_total > -1 else -1.0
    daily = pd.Series([r["portfolio_value"] for r in equity_rows]).pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * math.sqrt(252)) if len(daily) > 1 and daily.std() > 0 else 0.0
    max_dd = min((r["drawdown"] for r in equity_rows), default=0.0)
    summary = {
        "total_return": round(total_return, 6),
        "annualized_return": round(ann, 6),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "benchmark_total_return": round(spy_total, 6),
        "alpha": round(ann - spy_ann, 6),
        # avg_turnover keeps its NAME (bt_runs column, evaluator queries) but now
        # means realized turnover per rebalance EVALUATION — zero-turnover cycles
        # included. Existing readers get a better number under the same key.
        "avg_turnover": (round(float(np.sum(turnover_samples)) / n_rebalances, 4)
                         if n_rebalances else 0.0),
        "avg_turnover_per_fill_day": (round(float(np.mean(turnover_samples)), 4)
                                      if turnover_samples else 0.0),
        "win_rate": round(win_days / cmp_days, 4) if cmp_days else 0.0,
        "n_trading_days": len(all_days),
        # These used to be one number: turnover_samples doubled as the turnover
        # series AND the rebalance counter, and was appended only when trades
        # existed — so "n_rebalances" silently meant "rebalance dates that
        # produced trades".
        "n_rebalances": n_rebalances,                       # evaluations
        "n_rebalances_with_trades": n_rebalances_with_trades,
        "n_days_with_fills": len(turnover_samples),
        "total_turnover": round(float(np.sum(turnover_samples)), 4) if turnover_samples else 0.0,
        "target_status_counts": dict(sorted(status_counts.items())),
        # Stop exits vs everything else. The whole premise of the trailing stop is
        # that it replaces rank-driven exits with trend-driven ones, so a run where
        # this is 0 scored a config whose stop never fired — the A/B is meaningless
        # without knowing which.
        "trailing_stop_enabled": ts_on,
        "n_stop_exits": n_stop_exits,
        "unfilled_orders": len(unfilled),
        # A sample, not the whole list: a long run with a systemic data gap could
        # otherwise put thousands of rows into a summary JSON blob.
        "unfilled_sample": unfilled[:20],
        "delist_recovery_pct": float(params.delist_recovery_pct),
        # Terminal-wealth distribution (docs/architecture.md "terminal wealth").
        # CAGR and one realised max_drawdown describe the single path history
        # happened to take; the objective is compounded WEALTH, whose enemy is
        # the drawdown arithmetic cannot recover from. Resampling the realised
        # returns in circular blocks gives the spread — the 5th percentile is
        # that left tail in the only unit that matters. Paired with the SPY leg
        # so prob_beat_benchmark preserves co-movement. None when the window is
        # too short to say anything honest.
        "terminal_wealth": bootstrap_terminal_wealth(
            daily_returns(equity_rows),
            starting_capital=params.starting_capital,
            benchmark_returns=daily_returns(equity_rows, value_key="spy_value"),
        ),
        "n_trades": len(trade_rows),
        "fill_timing": params.fill_timing,
        "tx_cost_bps": params.tx_cost_bps,
    }
    # Score calibration (closed-loop item 3): decile-of-score → mean forward
    # return over the sampled rebalance dates. null when the range is too short
    # for a single full horizon or too few names were scored.
    calib_rows, calib_regimes = [], []
    for j, scores, creg in calib_samples:
        d0, d1 = all_days[j], all_days[j + CALIB_HORIZON_SESSIONS]
        calib_rows.append(decile_forward_returns(
            scores,
            lambda t, _d=d0: _price(t, _d, opens=False),
            lambda t, _d=d1: _price(t, _d, opens=False)))
        calib_regimes.append(creg)
    summary["score_calibration"] = aggregate_calibration(
        calib_rows, CALIB_HORIZON_SESSIONS, regimes=calib_regimes)

    # Empirical coverage backstop. The static gate in main.py runs on a DECLARED
    # capability list that could go stale, and a corpus can lose a column the
    # declaration honestly believes is populated. Raising here (rather than
    # returning a caveat) is deliberate: the run's numbers describe a config
    # nobody asked for, so an error row is the honest result. run_config_both_windows
    # turns this into a per-config error row; _run_bg marks a single run failed.
    cov = coverage.violations()
    if cov and coverage_enforcement_enabled():
        raise CoverageError("factor coverage: " + " ".join(cov))
    caveats.extend(cov)
    return SimResult(summary=summary, equity=equity_rows, trades=trade_rows,
                     positions=position_rows, caveats=caveats)
