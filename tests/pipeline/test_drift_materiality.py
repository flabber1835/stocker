"""Drift materiality gates + hold-safe/buy-closed risk failure mode
(external audit findings #7 and #8).

#7: the absolute drift threshold alone treats 2pp on a 20% position (10%
relative) like 2pp on a 2% position (100% relative), and can fire trades whose
dollar value is below any practical minimum. Two opt-in gates — relative drift
and dollar trade value — default OFF so existing behavior is untouched.

#8: when the builder's book-vol estimate is unusable while vol targeting is
enabled, risk must not INCREASE: entries and buy_adds defer (buy-closed) while
exits and sell_trims proceed (hold-safe, de-risking always allowed).
"""
from datetime import date

from app.engine import RankObservation, evaluate_target_vs_live


def _obs(rank=5):
    return [RankObservation(run_date=date(2026, 7, 17), rank=rank, composite_score=0.9)]


def _run(target, held, actual, **kw):
    return evaluate_target_vs_live(
        target_portfolio=target,
        live_positions=held,
        universe={t: _obs() for t in set(target) | held},
        confirmation_days=3,
        max_positions=30,
        actual_weights=actual,
        **kw,
    )


# ── defaults off → behavior unchanged ────────────────────────────────────────

def test_gates_default_off_small_drift_still_fires():
    d = _run({"AAA": 0.02}, {"AAA"}, {"AAA": 0.045}, drift_threshold=0.02)
    assert d["AAA"].action == "sell_trim"          # 2.5pp > 2pp, no gates


# ── #7 relative-drift gate ───────────────────────────────────────────────────

def test_relative_gate_passes_big_relative_drift():
    # 2% target, actual 4.5% → 125% relative — well past a 50% floor
    d = _run({"AAA": 0.02}, {"AAA"}, {"AAA": 0.045},
             drift_threshold=0.02, min_relative_drift=0.5)
    assert d["AAA"].action == "sell_trim"


def test_relative_gate_suppresses_small_relative_drift():
    # 20% target, actual 22.5% → 2.5pp absolute (over threshold) but only
    # 12.5% relative — under the 50% floor → hold, with the reason explaining
    d = _run({"AAA": 0.20}, {"AAA"}, {"AAA": 0.225},
             drift_threshold=0.02, min_relative_drift=0.5)
    assert d["AAA"].action == "hold"
    assert "materiality" in d["AAA"].reason


# ── #7 dollar-value gate ─────────────────────────────────────────────────────

def test_dollar_gate_suppresses_micro_trades():
    # 2.5pp drift on a $10k account = $250 < $500 floor → hold
    d = _run({"AAA": 0.02}, {"AAA"}, {"AAA": 0.045},
             drift_threshold=0.02, min_trade_value=500.0, account_value=10_000.0)
    assert d["AAA"].action == "hold"
    assert "materiality" in d["AAA"].reason


def test_dollar_gate_passes_material_trades():
    # same drift on a $100k account = $2,500 ≥ $500 → trim fires
    d = _run({"AAA": 0.02}, {"AAA"}, {"AAA": 0.045},
             drift_threshold=0.02, min_trade_value=500.0, account_value=100_000.0)
    assert d["AAA"].action == "sell_trim"


def test_dollar_gate_skipped_when_account_value_unknown():
    # unknown equity must never blindly block a rebalance (permissive skip)
    d = _run({"AAA": 0.02}, {"AAA"}, {"AAA": 0.045},
             drift_threshold=0.02, min_trade_value=500.0, account_value=None)
    assert d["AAA"].action == "sell_trim"


# ── #8 hold-safe / buy-closed ────────────────────────────────────────────────

def test_risk_degraded_defers_entries_to_watch():
    d = _run({"NEW": 0.03}, set(), None, risk_degraded=True)
    assert d["NEW"].action == "watch"
    assert "buy-closed" in d["NEW"].reason


def test_risk_degraded_defers_buy_add_but_not_sell_trim():
    d = _run({"UND": 0.05, "OVR": 0.02}, {"UND", "OVR"},
             {"UND": 0.01, "OVR": 0.06},
             drift_threshold=0.02, risk_degraded=True)
    assert d["UND"].action == "hold"               # buy_add deferred
    assert "buy-closed" in d["UND"].reason
    assert d["OVR"].action == "sell_trim"          # de-risking proceeds


def test_risk_degraded_never_blocks_orphan_exit():
    # held name absent from target must still exit on schedule — hold-safe
    # means no forced liquidation on MISSING risk data, not no de-risking
    d = _run({"AAA": 0.5}, {"AAA", "GONE"}, {"AAA": 0.5, "GONE": 0.1},
             risk_degraded=True, orphan_confirmation_days=1)
    assert d["GONE"].action == "exit"


def test_risk_ok_entries_unaffected():
    d = _run({"NEW": 0.03}, set(), None, risk_degraded=False)
    assert d["NEW"].action == "entry"
