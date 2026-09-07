#!/usr/bin/env python3
"""Eight preregistered Median-5 statistical/robustness closure analyses.

All analyses consume frozen daily evidence. They never modify strategy economics.
TEMPORAL_LEAVEOUT and CONTRIBUTOR_CONCENTRATION are explicitly descriptive
return-path/exposure analyses, not causal replays.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

MODES = (
    "DSR",
    "PBO_CSCV",
    "REALITY_CHECK",
    "ROLLING_WINDOWS",
    "TEMPORAL_LEAVEOUT",
    "BLOCK_BOOTSTRAP",
    "CONTRIBUTOR_CONCENTRATION",
    "WORST_REGIME",
)


def _daily_files(root: Path):
    return sorted(root.rglob("daily.csv"))


def _load_one(root: Path) -> pd.DataFrame:
    files = _daily_files(root)
    if len(files) != 1:
        raise RuntimeError(f"expected exactly one canonical daily.csv under {root}, got {len(files)}")
    d = pd.read_csv(files[0], parse_dates=["date"]).sort_values("date")
    if len(d) != 5032 or str(d.date.iloc[0].date()) != "2006-07-31" or str(d.date.iloc[-1].date()) != "2026-07-31":
        raise RuntimeError("canonical full-PIT measurement witness mismatch")
    if d.date.duplicated().any() or not d.date.is_monotonic_increasing:
        raise RuntimeError("invalid canonical date axis")
    for c in ("A_nav", "spy_nav"):
        if c not in d or not np.isfinite(d[c].astype(float)).all() or (d[c].astype(float) <= 0).any():
            raise RuntimeError(f"invalid {c}")
    return d


def _metrics(nav: pd.Series, dates: pd.Series | pd.DatetimeIndex) -> dict:
    v = nav.astype(float).reset_index(drop=True)
    dt = pd.Series(pd.to_datetime(dates)).reset_index(drop=True)
    r = v.pct_change().dropna()
    yrs = (dt.iloc[-1] - dt.iloc[0]).days / 365.2425
    mult = float(v.iloc[-1] / v.iloc[0])
    vol = float(r.std(ddof=1))
    return {
        "cagr": float(mult ** (1.0 / yrs) - 1.0),
        "max_drawdown": float((v / v.cummax() - 1).min()),
        "sharpe_daily_252": float(r.mean() / vol * math.sqrt(252)) if vol > 0 else None,
        "ending_multiple": mult,
        "sessions": int(len(v)),
    }


def _returns(d: pd.DataFrame, col="A_nav") -> np.ndarray:
    return d[col].astype(float).pct_change().dropna().to_numpy(float)


def _skew_kurt(x: np.ndarray):
    x = np.asarray(x, float)
    m = x.mean(); s = x.std(ddof=0)
    if s == 0: return 0.0, 3.0
    z = (x - m) / s
    return float(np.mean(z ** 3)), float(np.mean(z ** 4))


def dsr(d: pd.DataFrame) -> dict:
    r = _returns(d)
    n = len(r)
    sr_d = float(r.mean() / r.std(ddof=1))
    sr_a = sr_d * math.sqrt(252)
    skew, kurt = _skew_kurt(r)
    # Bailey/Lopez de Prado finite-sample SR uncertainty adjustment.
    se = math.sqrt(max(1e-18, (1 - skew * sr_d + ((kurt - 1) / 4) * sr_d * sr_d) / (n - 1)))
    nd = NormalDist(); gamma = 0.5772156649015329
    rows = []
    for trials in (41, 100, 250):
        sigma0 = 1.0 / math.sqrt(n - 1)
        a = nd.inv_cdf(1 - 1 / trials)
        b = nd.inv_cdf(1 - 1 / (trials * math.e))
        benchmark_d = sigma0 * ((1 - gamma) * a + gamma * b)
        prob = nd.cdf((sr_d - benchmark_d) / se)
        rows.append({
            "trial_count": trials,
            "observed_sharpe_annualized": sr_a,
            "deflated_sharpe_probability": float(prob),
            "expected_max_null_sharpe_annualized": float(benchmark_d * math.sqrt(252)),
        })
    return {
        "method": "Deflated Sharpe Ratio finite-sample skew/kurtosis adjustment",
        "documented_trial_count_lower_bound": 41,
        "daily_observations": n,
        "skew": skew,
        "kurtosis_raw": kurt,
        "rows": rows,
    }


def _family(hardening: Path, canonical: pd.DataFrame):
    frames = {"MEDIAN5_FRESH_RECERT": canonical[["date", "A_nav", "spy_nav"]].copy()}
    for p in _daily_files(hardening):
        try:
            d = pd.read_csv(p, parse_dates=["date"])
        except Exception:
            continue
        if len(d) != 5032 or "A_nav" not in d: continue
        name = p.parent.parent.name
        if name in frames: name = str(p.parent.parent.parent.name) + "/" + name
        frames[name] = d[["date", "A_nav", "spy_nav"]].copy()
    if len(frames) < 6:
        raise RuntimeError(f"hardening candidate family incomplete: {len(frames)} paths")
    base_dates = canonical.date.reset_index(drop=True)
    for k, d in frames.items():
        if not d.date.reset_index(drop=True).equals(base_dates):
            raise RuntimeError(f"date mismatch in family {k}")
    return frames


def pbo_cscv(canonical, hardening):
    fam = _family(hardening, canonical)
    names = sorted(fam)
    R = np.column_stack([_returns(fam[n]) for n in names])
    n = len(R); S = 15
    blocks = np.array_split(np.arange(n), S)
    lambdas = []; selected = {n: 0 for n in names}; combos = 0
    for train_blocks in itertools.combinations(range(S), 7):
        train_set = set(train_blocks)
        tr = np.concatenate([blocks[i] for i in range(S) if i in train_set])
        te = np.concatenate([blocks[i] for i in range(S) if i not in train_set])
        mu = R[tr].mean(axis=0); sd = R[tr].std(axis=0, ddof=1)
        sr = np.divide(mu, sd, out=np.full_like(mu, -np.inf), where=sd > 0)
        j = int(np.argmax(sr)); selected[names[j]] += 1
        muo = R[te].mean(axis=0); sdo = R[te].std(axis=0, ddof=1)
        sro = np.divide(muo, sdo, out=np.full_like(muo, -np.inf), where=sdo > 0)
        order = np.argsort(sro)
        rank = int(np.where(order == j)[0][0]) + 1
        w = rank / (len(names) + 1.0)
        lambdas.append(float(math.log(w / (1 - w))))
        combos += 1
    lam = np.asarray(lambdas)
    return {
        "method": "CSCV 15 contiguous blocks, choose 7 in-sample / 8 out-of-sample",
        "candidate_count": len(names),
        "candidate_names": names,
        "combinations": combos,
        "pbo": float(np.mean(lam <= 0)),
        "median_logit_oos_rank": float(np.median(lam)),
        "in_sample_selection_counts": selected,
    }


def reality_check(canonical, hardening):
    fam = _family(hardening, canonical); names = sorted(fam)
    spy = _returns(canonical, "spy_nav")
    X = np.column_stack([_returns(fam[n]) - spy for n in names])
    obs = float(np.max(X.mean(axis=0)))
    centered = X - X.mean(axis=0, keepdims=True)
    rng = np.random.default_rng(20260907)
    n = len(X); block = 20; B = 3000
    maxima = np.empty(B)
    starts = np.arange(n)
    for b in range(B):
        idx = []
        while len(idx) < n:
            s = int(rng.choice(starts))
            idx.extend(((s + np.arange(block)) % n).tolist())
        samp = centered[np.asarray(idx[:n])]
        maxima[b] = np.max(samp.mean(axis=0))
    return {
        "method": "White-style circular block bootstrap of maximum mean daily excess return",
        "candidate_count": len(names), "candidate_names": names,
        "bootstrap_draws": B, "block_sessions": block,
        "observed_max_mean_daily_excess": obs,
        "p_value": float((1 + np.sum(maxima >= obs)) / (B + 1)),
    }


def rolling_windows(d):
    d = d.copy().set_index("date")
    out = {}
    month_ends = d.groupby([d.index.year, d.index.month]).tail(1).index
    for years in (3, 5, 7, 10):
        rows = []
        for end in month_ends:
            start = end - pd.DateOffset(years=years)
            part = d[(d.index >= start) & (d.index <= end)]
            if len(part) < int(years * 240): continue
            sm = _metrics(part.A_nav, part.index); bm = _metrics(part.spy_nav, part.index)
            rows.append((end, sm["cagr"], bm["cagr"], sm["max_drawdown"], sm["sharpe_daily_252"]))
        q = pd.DataFrame(rows, columns=["end", "cagr", "spy_cagr", "maxdd", "sharpe"])
        out[str(years)] = {
            "windows": len(q),
            "cagr_min": float(q.cagr.min()), "cagr_p10": float(q.cagr.quantile(.1)),
            "cagr_median": float(q.cagr.median()), "cagr_max": float(q.cagr.max()),
            "fraction_positive": float((q.cagr > 0).mean()),
            "fraction_beating_spy": float((q.cagr > q.spy_cagr).mean()),
            "worst_window_end": str(q.loc[q.cagr.idxmin(), "end"].date()),
            "worst_window_cagr": float(q.cagr.min()),
            "worst_window_maxdd": float(q.loc[q.cagr.idxmin(), "maxdd"]),
        }
    return {"method": "monthly-ending rolling realized-path windows", "windows": out}


def temporal_leaveout(d):
    r = d[["date", "A_nav", "spy_nav"]].copy()
    r["r"] = r.A_nav.pct_change(); r["spy_r"] = r.spy_nav.pct_change(); r = r.dropna()
    r["year"] = r.date.dt.year
    years = sorted(r.year.unique()); rows = []
    for y in years:
        k = r[r.year != y]
        ann = 252.0
        c = float(np.prod(1 + k.r) ** (ann / len(k)) - 1)
        s = float(np.prod(1 + k.spy_r) ** (ann / len(k)) - 1)
        rows.append({"omitted_year": int(y), "strategy_annualized_geomean": c, "spy_annualized_geomean": s})
    return {
        "method": "descriptive return-path leave-one-calendar-year-out; NOT a causal strategy replay",
        "causal_replay": False,
        "rows": rows,
        "worst_strategy_geomean": min(x["strategy_annualized_geomean"] for x in rows),
        "best_strategy_geomean": max(x["strategy_annualized_geomean"] for x in rows),
    }


def block_bootstrap(d):
    a = _returns(d); s = _returns(d, "spy_nav"); n = len(a)
    rng = np.random.default_rng(20260907); B = 2500; block = 20
    cagr = np.empty(B); spy_cagr = np.empty(B); dd = np.empty(B)
    for b in range(B):
        idx = []
        while len(idx) < n:
            st = int(rng.integers(0, n)); idx.extend(((st + np.arange(block)) % n).tolist())
        ix = np.asarray(idx[:n]); rr = a[ix]; ss = s[ix]
        nav = np.cumprod(1 + rr); snav = np.cumprod(1 + ss)
        cagr[b] = nav[-1] ** (252 / n) - 1; spy_cagr[b] = snav[-1] ** (252 / n) - 1
        dd[b] = np.min(nav / np.maximum.accumulate(nav) - 1)
    def qs(x): return {str(q): float(np.quantile(x, q)) for q in (.01,.05,.1,.25,.5,.75,.9,.95,.99)}
    return {
        "method": "paired 20-session circular block bootstrap of realized Median-5/SPY daily returns",
        "draws": B, "block_sessions": block,
        "strategy_cagr_quantiles": qs(cagr), "max_drawdown_quantiles": qs(dd),
        "probability_positive_cagr": float(np.mean(cagr > 0)),
        "probability_beats_spy_cagr": float(np.mean(cagr > spy_cagr)),
    }


def contributor_concentration(d):
    if "research_selected_positions" not in d:
        raise RuntimeError("canonical evidence lacks selected-position witness")
    counts = {}
    total = 0
    for raw in d.research_selected_positions.fillna("[]"):
        ids = json.loads(raw)
        for sid in ids:
            counts[str(sid)] = counts.get(str(sid), 0) + 1; total += 1
    vals = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    shares = np.asarray([v / total for _, v in vals])
    def top(k): return float(shares[:k].sum()) if len(shares) else 0.0
    return {
        "method": "exact holding-day exposure concentration from certified selected-position witness",
        "scope": "exposure concentration only; this does NOT claim exact per-security P&L attribution",
        "unique_securities_held": len(vals), "total_holding_days": total,
        "hhi": float(np.sum(shares ** 2)), "effective_security_count": float(1 / np.sum(shares ** 2)),
        "top1_holding_day_share": top(1), "top5_holding_day_share": top(5), "top10_holding_day_share": top(10),
        "top20": [{"security_id": sid, "holding_days": int(v), "share": float(v/total)} for sid, v in vals[:20]],
        "limitation": "A true winner-contribution/removal test requires causal attribution telemetry or additional strategy replays and is not inferred from exposure.",
    }


def worst_regime(d):
    x = d[["date", "A_nav", "spy_nav"]].copy().set_index("date")
    x["r"] = x.A_nav.pct_change(); x["spy_r"] = x.spy_nav.pct_change()
    x["spy_vol63"] = x.spy_r.rolling(63).std() * math.sqrt(252)
    medvol = float(x.spy_vol63.median())
    x["regime"] = np.where(x.spy_vol63 >= medvol, "HIGH_SPY_VOL", "LOW_SPY_VOL")
    reg = {}
    for name, g in x.dropna().groupby("regime"):
        reg[name] = {
            "sessions": int(len(g)),
            "strategy_geomean_annualized": float(np.prod(1 + g.r) ** (252 / len(g)) - 1),
            "spy_geomean_annualized": float(np.prod(1 + g.spy_r) ** (252 / len(g)) - 1),
        }
    yr = []
    for y, g in x.dropna(subset=["r"]).groupby(x.dropna(subset=["r"]).index.year):
        yr.append({"year": int(y), "strategy_return": float(np.prod(1+g.r)-1), "spy_return": float(np.prod(1+g.spy_r)-1)})
    roll = x.A_nav / x.A_nav.shift(252) - 1
    i = roll.idxmin()
    return {
        "method": "descriptive contemporaneous SPY-volatility and calendar-period decomposition",
        "spy_vol63_median": medvol, "volatility_regimes": reg,
        "calendar_years": yr,
        "worst_252_session_end": str(i.date()), "worst_252_session_return": float(roll.loc[i]),
    }


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--mode", choices=MODES, required=True)
    ap.add_argument("--canonical", type=Path, required=True); ap.add_argument("--hardening", type=Path)
    ap.add_argument("--output", type=Path, required=True); a = ap.parse_args()
    d = _load_one(a.canonical)
    m = a.mode
    if m == "DSR": result = dsr(d)
    elif m == "PBO_CSCV": result = pbo_cscv(d, a.hardening)
    elif m == "REALITY_CHECK": result = reality_check(d, a.hardening)
    elif m == "ROLLING_WINDOWS": result = rolling_windows(d)
    elif m == "TEMPORAL_LEAVEOUT": result = temporal_leaveout(d)
    elif m == "BLOCK_BOOTSTRAP": result = block_bootstrap(d)
    elif m == "CONTRIBUTOR_CONCENTRATION": result = contributor_concentration(d)
    elif m == "WORST_REGIME": result = worst_regime(d)
    else: raise AssertionError(m)
    out = {
        "schema": "median5.statistical-closure/1", "mode": m,
        "canonical_sessions": 5032, "measurement_start": "2006-07-31", "measurement_end": "2026-07-31",
        "pit_source_required": True, "performance_target_used": False, "result": result,
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps(out, sort_keys=True))

if __name__ == "__main__": main()
