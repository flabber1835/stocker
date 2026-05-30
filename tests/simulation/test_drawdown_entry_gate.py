"""Unit tests for the drawdown entry-timing gate (prototype).

The gate defers `entry` intents for names in free-fall (price far below their
trailing peak), demoting entry -> watch. It must NEVER touch held positions,
buy_adds, exits, sell_trims, or holds.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "tests", "simulation"))

from app.engine import DeltaDecision  # noqa: E402
from drawdown_entry_gate_sim import drawdown_entry_gate, trailing_drawdowns  # noqa: E402
import numpy as np  # noqa: E402


def _entry(tk, rank=5):
    return DeltaDecision(ticker=tk, action="entry", rank=rank, composite_score=1.0,
                         confirmation_days_met=3, current_weight=0.05, reason="")


def _mk(tk, action, **kw):
    base = dict(ticker=tk, action=action, rank=10, composite_score=0.5,
                confirmation_days_met=3, current_weight=0.04, reason="")
    base.update(kw)
    return DeltaDecision(**base)


def test_defers_entry_in_freefall():
    decisions = {"AAA": _entry("AAA")}
    deferred = drawdown_entry_gate(decisions, {"AAA": -0.25}, max_drawdown=0.15)
    assert deferred == ["AAA"]
    assert decisions["AAA"].action == "watch"
    assert decisions["AAA"].current_weight is None
    assert "free-fall" in decisions["AAA"].reason


def test_keeps_entry_within_threshold():
    decisions = {"AAA": _entry("AAA")}
    deferred = drawdown_entry_gate(decisions, {"AAA": -0.10}, max_drawdown=0.15)
    assert deferred == []
    assert decisions["AAA"].action == "entry"


def test_threshold_is_exclusive_boundary():
    # exactly -15% with limit 15% should NOT defer (needs strictly worse)
    decisions = {"AAA": _entry("AAA")}
    drawdown_entry_gate(decisions, {"AAA": -0.15}, max_drawdown=0.15)
    assert decisions["AAA"].action == "entry"


def test_missing_drawdown_does_not_defer():
    decisions = {"AAA": _entry("AAA")}
    drawdown_entry_gate(decisions, {}, max_drawdown=0.15)
    assert decisions["AAA"].action == "entry"


def test_never_touches_non_entry_actions():
    decisions = {
        "HOLD": _mk("HOLD", "hold"),
        "ADD": _mk("ADD", "buy_add", weight_drift=-0.03),
        "EXIT": _mk("EXIT", "exit"),
        "TRIM": _mk("TRIM", "sell_trim", weight_drift=0.03),
        "WATCH": _mk("WATCH", "watch"),
    }
    # every one is deep in drawdown — must still be untouched (gate is entry-only)
    dd = {t: -0.40 for t in decisions}
    deferred = drawdown_entry_gate(decisions, dd, max_drawdown=0.15)
    assert deferred == []
    assert decisions["HOLD"].action == "hold"
    assert decisions["ADD"].action == "buy_add"      # buy_add NOT gated (already held)
    assert decisions["EXIT"].action == "exit"
    assert decisions["TRIM"].action == "sell_trim"
    assert decisions["WATCH"].action == "watch"


def test_only_freefall_entries_among_many():
    decisions = {
        "OK": _entry("OK", rank=3),
        "KNIFE": _entry("KNIFE", rank=8),
    }
    deferred = drawdown_entry_gate(decisions, {"OK": -0.05, "KNIFE": -0.30}, max_drawdown=0.15)
    assert deferred == ["KNIFE"]
    assert decisions["OK"].action == "entry"
    assert decisions["KNIFE"].action == "watch"


# ── trailing_drawdowns price math ────────────────────────────────────────────

def test_trailing_drawdown_at_peak_is_zero():
    prices = np.array([[100.0], [110.0], [120.0]])  # rising → at peak today
    dd = trailing_drawdowns(prices, gt=2, window=21)
    assert dd[0] == 0.0


def test_trailing_drawdown_below_peak():
    prices = np.array([[100.0], [120.0], [90.0]])   # peak 120, now 90
    dd = trailing_drawdowns(prices, gt=2, window=21)
    assert dd[0] == np.float64(90.0 / 120.0 - 1.0)


def test_trailing_drawdown_window_limits_lookback():
    # window=2 only sees days 1 and 2 → peak 120 (day0's 100 ignored), now 90
    prices = np.array([[100.0], [120.0], [90.0]])
    dd = trailing_drawdowns(prices, gt=2, window=2)
    assert abs(dd[0] - (90.0 / 120.0 - 1.0)) < 1e-12
