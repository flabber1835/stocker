#!/usr/bin/env python3
"""Prototype + measurement: drawdown entry-timing gate.

Idea (from the design discussion): keep ranking exactly as-is, but at the BUY
step defer an `entry` when the candidate is in free-fall — i.e. trading more than
`max_drawdown` below its trailing `dd_window`-day peak. This is an entry-timing
gate, NOT a ranking input: it never sells, it only delays NEW buys (entry->watch),
re-evaluated each day so a stabilized name is bought on the next chain.

The gate is the pure function `drawdown_entry_gate` below — written to drop into
`evaluate_target_vs_live` right after `_cap_buys` (same entry->watch demotion
pattern). Here we measure it against the SAME synthetic world as the A/B sim:

  - Reuses generate_market / precompute_signals / build_target / the real
    evaluate_target_vs_live delta engine (via trailing_stop_ab_sim).
  - Runs two variants on one deterministic path: baseline vs gated entries.

Reported:
  - entries deferred by the gate, split into:
      * FALLING KNIFE   = deferred name whose next dd_window-day forward return < 0
                          (gate was RIGHT — it dropped further / underperformed)
      * GOOD-ENTRY MISS = deferred name whose forward return > 0
                          (gate was WRONG — we delayed a winner)
  - precision = knives / (knives + misses)
  - net effect on final value & drawdown vs baseline.

Run:
    python tests/simulation/drawdown_entry_gate_sim.py
    SIM_SEEDS=1,2,3,4,5 DD_WINDOW=21 DD_MAX=0.15 python tests/simulation/drawdown_entry_gate_sim.py
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "tests", "simulation"))

from app.engine import RankObservation, evaluate_target_vs_live  # noqa: E402
from stock_strategy_shared.loader import load_strategy  # noqa: E402
import trailing_stop_ab_sim as AB  # reuse market + signal machinery  # noqa: E402


# ── Parameters ──────────────────────────────────────────────────────────────
DD_WINDOW = int(os.getenv("DD_WINDOW", "21"))     # trailing peak lookback (trading days)
DD_MAX = float(os.getenv("DD_MAX", "0.15"))       # defer entry if drawdown worse than -15%
FWD_WINDOW = int(os.getenv("FWD_WINDOW", "21"))   # horizon for judging knife vs miss
START_CASH = AB.START_CASH
WARMUP, SIM_DAYS, N_TICKERS = AB.WARMUP, AB.SIM_DAYS, AB.N_TICKERS


# ── The gate (pure — drop-in for evaluate_target_vs_live after _cap_buys) ────

def drawdown_entry_gate(
    decisions: dict,
    drawdowns: dict[str, float],
    max_drawdown: float = 0.15,
) -> list[str]:
    """Defer `entry` intents for names in free-fall. Mutates `decisions` in place.

    drawdowns: ticker -> current drawdown from trailing peak, as a NEGATIVE
               fraction (e.g. -0.22 = 22% below the recent peak). Missing/0 = ok.
    max_drawdown: positive threshold; defer when drawdown < -max_drawdown.

    Demotes entry -> watch (never touches held positions, buy_adds, or sells).
    Returns the list of deferred tickers (for measurement/audit).
    """
    deferred: list[str] = []
    for tk, d in list(decisions.items()):
        if d.action != "entry":
            continue
        dd = drawdowns.get(tk)
        if dd is not None and dd < -abs(max_drawdown):
            decisions[tk] = replace(
                d, action="watch", current_weight=None,
                reason=(f"entry deferred — in free-fall ({dd:+.1%} vs "
                        f"{DD_WINDOW}d peak, limit -{max_drawdown:.0%})"),
            )
            deferred.append(tk)
    return deferred


# ── Drawdown from the price panel ────────────────────────────────────────────

def trailing_drawdowns(prices: np.ndarray, gt: int, window: int) -> np.ndarray:
    """Per-ticker drawdown at global day gt: price_gt / max(last `window`) - 1."""
    lo = max(0, gt - window + 1)
    peak = prices[lo:gt + 1].max(axis=0)
    cur = prices[gt]
    return np.where(peak > 0, cur / peak - 1.0, 0.0)


# ── One variant ──────────────────────────────────────────────────────────────

@dataclass
class Res:
    pv: list = field(default_factory=list)
    entries: int = 0
    deferred_total: int = 0
    knife: int = 0          # deferred & forward return < 0  (gate right)
    miss: int = 0           # deferred & forward return >= 0 (gate wrong)
    knife_fwd: list = field(default_factory=list)
    miss_fwd: list = field(default_factory=list)


def run(use_gate, mkt, rankings, strategy):
    de = strategy.delta_engine
    pb = strategy.portfolio_builder
    cash = START_CASH
    positions: dict[str, list] = {}
    rank_hist: dict[str, list] = {}
    res = Res()

    for t in range(SIM_DAYS):
        gt = WARMUP + t
        day_price = {mkt.tickers[i]: float(mkt.prices[gt, i]) for i in range(N_TICKERS)}
        rdate = mkt.dates[gt]

        for tk, rk, sc in rankings[t]:
            obs = rank_hist.setdefault(tk, [])
            obs.insert(0, RankObservation(run_date=rdate, rank=int(rk), composite_score=float(sc)))
            del obs[6:]

        acct = cash + sum(q * day_price[tk] for tk, (q, _) in positions.items() if tk in day_price)
        actual_w = {tk: (positions[tk][0] * day_price[tk]) / acct
                    for tk in positions if tk in day_price and acct > 0}
        target = AB.build_target(rankings[t], mkt.sectors, de.max_positions,
                                 pb.max_position_weight, pb.max_sector_weight)

        decisions = evaluate_target_vs_live(
            target_portfolio=target, live_positions=set(positions), universe=rank_hist,
            confirmation_days=de.confirmation_days, max_positions=de.max_positions,
            actual_weights=actual_w, drift_threshold=de.rebalance_drift_threshold,
            account_value=acct, buying_power=cash,
        )

        # ── the gate ──
        if use_gate:
            dd_arr = trailing_drawdowns(mkt.prices, gt, DD_WINDOW)
            dd_map = {mkt.tickers[i]: float(dd_arr[i]) for i in range(N_TICKERS)}
            deferred = drawdown_entry_gate(decisions, dd_map, DD_MAX)
            for tk in deferred:
                res.deferred_total += 1
                # judge: forward return over FWD_WINDOW from today
                gf = min(gt + FWD_WINDOW, mkt.prices.shape[0] - 1)
                i = mkt.tickers.index(tk)
                fwd = mkt.prices[gf, i] / mkt.prices[gt, i] - 1.0
                if fwd < 0:
                    res.knife += 1; res.knife_fwd.append(fwd)
                else:
                    res.miss += 1; res.miss_fwd.append(fwd)

        # execute: sells then buys (same as A/B sim)
        for d in [x for x in decisions.values() if x.action in ("exit", "sell_trim")]:
            tk = d.ticker
            if tk not in positions:
                continue
            px = day_price.get(tk)
            if px is None:
                continue
            held = positions[tk][0]
            qty = held if d.action == "exit" else min(held, int(acct * abs(d.weight_drift or 0) / px))
            if qty < 1:
                continue
            cash += qty * px
            nq = held - qty
            if nq <= 1e-9:
                del positions[tk]
            else:
                positions[tk][0] = nq
        for d in sorted([x for x in decisions.values() if x.action in ("entry", "buy_add")],
                        key=lambda d: d.rank):
            tk = d.ticker
            px = day_price.get(tk)
            if px is None or px <= 0:
                continue
            want = int(acct * (d.current_weight or 0) / px) if d.action == "entry" \
                else int(acct * abs(d.weight_drift or 0) / px)
            qty = min(want, int(cash / px))
            if qty < 1:
                continue
            cash -= qty * px
            if tk in positions:
                pq, pp = positions[tk]
                positions[tk] = [pq + qty, (pq * pp + qty * px) / (pq + qty)]
            else:
                positions[tk] = [qty, px]
                res.entries += 1

        res.pv.append(cash + sum(q * day_price[tk] for tk, (q, _) in positions.items() if tk in day_price))
    return res


def main():
    seeds = [int(s) for s in os.getenv("SIM_SEEDS", "1,2,3,4,5").split(",")]
    strategy, _ = load_strategy(os.path.join(ROOT, "strategies", "quality_core_v1.yaml"))
    print(f"=== Drawdown entry-gate prototype === dd_window={DD_WINDOW}d "
          f"defer<-{DD_MAX:.0%}, judge fwd={FWD_WINDOW}d, seeds={seeds}")
    print("Gate is pure drawdown_entry_gate(); ranking unchanged; entry->watch only.\n")
    hdr = (f"{'seed':>4} | {'base final':>12} | {'gate final':>12} | {'entries':>7} | "
           f"{'deferred':>8} | {'knife':>5} | {'miss':>5} | {'precision':>9}")
    print(hdr); print("-" * len(hdr))

    agg = {k: [] for k in ("bf", "gf", "defer", "knife", "miss", "prec",
                            "bmdd", "gmdd", "kfwd", "mfwd")}
    for sd in seeds:
        mkt = AB.generate_market(sd)
        _, rankings = AB.precompute_signals(mkt, strategy)
        base = run(False, mkt, rankings, strategy)
        gate = run(True, mkt, rankings, strategy)
        mb, mg = AB.metrics(base.pv), AB.metrics(gate.pv)
        prec = gate.knife / (gate.knife + gate.miss) if (gate.knife + gate.miss) else float("nan")
        print(f"{sd:>4} | ${mb['final']:>10,.0f} | ${mg['final']:>10,.0f} | "
              f"{gate.entries:>7} | {gate.deferred_total:>8} | {gate.knife:>5} | "
              f"{gate.miss:>5} | {prec:>8.1%}")
        agg["bf"].append(mb["final"]); agg["gf"].append(mg["final"])
        agg["defer"].append(gate.deferred_total); agg["knife"].append(gate.knife)
        agg["miss"].append(gate.miss); agg["prec"].append(prec)
        agg["bmdd"].append(mb["mdd"]); agg["gmdd"].append(mg["mdd"])
        agg["kfwd"] += gate.knife_fwd; agg["mfwd"] += gate.miss_fwd

    import statistics as st
    print("-" * len(hdr))
    print("\nAVERAGES:")
    print(f"  Final value   base ${st.mean(agg['bf']):>12,.0f}   "
          f"gate ${st.mean(agg['gf']):>12,.0f}   d ${st.mean(agg['gf'])-st.mean(agg['bf']):>+11,.0f}")
    print(f"  Max drawdown  base {st.mean(agg['bmdd'])*100:>+7.2f}%   "
          f"gate {st.mean(agg['gmdd'])*100:>+7.2f}%")
    print(f"  Deferred/yr   {st.mean(agg['defer']):.0f}   "
          f"(knife {st.mean(agg['knife']):.0f}, miss {st.mean(agg['miss']):.0f})")
    prec_all = sum(agg["knife"]) / (sum(agg["knife"]) + sum(agg["miss"])) if (sum(agg["knife"]) + sum(agg["miss"])) else float("nan")
    print(f"  Gate precision (pooled): {prec_all:.1%}  "
          f"(deferrals whose next {FWD_WINDOW}d return was negative)")
    if agg["kfwd"]:
        print(f"  Avg fwd return  knives {st.mean(agg['kfwd'])*100:+.2f}%   "
              f"misses {st.mean(agg['mfwd'])*100:+.2f}%   "
              f"(spread = avg drop avoided vs upside delayed)")
    print("\nRead: high precision + final value >= base => the gate skips losers")
    print("without sacrificing winners. Low precision or lower final value => the")
    print("threshold is too tight (deferring normal dips). Sweep DD_MAX / DD_WINDOW.")


if __name__ == "__main__":
    main()
