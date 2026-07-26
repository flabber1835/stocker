"""Seasonal-random-walk SUE — the definition both stacks can compute.

Live's original SUE was (reported − estimated); Sharadar carries no analyst
estimates, so the wind tunnel refused every config weighting the factor. Rather
than delete the factor (letting the test rig dictate the strategy) or buy an
estimates history, both sides moved to eps_q − eps_{q-4} standardized by the
ticker's own history — Foster-Olsen-Shevlin (1984).

The properties that matter are the ones a positional implementation would get
subtly wrong: alignment by fiscal PERIOD, point-in-time visibility, and never
falling back to the other method when a column is missing.
"""
import datetime as dt

import pandas as pd
import pytest

from app.factors import compute_earnings_surprise

Q = "seasonal_random_walk"
A = "analyst"


def _rows(specs) -> pd.DataFrame:
    """specs: [(fiscal_date_ending, reported_date, eps, estimated)]"""
    return pd.DataFrame([
        {"ticker": "AAA", "fiscal_date_ending": dt.date.fromisoformat(f),
         "reported_date": dt.date.fromisoformat(r),
         "reported_eps": e, "estimated_eps": est}
        for f, r, e, est in specs])


def _growing(i: float) -> float:
    """Growing EPS whose YoY DELTA varies.

    A perfectly linear series (1.0 + 0.05i) has a constant year-over-year delta,
    hence zero dispersion, hence an undefined standardized value — correct
    behaviour (a delta that never varies is not a surprise) but a degenerate
    fixture. Real earnings vary; so does this."""
    return 1.0 + 0.05 * i + 0.02 * ((i * 7) % 5)


def _quarters(n, eps_fn, start_year=2020, est_fn=None):
    """n consecutive quarters, reported ~45 days after period end."""
    out = []
    for i in range(n):
        y, q = start_year + i // 4, i % 4
        fde = dt.date(y, [3, 6, 9, 12][q], 28)
        rep = fde + dt.timedelta(days=45)
        out.append((fde.isoformat(), rep.isoformat(), eps_fn(i),
                    None if est_fn is None else est_fn(i)))
    return out


# ── the definition ──────────────────────────────────────────────────────────

def test_srw_measures_growth_against_the_YEAR_AGO_quarter():
    """Not the previous quarter. A seasonal business earns more in Q4 every year;
    comparing consecutive quarters would read that seasonality as a surprise."""
    # Strong seasonality, ZERO year-over-year growth: every quarter equals its
    # own year-ago counterpart, so every unexpected is 0.
    seasonal = [1.0, 2.0, 1.5, 8.0]
    df = _rows(_quarters(12, lambda i: seasonal[i % 4]))
    out = compute_earnings_surprise(df, dt.date(2022, 12, 1), drift_window_days=400,
                                    method=Q)
    # All unexpecteds are 0 → stdev 0 → no signal, NOT a huge Q4 "surprise".
    assert pd.isna(out.get("AAA")), (
        "flat year-over-year earnings produced a surprise — the comparison is "
        "against the wrong period")


def test_a_real_year_over_year_beat_is_positive():
    df = _rows(_quarters(12, _growing))                   # YoY growth
    out = compute_earnings_surprise(df, dt.date(2022, 12, 1), drift_window_days=400,
                                    method=Q)
    assert out["AAA"] > 0


def test_a_year_over_year_miss_is_negative():
    # Growing, then the last quarter collapses below its year-ago counterpart.
    eps = [_growing(i) for i in range(11)] + [0.2]
    df = _rows(_quarters(12, lambda i: eps[i]))
    # as_of AFTER the collapsed quarter's FILING date (period end + 45d), not
    # merely after its period end — otherwise point-in-time correctly hides it
    # and the test reads the previous, growing quarter.
    out = compute_earnings_surprise(df, dt.date(2023, 3, 1), drift_window_days=400,
                                    method=Q)
    assert out["AAA"] < 0


