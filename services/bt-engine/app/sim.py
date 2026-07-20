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
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from stock_strategy_shared.drawdown import (
    excess_drawdown, recent_drawdown, falling_knife_verdict)
from stock_strategy_shared.investability import (
    DOLLAR_VOLUME_WINDOW,
    avg_dollar_volume,
    below_investability_floor,
)
from stock_strategy_shared.schemas.strategy import StrategyConfig

from app import live

# Env-default falling-knife thresholds (mirror the vetter's DRAWDOWN_* defaults);
# a config's vetter.falling_knife overrides field-by-field, exactly like live.
_FK_DEFAULTS = dict(backstop_pct=0.25, window_days=21, excess_pct=0.15,
                    beta_lookback=120, vol_scaling=True, vol_anchor=0.35,
                    excess_min=0.10, excess_max=0.30)

# Trailing price history handed to the factor step per rebalance (calendar days).
# Momentum 12-1 needs ~370; covariance/regime ≤ 252 trading days. 420 covers all.
FACTOR_LOOKBACK_DAYS = 420
# A held name with no price for this many TRADING days is treated as delisted and
# force-exited at its last available adjusted close.
DELIST_GAP_DAYS = 7


@dataclass
class SimParams:
    start: date
    end: date
    tx_cost_bps: int = 10
    fill_timing: str = "next_open"          # 'next_open' | 'close'
    starting_capital: float = 100_000.0
    rebalance_every: int = 1                # trading days between rebalances (1 = live-faithful)
    drawdown_backstop_pct: float | None = None   # optional override of config/env default


@dataclass
class SimResult:
    summary: dict
    equity: list = field(default_factory=list)      # [{date, portfolio_value, spy_value, drawdown}]
    trades: list = field(default_factory=list)      # [{date, ticker, action, qty, price, tx_cost, reason}]
    positions: list = field(default_factory=list)   # EOD on rebalance days [{date, ticker, qty, weight, market_value}]
    caveats: list = field(default_factory=list)


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
                 fk: dict, spy_closes: list[float]) -> dict[str, float]:
    """One rebalance: factors → rank → falling-knife → builder composition.
    Returns ({ticker: weight}, ranked_df) — weights sum ≤ 1 (cash_reserve /
    vol-target de-lever); ({}, None|df) when no feasible target.
    Faithful to portfolio-builder _do_build ordering (cluster on the full pool,
    exclusions dropped from the selectable pool AFTER clustering)."""
    pb = config.portfolio_builder
    fdf = live.compute_all_factors(
        day_prices, fundamentals_asof, cfg=config.factor_engine,
        copy_input=True, sector_map=sector_map,
        as_of_date=day_prices["date"].max().date(),
    )
    ranked = live.rank_universe(fdf, regime, config)
    if ranked.empty:
        return {}, None
    ranked = ranked.head(pb.candidate_count)
    candidates = ranked["ticker"].tolist()
    scores_map = dict(zip(ranked["ticker"], ranked["composite_score"].astype(float)))

    dnb = {t.upper() for t in (pb.do_not_buy or [])}
    candidates = [t for t in candidates if t.upper() not in dnb]

    sub = day_prices[day_prices["ticker"].isin(candidates)].sort_values("date")
    latest_px = sub.groupby("ticker")["adjusted_close"].last().to_dict()
    avg_dv: dict[str, float] = {}
    if "close" in sub.columns and "volume" in sub.columns:
        for t, g in sub.groupby("ticker"):
            dv = avg_dollar_volume(g["close"].tolist(), g["volume"].tolist(),
                                   window=DOLLAR_VOLUME_WINDOW)
            if dv is not None:
                avg_dv[t] = dv
    candidates = [t for t in candidates if t in latest_px and not below_investability_floor(
        latest_px.get(t), avg_dv.get(t),
        min_price=config.universe.min_price,
        min_avg_dollar_volume=config.universe.min_avg_dollar_volume_20d)]
    if len(candidates) < 2:
        return {}, None

    # Falling-knife veto at selection (plan decision #1): computed from prices ≤ D.
    closes_by_ticker = {t: g["adjusted_close"].astype(float).tolist()
                        for t, g in sub[sub["ticker"].isin(candidates)]
                        .sort_values("date").groupby("ticker")}
    vetoed = falling_knife_excluded(closes_by_ticker, spy_closes, fk)

    cov, _dropped, raw_corr = live.build_covariance(
        day_prices[day_prices["ticker"].isin(candidates)],
        window_days=pb.covariance_window_days,
        min_observations=pb.min_covariance_observations,
        shrinkage=pb.covariance_shrinkage)
    if cov is None or len(cov) < 2:
        return {}, None
    available = [t for t in candidates if t in cov.index]
    cluster_map = live.correlation_clusters(raw_corr, threshold=pb.cluster_correlation_threshold)

    # Exclusions after clustering, exactly like the builder.
    available = [t for t in available if t not in vetoed]
    if pb.require_positive_composite_score:
        available = [t for t in available if scores_map[t] >= 0]
    if len(available) < 2:
        return {}, None
    scores = pd.Series({t: scores_map[t] for t in available})
    cov = cov.loc[available, available]

    selected = live.greedy_select(
        scores, cov, target=pb.max_positions,
        sector_map=cluster_map, max_sector_weight=pb.max_cluster_weight,
        max_tickers_per_sector=pb.max_tickers_per_cluster,
        av_sector_map=sector_map, max_av_sector_weight=pb.max_sector_weight,
        selection_vol_aversion=pb.selection_vol_aversion)
    if not selected:
        return {}, ranked
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
    return {t: float(w) for t, w in weights.items()}, ranked


