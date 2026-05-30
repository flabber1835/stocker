#!/usr/bin/env python3
"""365-day A/B simulation — current exits vs +5% trailing-stop exits.

Two runs share an identical, deterministic synthetic price/ranking path over a
large ticker universe; the ONLY difference is that variant B arms a 5% trailing
stop on every buy (using the exact pure logic the alpaca simulator uses). This
isolates the effect of the trailing-stop exit overlay on portfolio value while
reusing the system's real decision code:

    regime detection    → services/pipeline/app/regime.detect_regime
    cross-section z      → services/pipeline/app/factors.cross_section_zscore
    composite ranking   → services/pipeline/app/rank.rank_universe
    buffer-zone delta    → services/pipeline/app/engine.evaluate_target_vs_live
    trailing-stop logic  → services/alpaca-sim/app/trailing (single source of truth)

Synthetic world (seeded, reproducible via SIM_SEED):
  - ~600 tickers across 11 sectors, betas ~N(1,0.3)
  - SPY drives a 3-regime year: bull_calm → bear_stress → bull_calm (recovery),
    labelled by the REAL detect_regime (200-SMA trend × 20-day vol)
  - 6 slow mean-reverting latent factors per ticker; expected return loads on the
    regime-appropriate factor weights (so rank genuinely predicts return), plus
    market beta, idiosyncratic noise (low-vol factor lowers it), and occasional
    idiosyncratic crashes/pops (more crashes in the bear regime) — the events
    where a trailing stop actually bites.

Portfolio construction here is the documented adj_score_proportional weighting of
the top `max_positions` names with a 30% sector cap (the per-day covariance build
of greedy_score_per_port_vol is skipped for speed over 365×2 iterations).

Run:
    python tests/simulation/trailing_stop_ab_sim.py                 # single seed + chart
    SIM_SEEDS=1,2,3,4,5,6,7,8 python tests/simulation/trailing_stop_ab_sim.py   # aggregate
    SIM_SEED=42 TRAIL_PCT=5 python tests/simulation/trailing_stop_ab_sim.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "pipeline"))

from app.engine import RankObservation, evaluate_target_vs_live  # noqa: E402
from app.factors import cross_section_zscore  # noqa: E402
from app.rank import FACTORS, rank_universe  # noqa: E402
from app.regime import detect_regime  # noqa: E402
from stock_strategy_shared.loader import load_strategy  # noqa: E402

# Load trailing.py standalone — alpaca-sim's `app` package name collides with
# pipeline's, so import the file directly to keep a single source of truth.
_TS_PATH = os.path.join(ROOT, "services", "alpaca-sim", "app", "trailing.py")
_spec = importlib.util.spec_from_file_location("sim_trailing", _TS_PATH)
sim_trailing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim_trailing)
arm = sim_trailing.arm


# ── Parameters ─────────────────────────────────────────────────────────────────

SEED = int(os.getenv("SIM_SEED", "7"))
TRAIL_PCT = float(os.getenv("TRAIL_PCT", "5.0"))
N_TICKERS = int(os.getenv("SIM_TICKERS", "600"))
N_SECTORS = 11
WARMUP = 220          # trading days before the sim window (>= 200-day SMA)
SIM_DAYS = 365        # the "365-day simulation" window
START_CASH = 1_000_000.0
ALPHA_SCALE = 0.0009  # daily expected return per unit of composite factor signal


# ── Synthetic market generation ────────────────────────────────────────────────

@dataclass
class Market:
    tickers: list
    sectors: dict           # ticker -> sector label
    prices: np.ndarray      # (total_days, n_tickers) price levels
    factors: np.ndarray     # (total_days, n_tickers, 6) latent factor z-levels
    spy: np.ndarray         # (total_days,) SPY level
    dates: list             # python dates, length total_days


def _regime_schedule(total, warmup, sim_days):
    """Per-day market (drift, daily_vol) so the REAL detect_regime labels the
    intended bull_calm → bear_stress → bull_calm arc."""
    drift = np.empty(total)
    vol = np.empty(total)
    drift[:warmup] = 0.0005
    vol[:warmup] = 0.008
    e1 = warmup + int(sim_days * 0.42)   # end of bull era 1
    e2 = warmup + int(sim_days * 0.66)   # end of bear era 2
    drift[warmup:e1] = 0.0006; vol[warmup:e1] = 0.008      # bull_calm
    drift[e1:e2] = -0.0018;    vol[e1:e2] = 0.0225         # bear_stress
    drift[e2:] = 0.0013;       vol[e2:] = 0.0105           # recovery bull
    return drift, vol


def generate_market(seed) -> Market:
    rng = np.random.default_rng(seed)
    total = WARMUP + SIM_DAYS
    tickers = [f"SYN{i:04d}" for i in range(N_TICKERS)]
    sector_labels = [f"SEC{j:02d}" for j in range(N_SECTORS)]
    sec_idx = rng.integers(0, N_SECTORS, N_TICKERS)
    sectors = {tickers[i]: sector_labels[sec_idx[i]] for i in range(N_TICKERS)}

    betas = np.clip(rng.normal(1.0, 0.30, N_TICKERS), 0.2, 2.2)

    mdrift, mvol = _regime_schedule(total, WARMUP, SIM_DAYS)
    spy_ret = rng.normal(mdrift, mvol)
    spy = 100.0 * np.cumprod(1.0 + spy_ret)

    # Latent factors: slow mean-reverting (OU), cross-sectionally ~N(0,1).
    F = 6
    fac = np.empty((total, N_TICKERS, F))
    fac[0] = rng.normal(0, 1, (N_TICKERS, F))
    phi = 0.985
    shock = np.sqrt(1 - phi**2)
    for t in range(1, total):
        fac[t] = phi * fac[t - 1] + shock * rng.normal(0, 1, (N_TICKERS, F))
    lowvol_i = FACTORS.index("low_volatility")

    strategy, _ = load_strategy(os.path.join(ROOT, "strategies", "quality_core_v1.yaml"))
    e1 = WARMUP + int(SIM_DAYS * 0.42)
    e2 = WARMUP + int(SIM_DAYS * 0.66)

    def wvec(regime):
        w = strategy.factor_weights[regime].model_dump()
        return np.array([w[f] for f in FACTORS])

    wv = np.empty((total, F))
    wv[:e1] = wvec("bull_calm")
    wv[e1:e2] = wvec("bear_stress")
    wv[e2:] = wvec("bull_calm")

    prices = np.empty((total, N_TICKERS))
    prices[0] = rng.uniform(20, 400, N_TICKERS)
    crash_p = np.full(total, 0.0012)
    crash_p[e1:e2] = 0.0040      # elevated idiosyncratic crash rate in the bear era
    pop_p = 0.0010

    for t in range(1, total):
        comp = (fac[t] * wv[t]).sum(axis=1)              # composite factor signal
        idio_vol = np.clip(0.018 * np.exp(-0.30 * fac[t, :, lowvol_i]), 0.006, 0.060)
        r = betas * spy_ret[t] + ALPHA_SCALE * comp + rng.normal(0, idio_vol)
        crash = rng.random(N_TICKERS) < crash_p[t]
        r[crash] += rng.uniform(-0.45, -0.15, crash.sum())
        pop = rng.random(N_TICKERS) < pop_p
        r[pop] += rng.uniform(0.10, 0.30, pop.sum())
        prices[t] = np.maximum(prices[t - 1] * (1.0 + r), 0.50)

    base = pd.Timestamp("2025-01-02")
    dates = [(base + pd.Timedelta(days=int(i))).date() for i in range(total)]
    return Market(tickers, sectors, prices, fac, spy, dates)


# ── Precompute regimes + rankings (shared by both variants) ─────────────────────

def precompute_signals(mkt: Market, strategy):
    cfg = strategy.regime_detection
    spy_df_full = pd.DataFrame({"date": mkt.dates, "adjusted_close": mkt.spy})

    regimes: list[str] = []
    current = None
    run_regime = None
    run_len = 0
    rankings: list[list[tuple]] = []   # per sim day: [(ticker, rank, score), ...]

    for t in range(SIM_DAYS):
        gt = WARMUP + t
        raw = detect_regime(spy_df_full.iloc[: gt + 1], cfg)["raw_regime"]
        # confirmation smoothing: retain prior regime until N consecutive new-raw days
        if current is None:
            current = raw
        elif raw == current:
            run_regime, run_len = None, 0
        else:
            if raw == run_regime:
                run_len += 1
            else:
                run_regime, run_len = raw, 1
            if run_len >= cfg.confirmation_days:
                current = raw
                run_regime, run_len = None, 0
        regimes.append(current)

        fac_t = mkt.factors[gt]  # (n_tickers, 6)
        df = pd.DataFrame({"ticker": mkt.tickers})
        for fi, fname in enumerate(FACTORS):
            df[fname] = cross_section_zscore(pd.Series(fac_t[:, fi]))
        ranked = rank_universe(df, current, strategy)
        rankings.append(list(zip(ranked["ticker"], ranked["rank"], ranked["composite_score"])))

    return regimes, rankings


# ── Portfolio target (adj_score_proportional, top-N, sector-capped) ─────────────

def build_target(ranking, sectors, max_positions, max_pos_w, max_sector_w):
    per_sector_cap = max(1, int(max_sector_w * max_positions))
    sector_count: dict[str, int] = {}
    chosen = []  # (ticker, score)
    for ticker, _rank, score in ranking:
        if len(chosen) >= max_positions:
            break
        sec = sectors[ticker]
        if sector_count.get(sec, 0) >= per_sector_cap:
            continue
        chosen.append((ticker, score))
        sector_count[sec] = sector_count.get(sec, 0) + 1
    if not chosen:
        return {}
    scores = np.array([s for _, s in chosen], dtype=float)
    adj = scores - scores.min() + 1e-6           # shift strictly positive
    w = adj / adj.sum()
    w = np.minimum(w, max_pos_w)                  # clip per-name
    w = w / w.sum()                              # renormalize to fully invested
    return {t: float(wi) for (t, _), wi in zip(chosen, w)}


# ── Execution (one variant) ─────────────────────────────────────────────────────

@dataclass
class RunResult:
    pv: list = field(default_factory=list)
    cash: list = field(default_factory=list)
    invested: list = field(default_factory=list)
    n_positions: list = field(default_factory=list)
    entries: int = 0
    delta_exits: int = 0
    stop_exits: int = 0
    buy_adds: int = 0
    sell_trims: int = 0
    reentries: int = 0
    gross_buys: float = 0.0
    gross_sells: float = 0.0


def run_variant(use_trailing, mkt: Market, regimes, rankings, strategy, trail_pct):
    de = strategy.delta_engine
    entry_rank, exit_rank = de.entry_rank, de.exit_rank
    conf_days = de.confirmation_days
    max_positions = de.max_positions
    drift_threshold = de.rebalance_drift_threshold
    pb = strategy.portfolio_builder
    max_pos_w, max_sector_w = pb.max_position_weight, pb.max_sector_weight

    cash = START_CASH
    positions: dict[str, list] = {}     # ticker -> [qty, avg_price]
    stops: dict = {}                    # ticker -> TrailingStopState (variant B)
    rank_hist: dict[str, list] = {}     # ticker -> [RankObservation] most-recent-first
    last_stopped_day: dict[str, int] = {}
    res = RunResult()

    for t in range(SIM_DAYS):
        gt = WARMUP + t
        day_price = {mkt.tickers[i]: float(mkt.prices[gt, i]) for i in range(N_TICKERS)}
        rdate = mkt.dates[gt]

        # 1. trailing-stop evaluation (variant B) — react to today's close first
        if use_trailing:
            for tk in list(positions):
                st = stops.get(tk)
                px = day_price.get(tk)
                if st is None or px is None:
                    continue
                if st.update(px):
                    qty = positions[tk][0]
                    cash += qty * px
                    res.gross_sells += qty * px
                    res.stop_exits += 1
                    last_stopped_day[tk] = t
                    del positions[tk]
                    stops.pop(tk, None)

        # 2. rank history (most-recent-first), shared logic
        for ticker, rank, score in rankings[t]:
            obs = rank_hist.setdefault(ticker, [])
            obs.insert(0, RankObservation(run_date=rdate, rank=int(rank), composite_score=float(score)))
            del obs[6:]

        # 3. account state
        acct = cash + sum(q * day_price[tk] for tk, (q, _) in positions.items() if tk in day_price)
        actual_w = {tk: (positions[tk][0] * day_price[tk]) / acct
                    for tk in positions if tk in day_price and acct > 0}

        # 4. target portfolio
        target = build_target(rankings[t], mkt.sectors, max_positions, max_pos_w, max_sector_w)

        # 5. buffer-zone delta engine (the real decision logic)
        decisions = evaluate_target_vs_live(
            target_portfolio=target,
            live_positions=set(positions),
            universe=rank_hist,
            entry_rank=entry_rank,
            exit_rank=exit_rank,
            confirmation_days=conf_days,
            max_positions=max_positions,
            actual_weights=actual_w,
            drift_threshold=drift_threshold,
            account_value=acct,
            buying_power=cash,
        )

        # 6. execute — sells first (free cash), then buys (same-open net-out)
        sells = [d for d in decisions.values() if d.action in ("exit", "sell_trim")]
        buys = [d for d in decisions.values() if d.action in ("entry", "buy_add")]
        for d in sells:
            tk = d.ticker
            if tk not in positions:
                continue
            px = day_price.get(tk)
            if px is None:
                continue
            held = positions[tk][0]
            if d.action == "exit":
                qty = held
                res.delta_exits += 1
            else:  # sell_trim
                qty = min(held, int(acct * abs(d.weight_drift or 0.0) / px))
                if qty < 1:
                    continue
                res.sell_trims += 1
            cash += qty * px
            res.gross_sells += qty * px
            new_qty = held - qty
            if new_qty <= 1e-9:
                del positions[tk]
                stops.pop(tk, None)
            else:
                positions[tk][0] = new_qty

        for d in sorted(buys, key=lambda d: d.rank):
            tk = d.ticker
            px = day_price.get(tk)
            if px is None or px <= 0:
                continue
            if d.action == "entry":
                want = int(acct * (d.current_weight or 0.0) / px)
            else:  # buy_add
                want = int(acct * abs(d.weight_drift or 0.0) / px)
            qty = min(want, int(cash / px))   # never spend more cash than we have
            if qty < 1:
                continue
            cost = qty * px
            cash -= cost
            res.gross_buys += cost
            if tk in positions:
                pq, pp = positions[tk]
                positions[tk] = [pq + qty, (pq * pp + cost) / (pq + qty)]
                res.buy_adds += 1
            else:
                positions[tk] = [qty, px]
                res.entries += 1
                if last_stopped_day.get(tk) is not None and t - last_stopped_day[tk] <= 10:
                    res.reentries += 1
            if use_trailing:
                existing = stops.get(tk)
                if existing is None:
                    stops[tk] = arm(trail_pct, px)
                else:
                    existing.hwm = max(existing.hwm, px)

        # 7. end-of-day portfolio value
        pv = cash + sum(q * day_price[tk] for tk, (q, _) in positions.items() if tk in day_price)
        res.pv.append(pv)
        res.cash.append(cash)
        res.invested.append(pv - cash)
        res.n_positions.append(len(positions))

    return res


# ── Metrics ─────────────────────────────────────────────────────────────────────

def metrics(pv):
    pv = np.asarray(pv, dtype=float)
    rets = pv[1:] / pv[:-1] - 1.0
    total_ret = pv[-1] / pv[0] - 1.0
    ann = (1 + total_ret) ** (252.0 / len(pv)) - 1.0
    vol = rets.std() * np.sqrt(252) if len(rets) else 0.0
    sharpe = (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    peak = np.maximum.accumulate(pv)
    mdd = float(((pv - peak) / peak).min())
    return dict(final=pv[-1], total_ret=total_ret, ann=ann, vol=vol, sharpe=sharpe, mdd=mdd)


def _fmt_pct(x):
    return f"{x*100:+.2f}%"


# ── Single-seed run with table + chart ──────────────────────────────────────────

def main():
    print(f"=== Trailing-stop A/B simulation (seed={SEED}, trail={TRAIL_PCT}%) ===")
    print(f"universe={N_TICKERS} tickers, sim_days={SIM_DAYS}, start_cash=${START_CASH:,.0f}\n")
    strategy, _ = load_strategy(os.path.join(ROOT, "strategies", "quality_core_v1.yaml"))

    mkt = generate_market(SEED)
    regimes, rankings = precompute_signals(mkt, strategy)
    from collections import Counter
    print("Regime days (real detect_regime):", dict(Counter(regimes)))
    spy_sim = mkt.spy[WARMUP:]
    print(f"SPY over sim window: {_fmt_pct(spy_sim[-1]/spy_sim[0]-1)}\n")

    base = run_variant(False, mkt, regimes, rankings, strategy, TRAIL_PCT)
    trail = run_variant(True, mkt, regimes, rankings, strategy, TRAIL_PCT)

    mb, mt = metrics(base.pv), metrics(trail.pv)
    spy_m = metrics(spy_sim)

    rows = [
        ("Final value",        f"${mb['final']:,.0f}",     f"${mt['final']:,.0f}"),
        ("Total return",       _fmt_pct(mb['total_ret']),  _fmt_pct(mt['total_ret'])),
        ("Annualized",         _fmt_pct(mb['ann']),        _fmt_pct(mt['ann'])),
        ("Volatility (ann)",   _fmt_pct(mb['vol']),        _fmt_pct(mt['vol'])),
        ("Sharpe",             f"{mb['sharpe']:.2f}",      f"{mt['sharpe']:.2f}"),
        ("Max drawdown",       _fmt_pct(mb['mdd']),        _fmt_pct(mt['mdd'])),
        ("Entries",            f"{base.entries}",          f"{trail.entries}"),
        ("Delta exits",        f"{base.delta_exits}",      f"{trail.delta_exits}"),
        ("Trailing-stop exits", "-",                       f"{trail.stop_exits}"),
        ("Buy-adds",           f"{base.buy_adds}",         f"{trail.buy_adds}"),
        ("Sell-trims",         f"{base.sell_trims}",       f"{trail.sell_trims}"),
        ("Stop->re-entry <=10d", "-",                      f"{trail.reentries}"),
        ("Gross traded $",     f"${base.gross_buys+base.gross_sells:,.0f}",
                               f"${trail.gross_buys+trail.gross_sells:,.0f}"),
        ("Avg cash %",         f"{np.mean(base.cash)/np.mean(base.pv)*100:.1f}%",
                               f"{np.mean(trail.cash)/np.mean(trail.pv)*100:.1f}%"),
    ]
    w = max(len(r[0]) for r in rows)
    print(f"{'Metric'.ljust(w)} | {'Sim 1 (as-is)':>18} | {'Sim 2 (+trail)':>18}")
    print("-" * (w + 44))
    for name, a, b in rows:
        print(f"{name.ljust(w)} | {a:>18} | {b:>18}")
    print(f"\nSPY benchmark: total {_fmt_pct(spy_m['total_ret'])}, MDD {_fmt_pct(spy_m['mdd'])}")
    print(f"d final value (Sim2 - Sim1): ${mt['final']-mb['final']:,.0f} "
          f"({_fmt_pct(mt['total_ret']-mb['total_ret'])} of start)")

    out_png = os.path.join(ROOT, "artifacts", "trailing_stop_ab.png")
    _plot(base, trail, mkt, regimes, out_png)
    print(f"\nChart written: {out_png}")
    return out_png


# ── Multi-seed aggregate run ────────────────────────────────────────────────────

def _run_one(seed, strategy):
    mkt = generate_market(seed)
    regimes, rankings = precompute_signals(mkt, strategy)
    base = run_variant(False, mkt, regimes, rankings, strategy, TRAIL_PCT)
    trail = run_variant(True, mkt, regimes, rankings, strategy, TRAIL_PCT)
    return mkt, regimes, base, trail


def multi(seeds):
    strategy, _ = load_strategy(os.path.join(ROOT, "strategies", "quality_core_v1.yaml"))
    lines: list[str] = []

    def out(s=""):
        lines.append(s)

    out(f"=== Trailing-stop A/B simulation — {len(seeds)} seeds, trail={TRAIL_PCT}% ===")
    out(f"universe={N_TICKERS} tickers, sim_days={SIM_DAYS}, start_cash=${START_CASH:,.0f}")
    out("Reuses real modules: detect_regime, cross_section_zscore, rank_universe, "
        "evaluate_target_vs_live; trailing.py shared with alpaca-sim.")
    out("")
    out(f"{'seed':>5} | {'Sim1 final':>13} | {'Sim2 final':>13} | {'Sim1 ret':>9} | "
        f"{'Sim2 ret':>9} | {'Sim1 MDD':>9} | {'Sim2 MDD':>9} | {'stops':>6} | {'reentry':>7}")
    out("-" * 104)

    agg = {"b_final": [], "t_final": [], "b_ret": [], "t_ret": [],
           "b_mdd": [], "t_mdd": [], "b_sh": [], "t_sh": [], "stops": [], "reentry": [],
           "t_wins": 0, "mdd_better": 0}
    first = None
    for sd in seeds:
        mkt, regimes, base, trail = _run_one(sd, strategy)
        if first is None:
            first = (mkt, regimes, base, trail)
        mb, mt = metrics(base.pv), metrics(trail.pv)
        out(f"{sd:>5} | ${mb['final']:>11,.0f} | ${mt['final']:>11,.0f} | "
            f"{_fmt_pct(mb['total_ret']):>9} | {_fmt_pct(mt['total_ret']):>9} | "
            f"{_fmt_pct(mb['mdd']):>9} | {_fmt_pct(mt['mdd']):>9} | "
            f"{trail.stop_exits:>6} | {trail.reentries:>7}")
        agg["b_final"].append(mb["final"]); agg["t_final"].append(mt["final"])
        agg["b_ret"].append(mb["total_ret"]); agg["t_ret"].append(mt["total_ret"])
        agg["b_mdd"].append(mb["mdd"]); agg["t_mdd"].append(mt["mdd"])
        agg["b_sh"].append(mb["sharpe"]); agg["t_sh"].append(mt["sharpe"])
        agg["stops"].append(trail.stop_exits); agg["reentry"].append(trail.reentries)
        agg["t_wins"] += int(mt["final"] > mb["final"])
        agg["mdd_better"] += int(mt["mdd"] > mb["mdd"])   # less negative = shallower

    import statistics as st
    n = len(seeds)
    out("-" * 104)
    out("")
    out("AVERAGES across seeds:")
    out(f"  Final value     Sim1 ${st.mean(agg['b_final']):>13,.0f}   "
        f"Sim2 ${st.mean(agg['t_final']):>13,.0f}   "
        f"d ${st.mean(agg['t_final'])-st.mean(agg['b_final']):>+12,.0f}")
    out(f"  Total return    Sim1 {_fmt_pct(st.mean(agg['b_ret'])):>13}   "
        f"Sim2 {_fmt_pct(st.mean(agg['t_ret'])):>13}")
    out(f"  Max drawdown    Sim1 {_fmt_pct(st.mean(agg['b_mdd'])):>13}   "
        f"Sim2 {_fmt_pct(st.mean(agg['t_mdd'])):>13}   (shallower is better)")
    out(f"  Sharpe          Sim1 {st.mean(agg['b_sh']):>13.2f}   "
        f"Sim2 {st.mean(agg['t_sh']):>13.2f}")
    out(f"  Trailing-stop exits/yr (avg): {st.mean(agg['stops']):.0f}   "
        f"stop->re-entries <=10d (avg): {st.mean(agg['reentry']):.0f}")
    out("")
    out(f"  Sim2 beat Sim1 on FINAL VALUE in {agg['t_wins']}/{n} seeds")
    out(f"  Sim2 had SHALLOWER drawdown   in {agg['mdd_better']}/{n} seeds")
    out("")
    out("Interpretation: a 5% trailing stop trades upside capture for downside")
    out("control - it cuts idiosyncratic crashes and the bear-regime leg, but in")
    out("choppy bull regimes it whipsaws out of volatile winners (see re-entries).")

    report = os.path.join(ROOT, "artifacts", "trailing_stop_ab_report.txt")
    os.makedirs(os.path.dirname(report), exist_ok=True)
    with open(report, "w") as f:
        f.write("\n".join(lines) + "\n")
    mkt, regimes, base, trail = first
    png = os.path.join(ROOT, "artifacts", "trailing_stop_ab.png")
    _plot(base, trail, mkt, regimes, png)
    print("\n".join(lines))
    print(f"\nReport: {report}\nChart:  {png}")
    return report, png


# ── Chart ────────────────────────────────────────────────────────────────────────

def _plot(base, trail, mkt, regimes, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(os.path.dirname(path), exist_ok=True)
    days = np.arange(SIM_DAYS)
    spy = mkt.spy[WARMUP:]
    spy_scaled = START_CASH * spy / spy[0]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9), height_ratios=[3, 1], sharex=True)

    colors = {"bull_calm": "#e8f5e9", "bull_stress": "#fff8e1",
              "bear_stress": "#ffebee", "bear_calm": "#eceff1"}
    start = 0
    for i in range(1, SIM_DAYS + 1):
        if i == SIM_DAYS or regimes[i] != regimes[start]:
            ax1.axvspan(start, i, color=colors.get(regimes[start], "#ffffff"), alpha=0.6, zorder=0)
            start = i

    ax1.plot(days, base.pv, label="Sim 1 - as-is exits", color="#1565c0", lw=1.8)
    ax1.plot(days, trail.pv, label=f"Sim 2 - +{TRAIL_PCT:.0f}% trailing stop", color="#c62828", lw=1.8)
    ax1.plot(days, spy_scaled, label="SPY (scaled)", color="#555", lw=1.0, ls="--")
    ax1.axhline(START_CASH, color="#999", lw=0.8, ls=":")
    ax1.set_ylabel("Portfolio value ($)")
    ax1.set_title(f"365-day A/B: buffer-zone exits vs +{TRAIL_PCT:.0f}% trailing stop "
                  f"(seed={SEED}, {N_TICKERS} tickers)")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(lambda x, _: f"${x/1000:.0f}k")

    def dd(pv):
        pv = np.asarray(pv)
        return (pv - np.maximum.accumulate(pv)) / np.maximum.accumulate(pv) * 100

    ax2.plot(days, dd(base.pv), color="#1565c0", lw=1.2)
    ax2.plot(days, dd(trail.pv), color="#c62828", lw=1.2)
    ax2.fill_between(days, dd(base.pv), 0, color="#1565c0", alpha=0.12)
    ax2.fill_between(days, dd(trail.pv), 0, color="#c62828", alpha=0.12)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Trading day")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    seeds_env = os.getenv("SIM_SEEDS")
    if seeds_env:
        multi([int(s) for s in seeds_env.split(",") if s.strip()])
    else:
        main()