def test_it_is_standardized_by_the_tickers_own_history():
    """Two names with the SAME absolute beat but different surprise volatility
    must not score the same — that is the whole point of SUE over raw surprise."""
    steady = _rows(_quarters(12, _growing))
    noisy_eps = [_growing(i) + (0.9 if i % 2 else -0.9) for i in range(11)]
    noisy_eps.append(steady["reported_eps"].iloc[-1])
    noisy = _rows(_quarters(12, lambda i: noisy_eps[i]))
    a = compute_earnings_surprise(steady, dt.date(2022, 12, 1),
                                  drift_window_days=400, method=Q)["AAA"]
    b = compute_earnings_surprise(noisy, dt.date(2022, 12, 1),
                                  drift_window_days=400, method=Q)["AAA"]
    assert abs(a) > abs(b), "a chronically noisy reporter was not damped"


# ── alignment: what a positional lookup gets wrong ──────────────────────────

def test_a_missing_quarter_does_not_shift_the_comparison():
    """THE reason alignment is by fiscal_date_ending and not iloc[-5]. Drop one
    filing and a positional lookup silently compares against Q3 instead of Q4."""
    full = _quarters(12, _growing)
    gapped = full[:5] + full[6:]          # one quarter never filed
    out = compute_earnings_surprise(_rows(gapped), dt.date(2022, 12, 1),
                                    drift_window_days=400, method=Q)
    # Still a sane positive growth signal, not a seasonality artifact.
    assert out["AAA"] > 0


def test_no_year_ago_quarter_means_no_signal():
    """A newly listed company has nothing to compare against. Inventing one would
    be a fabricated factor value."""
    df = _rows(_quarters(3, lambda i: 1.0 + i))
    out = compute_earnings_surprise(df, dt.date(2020, 12, 1), drift_window_days=400,
                                    method=Q)
    assert out.empty or pd.isna(out.get("AAA"))


def test_fiscal_calendar_drift_within_tolerance_still_matches():
    """52/53-week fiscal calendars move period ends by days. A strict 365-day
    equality would drop those names entirely."""
    specs = _quarters(12, _growing)
    shifted = []
    for i, (f, r, e, est) in enumerate(specs):
        fd = dt.date.fromisoformat(f) + dt.timedelta(days=(i % 3))
        shifted.append((fd.isoformat(), r, e, est))
    out = compute_earnings_surprise(_rows(shifted), dt.date(2022, 12, 1),
                                    drift_window_days=400, method=Q)
    assert not pd.isna(out.get("AAA"))


# ── shared guarantees: unchanged by the method ──────────────────────────────

def test_point_in_time_is_enforced_for_srw():
    """A quarter reported AFTER as_of must be invisible. This is the property the
    whole backtest rests on."""
    df = _rows(_quarters(12, _growing))
    early = compute_earnings_surprise(df, dt.date(2022, 2, 1),
                                      drift_window_days=400, method=Q)
    late = compute_earnings_surprise(df, dt.date(2022, 12, 1),
                                     drift_window_days=400, method=Q)
    assert early.get("AAA") != late.get("AAA")


def test_the_drift_window_still_neutralizes_a_stale_report():
    df = _rows(_quarters(12, _growing))
    out = compute_earnings_surprise(df, dt.date(2025, 1, 1), drift_window_days=90,
                                    method=Q)
    assert pd.isna(out.get("AAA")), "a two-year-old report still carried a signal"


# ── method selection: never a silent fallback ───────────────────────────────

def test_srw_without_fiscal_dates_yields_nothing_rather_than_the_other_method():
    """Falling back to the analyst formula would compute a DIFFERENT factor under
    the requested name — the exact failure this whole thread is about."""
    df = _rows(_quarters(12, _growing,
                         est_fn=lambda i: 1.0)).drop(columns=["fiscal_date_ending"])
    assert compute_earnings_surprise(df, dt.date(2022, 12, 1), method=Q).empty


def test_analyst_without_estimates_yields_nothing_rather_than_srw():
    df = _rows(_quarters(12, _growing)).drop(columns=["estimated_eps"])
    assert compute_earnings_surprise(df, dt.date(2022, 12, 1), method=A).empty