def run_simulation(prices: pd.DataFrame, fundamentals: pd.DataFrame,
                   sector_map: dict[str, str], config: StrategyConfig,
                   params: SimParams, progress_cb=None) -> SimResult:
    """prices: long [ticker, date, open, close, adjusted_close, volume] covering
    [start − FACTOR_LOOKBACK_DAYS, end] incl. SPY. fundamentals: long
    [ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity, revenue_growth,
    eps_growth] with as_of_date = point-in-time known date."""
    caveats = [
        "bt_fundamentals carries PE/PB/ROE/D-E/growth only — issuance/small_cap/"
        "volume_surge inputs absent → those factors are null and renormalized out",
        "sector labels are the latest bt_universe snapshot (static, not per-date)",
    ]
    px = prices.copy()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["ticker", "date"])
    px["adjusted_close"] = px["adjusted_close"].astype(float)

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

    fk = _fk_params(config, params.drawdown_backstop_pct)
    rd_cfg = config.regime_detection

    # ── state ────────────────────────────────────────────────────────────────
    cash = float(params.starting_capital)
    qty: dict[str, float] = {}
    last_px: dict[str, float] = {}
    last_seen: dict[str, pd.Timestamp] = {}
    rank_history: dict[str, list] = {}          # ticker → [RankObservation] newest-first
    target_history: list[set] = []              # newest-first target membership
    raw_regimes: list[str] = []                 # newest-first
    confirmed_regime: str | None = None
    pending: list[dict] = []                    # trades decided at D, filling at D+1 open
    equity_rows, trade_rows, position_rows = [], [], []
    turnover_samples: list[float] = []
    spy_start = float(spy[spy["date"] == all_days[0]]["close"].iloc[0])

    # Per-day price lookup (adjusted) and adjusted-open factor.
    day_close = px.pivot_table(index="date", columns="ticker", values="adjusted_close")
    if "open" in px.columns and px["open"].notna().any():
        adj_factor = (px["adjusted_close"] / px["close"].replace(0, np.nan)).astype(float)
        px = px.assign(_adj_open=px["open"].astype(float) * adj_factor)
        day_open = px.pivot_table(index="date", columns="ticker", values="_adj_open")
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
                last_px[t], last_seen[t] = p, d
            total += q * (p if p is not None else last_px.get(t, 0.0))
        return total

    def _fill(trades: list[dict], d: pd.Timestamp, opens: bool):
        nonlocal cash
        # sells first (frees cash), then buys best-rank first, capped by cash
        for tr in sorted(trades, key=lambda x: 0 if x["side"] == "sell" else 1):
            p = _price(tr["ticker"], d, opens)
            if p is None or p <= 0:
                p = last_px.get(tr["ticker"])
                if p is None:
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
                qty[tr["ticker"]] = qty.get(tr["ticker"], 0.0) + q
            trade_rows.append({"date": d.date(), "ticker": tr["ticker"],
                               "action": tr["action"], "qty": float(q), "price": p,
                               "tx_cost": round(q * p * params.tx_cost_bps / 10_000.0, 4),
                               "reason": tr.get("reason", "")[:300]})

    prev_equity = params.starting_capital
    win_days = cmp_days = 0
    prev_spy = spy_start
    peak = params.starting_capital

    for i, D in enumerate(all_days):
        # 1. fill pending next_open trades at today's open
        if pending:
            _fill(pending, D, opens=True)
            pending = []

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
            target, ranked = build_target(
                day_prices[day_prices["ticker"] != "SPY"], fnd_asof, sector_map,
                config, confirmed_regime, fk, spy_closes)

            if ranked is not None:
                obs_date = D.date()
                for r in ranked.itertuples():
                    rank_history.setdefault(r.ticker, []).insert(
                        0, live.RankObservation(run_date=obs_date, rank=int(r.rank),
                                                composite_score=float(r.composite_score)))
                for t in rank_history:
                    del rank_history[t][8:]

            if target:      # empty target = degraded build → hold (mirrors live)
                target_history.insert(0, set(target))
                del target_history[10:]
                equity_now = _mtm(D)
                actual_w = {t: (qty.get(t, 0.0) * (last_px.get(t) or 0.0)) / equity_now
                            for t in qty} if equity_now > 0 else {}
                delta_cfg = config.delta_engine
                decisions = live.evaluate_target_vs_live(
                    target_portfolio=target,
                    live_positions=set(qty),
                    universe=rank_history,
                    confirmation_days=delta_cfg.confirmation_days,
                    max_positions=config.portfolio_builder.max_positions,
                    actual_weights=actual_w,
                    drift_threshold=delta_cfg.rebalance_drift_threshold,
                    account_value=equity_now,
                    target_history=target_history,
                    orphan_confirmation_days=delta_cfg.orphan_confirmation_days,
                    cash_fraction=cash / equity_now if equity_now > 0 else None,
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
                            p = last_px.get(dcs.ticker) or 1.0
                            trades.append({"ticker": dcs.ticker, "side": "sell",
                                           "qty": math.floor(-diff / p),
                                           "action": "sell_trim", "reason": dcs.reason})
                if trades:
                    notional = sum((t.get("notional") or t["qty"] * (last_px.get(t["ticker"]) or 0.0))
                                   for t in trades)
                    turnover_samples.append(notional / equity_now / 2 if equity_now > 0 else 0.0)
                if params.fill_timing == "close":
                    _fill(trades, D, opens=False)
                else:
                    pending = trades

        # 2. delist sweep: held names with no print for DELIST_GAP_DAYS trading days
        for t in list(qty):
            if t in last_seen and (D - last_seen[t]).days > DELIST_GAP_DAYS * 2:
                p = last_px.get(t, 0.0)
                cash += qty[t] * p
                trade_rows.append({"date": D.date(), "ticker": t, "action": "exit",
                                   "qty": qty[t], "price": p, "tx_cost": 0.0,
                                   "reason": "delisted — exited at last available price"})
                qty.pop(t)

        # 3. mark to market
        equity = _mtm(D)
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
            progress_cb(i + 1, len(all_days))

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
        "avg_turnover": round(float(np.mean(turnover_samples)), 4) if turnover_samples else 0.0,
        "win_rate": round(win_days / cmp_days, 4) if cmp_days else 0.0,
        "n_trading_days": len(all_days),
        "n_rebalances": len(turnover_samples),
        "n_trades": len(trade_rows),
        "fill_timing": params.fill_timing,
        "tx_cost_bps": params.tx_cost_bps,
    }
    return SimResult(summary=summary, equity=equity_rows, trades=trade_rows,
                     positions=position_rows, caveats=caveats)
