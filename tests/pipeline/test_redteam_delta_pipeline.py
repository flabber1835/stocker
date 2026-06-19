"""Red-team regressions for three confirmed pipeline bugs:

D1 — share-class dedup stranding + slot erosion. A broker position held in a
     share-class that lost the dedup (e.g. GOOG when GOOGL ranks better) has no
     ranking obs, so the delta engine used to hit the data-gap branch and HOLD it
     forever (data-gap exemption) AND burn a capacity slot. Fixed by threading a
     loser→survivor map (dedup_survivors) into evaluate_target_vs_live: held loser
     whose survivor IS in target → held (same company); survivor NOT in target →
     normal orphan path (orphan-exits). Genuine data gaps stay exempt.

E2 — staleness on near_high / volume_surge. Both scored ~1.0 on forward-filled /
     positional-window data for a halted/delisted ticker. Fixed with the same
     7-trading-day staleness drop compute_liquidity / the pipeline _stale uses.

E1 — display excess-drawdown parity. _excess_drawdown_map_from_rows must equal the
     vetter's excess_drawdown + beta_and_idio_vol on a shared fixture (beta clamp
     [0,3]; beta regressed over the last lookback+1 common dates).
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from app.engine import evaluate_target_vs_live, RankObservation
from app.factors import compute_near_high, compute_volume_surge
from app.main import _excess_drawdown_map_from_rows


# ─────────────────────────── D1: dedup-loser routing ───────────────────────────

def _obs(rank, score=1.0, d=date(2025, 1, 2)):
    return [RankObservation(run_date=d, rank=rank, composite_score=score)]


def test_dedup_loser_with_survivor_in_target_is_held_not_orphan():
    """Broker holds GOOG (dedup loser, no obs). GOOGL (survivor) IS in the target.
    The held GOOG must be HELD (same company), NOT stranded as a data-gap hold and
    NOT orphaned."""
    target = {"GOOGL": 0.1, "AAA": 0.1}
    live = {"GOOG", "GOOGL", "AAA"}
    universe = {"GOOGL": _obs(1), "AAA": _obs(2)}  # GOOG absent (deduped out)
    decisions = evaluate_target_vs_live(
        target_portfolio=target,
        live_positions=live,
        universe=universe,
        confirmation_days=2,
        max_positions=30,
        target_history=[{"GOOGL", "AAA"}],
        orphan_confirmation_days=2,
        dedup_survivors={"GOOG": "GOOGL"},
    )
    assert decisions["GOOG"].action == "hold"
    assert "survivor GOOGL is in target" in decisions["GOOG"].reason
    # And it's clearly distinguished from the genuine data-gap reason.
    assert "awaiting price/fundamentals" not in decisions["GOOG"].reason


def test_dedup_loser_with_survivor_absent_orphan_exits_not_data_gap_exempt():
    """Broker holds GOOG (dedup loser). The survivor GOOGL is NOT in the target
    (builder dropped the company). GOOG must orphan-exit after the confirmation
    window — NOT be held forever under the data-gap exemption."""
    target = {"AAA": 0.1}                 # company dropped: neither GOOG nor GOOGL
    live = {"GOOG", "AAA"}
    universe = {"GOOGL": _obs(40), "AAA": _obs(1)}  # survivor still ranked, just not targeted
    # GOOG absent from target across 2 consecutive builds → exit at orphan_conf=2.
    th = [{"AAA"}, {"AAA"}]
    decisions = evaluate_target_vs_live(
        target_portfolio=target,
        live_positions=live,
        universe=universe,
        confirmation_days=2,
        max_positions=30,
        target_history=th,
        orphan_confirmation_days=2,
        dedup_survivors={"GOOG": "GOOGL"},
    )
    assert decisions["GOOG"].action == "exit"
    assert "awaiting price/fundamentals" not in decisions["GOOG"].reason


def test_dedup_loser_survivor_absent_at_risk_first_build():
    """Same but only one build absent (orphan_conf=2) → at_risk, not yet exit, and
    NOT held under the data-gap exemption."""
    decisions = evaluate_target_vs_live(
        target_portfolio={"AAA": 0.1},
        live_positions={"GOOG", "AAA"},
        universe={"GOOGL": _obs(40), "AAA": _obs(1)},
        confirmation_days=2,
        max_positions=30,
        target_history=[{"AAA"}],   # only the current build present
        orphan_confirmation_days=2,
        dedup_survivors={"GOOG": "GOOGL"},
    )
    assert decisions["GOOG"].action == "at_risk"


def test_genuine_data_gap_still_held_exempt():
    """A held name that is NEITHER ranked NOR a dedup loser stays exempt (held) —
    behavior must be unchanged for true data gaps."""
    decisions = evaluate_target_vs_live(
        target_portfolio={"AAA": 0.1},
        live_positions={"ZZZ", "AAA"},
        universe={"AAA": _obs(1)},     # ZZZ totally absent
        confirmation_days=2,
        max_positions=30,
        target_history=[{"AAA"}],
        orphan_confirmation_days=2,
        dedup_survivors={"GOOG": "GOOGL"},  # ZZZ not a dedup loser
    )
    assert decisions["ZZZ"].action == "hold"
    assert "awaiting price/fundamentals" in decisions["ZZZ"].reason


# ─────────────────────────── E2: staleness guards ───────────────────────────

def _long(ticker, dates, volumes):
    return pd.DataFrame({
        "ticker": [ticker] * len(dates),
        "date": dates,
        "volume": volumes,
    })


def test_volume_surge_nan_for_stale_ticker():
    ref = date(2025, 6, 1)
    fresh_dates = [ref - timedelta(days=i) for i in range(80)][::-1]
    # FRESH ticker: 80 days ending at ref, recent volume surging.
    fresh_vol = [100.0] * 70 + [500.0] * 10
    # STALE ticker: 80 days but ending ~30 days before ref (halted).
    stale_dates = [ref - timedelta(days=i) for i in range(30, 110)][::-1]
    stale_vol = [100.0] * 70 + [500.0] * 10
    df = pd.concat([
        _long("FRESH", fresh_dates, fresh_vol),
        _long("STALE", stale_dates, stale_vol),
    ], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    out = compute_volume_surge(df, short_window=5, long_window=60, max_staleness_days=7)
    assert not pd.isna(out.get("FRESH"))          # fresh ticker scores
    assert pd.isna(out.get("STALE", float("nan")))  # stale ticker is NaN


def test_near_high_nan_for_stale_ticker():
    ref = date(2025, 6, 1)
    fresh_idx = pd.to_datetime([ref - timedelta(days=i) for i in range(60)][::-1])
    stale_idx = pd.to_datetime([ref - timedelta(days=i) for i in range(30, 90)][::-1])
    # Build a wide pivot (date × ticker). STALE only has real values on old dates;
    # on the recent dates its column is NaN (forward-fill would otherwise revive it).
    all_idx = fresh_idx.union(stale_idx)
    fresh = pd.Series(range(1, len(fresh_idx) + 1), index=fresh_idx, dtype=float)
    stale = pd.Series(range(1, len(stale_idx) + 1), index=stale_idx, dtype=float)
    pivot = pd.DataFrame(index=all_idx)
    pivot["FRESH"] = fresh.reindex(all_idx)
    pivot["STALE"] = stale.reindex(all_idx)
    pivot = pivot.sort_index()
    out = compute_near_high(pivot, window=252, max_staleness_days=7)
    assert not pd.isna(out.get("FRESH"))
    assert pd.isna(out.get("STALE", float("nan")))


def test_near_high_fresh_unaffected():
    """A non-stale ticker at its high still scores ~1.0 — the guard must not change
    the happy path."""
    idx = pd.to_datetime([date(2025, 6, 1) - timedelta(days=i) for i in range(30)][::-1])
    s = pd.Series([10.0] * 29 + [20.0], index=idx)  # last value is the high
    pivot = pd.DataFrame({"AAA": s})
    out = compute_near_high(pivot, window=252)
    assert abs(out["AAA"] - 1.0) < 1e-9


# ─────────────────────────── E1: excess-drawdown parity ───────────────────────────

def _row(ticker, d, close):
    return SimpleNamespace(ticker=ticker, date=d, adjusted_close=close)


def _vetter_excess(stock_closes, spy_closes, window=21, lookback=120,
                   beta_floor=0.0, beta_cap=3.0, baseline_window=3):
    """Re-implement the vetter's excess_drawdown + beta_and_idio_vol semantics
    (services/llm-vetter/app/drawdown.py) on already date-aligned, positive-price
    close lists, so we can assert byte-for-byte parity without importing the vetter
    package (different service path). Includes the round-trip baseline suppression
    (baseline_window) so it still mirrors the shared formula both services use."""
    # beta + idio_vol over the last lookback+1 aligned closes
    s = list(stock_closes)[-(lookback + 1):]
    m = list(spy_closes)[-(lookback + 1):]
    n = min(len(s), len(m))
    rs, rm = [], []
    for i in range(1, n):
        rs.append(s[i] / s[i - 1] - 1.0)
        rm.append(m[i] / m[i - 1] - 1.0)
    k = len(rs)
    mean_m = sum(rm) / k
    var_m = sum((x - mean_m) ** 2 for x in rm)
    mean_s = sum(rs) / k
    cov = sum((rs[i] - mean_s) * (rm[i] - mean_m) for i in range(k))
    raw_beta = cov / var_m
    resid = [rs[i] - raw_beta * rm[i] for i in range(k)]
    mean_r = sum(resid) / k
    var_r = sum((x - mean_r) ** 2 for x in resid) / max(k - 1, 1)
    idio_vol = (var_r ** 0.5) * (252 ** 0.5)
    beta = min(max(raw_beta, beta_floor), beta_cap)
    sw = list(stock_closes)[-window:]
    mw = list(spy_closes)[-window:]
    peak = max(sw)
    peak_i = sw.index(peak)
    raw_dd = sw[-1] / peak - 1.0
    spy_move = mw[-1] / mw[peak_i] - 1.0
    if baseline_window and baseline_window > 0:
        bw = min(baseline_window, len(sw))
        base_s = sum(sw[:bw]) / bw
        base_m = sum(mw[:bw]) / bw
        if base_s > 0 and base_m > 0:
            net_dd = sw[-1] / base_s - 1.0
            if net_dd >= raw_dd:
                raw_dd = min(0.0, net_dd)
                spy_move = mw[-1] / base_m - 1.0
    return {"excess_dd": raw_dd - beta * spy_move, "idio_vol": idio_vol}


def test_pipeline_excess_matches_vetter_handcompute():
    """The pipeline excess-drawdown map equals the vetter's excess_drawdown on a
    shared fixture where stock and SPY share every trading date."""
    # 61 aligned closes (= 60 returns) with var > 0 in SPY and an idiosyncratic stock.
    d0 = date(2025, 1, 1)
    spy_rets = [0.01, -0.02, 0.015, -0.01, 0.005, -0.025] * 10
    stk_rets = [0.012, -0.03, 0.02, -0.02, 0.004, -0.04] * 10  # idiosyncratic, net down

    def _build(rets, start):
        px, vals = start, [start]
        for r in rets:
            px *= (1 + r)
            vals.append(px)
        return vals

    spy_vals = _build(spy_rets, 400.0)
    stk_vals = _build(stk_rets, 100.0)
    dates = [d0 + timedelta(days=i) for i in range(len(spy_vals))]
    spy_rows = [_row("SPY", dates[i], spy_vals[i]) for i in range(len(dates))]
    stk_rows = [_row("XYZ", dates[i], stk_vals[i]) for i in range(len(dates))]

    m = _excess_drawdown_map_from_rows(
        stk_rows, spy_rows, window=21, lookback=120, min_obs=10,
        beta_floor=0.0, beta_cap=3.0,
    )
    expected = _vetter_excess(stk_vals, spy_vals, window=21, lookback=120)
    assert "XYZ" in m
    assert abs(m["XYZ"]["excess_dd"] - expected["excess_dd"]) < 1e-9
    assert abs(m["XYZ"]["idio_vol"] - expected["idio_vol"]) < 1e-9


def test_pipeline_excess_beta_window_matches_vetter_with_long_history():
    """When fetched history runs LONGER than lookback+1, the pipeline must regress
    beta over only the last lookback+1 common dates (the vetter's slice), not all
    of them — otherwise the displayed excess would diverge from the veto."""
    d0 = date(2024, 1, 1)
    n = 200  # well beyond lookback+1 = 121
    dates = [d0 + timedelta(days=i) for i in range(n)]
    spy_rets = [0.01, -0.02, 0.015, -0.018, 0.006, -0.022] * 40
    stk_rets = [0.013, -0.028, 0.019, -0.021, 0.003, -0.035] * 40

    def _build(rets, start):
        px, vals = start, [start]
        for r in rets:
            px *= (1 + r)
            vals.append(px)
        return vals[:n]

    spy_vals = _build(spy_rets, 400.0)
    stk_vals = _build(stk_rets, 100.0)
    spy_rows = [_row("SPY", dates[i], spy_vals[i]) for i in range(n)]
    stk_rows = [_row("XYZ", dates[i], stk_vals[i]) for i in range(n)]

    m = _excess_drawdown_map_from_rows(
        stk_rows, spy_rows, window=21, lookback=120, min_obs=10,
    )
    expected = _vetter_excess(stk_vals, spy_vals, window=21, lookback=120)
    assert abs(m["XYZ"]["excess_dd"] - expected["excess_dd"]) < 1e-9
    assert abs(m["XYZ"]["idio_vol"] - expected["idio_vol"]) < 1e-9