def test_the_two_methods_give_different_answers_on_the_same_data():
    """If they agreed, the parity work would have been pointless. Estimates that
    track earnings closely give a near-zero analyst surprise while YoY growth is
    strongly positive."""
    df = _rows(_quarters(12, _growing, est_fn=lambda i: _growing(i) - 0.001))
    srw = compute_earnings_surprise(df, dt.date(2022, 12, 1),
                                    drift_window_days=400, method=Q)["AAA"]
    ana = compute_earnings_surprise(df, dt.date(2022, 12, 1),
                                    drift_window_days=400, method=A)["AAA"]
    assert srw > 0
    assert srw != ana


def test_empty_input_is_inert_under_both_methods():
    for m in (Q, A):
        assert compute_earnings_surprise(pd.DataFrame(), dt.date(2024, 1, 1),
                                         method=m).empty
        assert compute_earnings_surprise(None, dt.date(2024, 1, 1), method=m).empty


# ── the config wiring ───────────────────────────────────────────────────────

def test_the_active_config_uses_the_computable_method():
    import os

    import yaml
    from stock_strategy_shared.schemas.strategy import StrategyConfig
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    with open(os.path.join(root, "strategies", "momentum_rotation_v2.yaml")) as f:
        cfg = StrategyConfig(**yaml.safe_load(f))
    assert cfg.factor_engine.sue_method == "seasonal_random_walk", (
        "the active config weights earnings_surprise, so it must use the method "
        "the wind tunnel can also compute — otherwise it is unscorable")


def test_a_perfectly_constant_yoy_delta_yields_no_signal():
    """Documents the edge the first draft of these fixtures tripped over: a
    company growing EPS by exactly the same amount every year has zero surprise
    DISPERSION, so the standardized value is undefined. That is correct — a delta
    that never varies is not a surprise — and it is why the fixtures above use a
    varying growth series."""
    df = _rows(_quarters(12, lambda i: 1.0 + 0.05 * i))
    out = compute_earnings_surprise(df, dt.date(2022, 12, 1),
                                    drift_window_days=400, method=Q)
    assert pd.isna(out.get("AAA"))


# ── scaling guard ───────────────────────────────────────────────────────────

def test_srw_costs_no_more_than_a_few_analyst_passes():
    """The first SRW implementation was O(q²) per ticker: every row linearly
    scanned ALL of the ticker's periods with Python-level date arithmetic — and
    the fallback-reference helper did it AGAIN. Across a live universe with
    decades of AV history that made the factor step visibly slower on the NAS
    the day it shipped, reading as "stuck on calculating factors".

    Guarded as a ratio against the ANALYST method ON THE SAME FRAME — same
    machine, same data, same groupby overhead, and analyst is a vectorized O(q)
    subtraction. That internal control is what makes the bound meaningful:
    the first draft compared q=40 vs q=200 wall-clock and measured the OLD
    quadratic at 7.7x against a threshold of 8 — a guard that misses the very
    bug it was written for. Calibrated here: old 14.5x, new 2.8x; 8 splits them
    with ~2x margin on both sides, on any machine.
    """
    import time

    rows = []
    for t in range(300):
        for i in range(200):
            y, qq = 1975 + i // 4, i % 4
            fde = dt.date(y, [3, 6, 9, 12][qq], 28)
            rows.append({"ticker": f"S{t:04d}", "fiscal_date_ending": fde,
                         "reported_date": fde + dt.timedelta(days=45),
                         "reported_eps": 1.0 + 0.01 * i + 0.001 * ((i * 7) % 5),
                         "estimated_eps": 1.0 + 0.01 * i})
    df = pd.DataFrame(rows)

    def _time(method):
        best = float("inf")
        for _ in range(2):                      # best-of-2 damps scheduler noise
            t0 = time.perf_counter()
            compute_earnings_surprise(df, dt.date(2026, 7, 25),
                                      drift_window_days=100000, method=method)
            best = min(best, time.perf_counter() - t0)
        return best

    srw, analyst = _time(Q), _time(A)
    ratio = srw / max(analyst, 1e-9)
    assert ratio < 8, (
        f"SRW costs {ratio:.1f}x the analyst pass on identical data — the "
        f"alignment has gone super-linear in history length again "
        f"(srw {srw:.2f}s vs analyst {analyst:.2f}s)")
