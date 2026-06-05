"""Deposit-sweep: new cash deposited at the broker gets invested via weight drift.

There is no dedicated "cash sweep" — investing a deposit is an emergent property
of weight-targeting. The pipeline computes each holding's actual weight as
`market_value / account_value` (services/pipeline/app/main.py). When cash is
deposited, account_value grows while position market values don't, so every
holding's actual weight falls below its target. The delta engine sees that
under-weight drift and emits `buy_add` (sized by the executor against the larger
account_value), deploying the new cash up to target.

These tests pin that mechanism — and its limit: a deposit too small to push any
holding past `drift_threshold` does NOT generate buys (the idle cash simply waits).
See the "deposit-sweep" discussion in the architecture notes.
"""
import pytest

from app.engine import evaluate_target_vs_live, RankObservation


def _good_history(ticker_count_days: int = 3):
    """A flat, well-ranked history (rank 10) so rank never forces an exit/at_risk
    and the drift layer is what decides hold vs buy_add."""
    return [RankObservation(run_date=None, rank=10, composite_score=1.0)
            for _ in range(ticker_count_days)]


def _weights(positions: dict[str, float], account_value: float) -> dict[str, float]:
    """Mirror pipeline main.py: actual_weight = market_value / account_value."""
    return {t: mv / account_value for t, mv in positions.items()}


# Held book: targets exactly matched at a $100k account.
TARGET = {"AAPL": 0.10, "MSFT": 0.08, "NVDA": 0.12}
POSITIONS = {"AAPL": 10_000.0, "MSFT": 8_000.0, "NVDA": 12_000.0}
LIVE = set(TARGET)
UNIVERSE = {t: _good_history() for t in TARGET}

_COMMON = dict(
    target_portfolio=TARGET, live_positions=LIVE, universe=UNIVERSE,
    confirmation_days=3, max_positions=30,
    drift_threshold=0.02,
)


def test_before_deposit_all_on_target_hold():
    """Sanity: at the original account size, actual == target → all hold."""
    d = evaluate_target_vs_live(
        actual_weights=_weights(POSITIONS, 100_000.0), account_value=100_000.0, **_COMMON,
    )
    assert {t: d[t].action for t in TARGET} == {"AAPL": "hold", "MSFT": "hold", "NVDA": "hold"}


def test_large_deposit_dilutes_into_buy_adds():
    """Deposit $100k → account_value doubles → every holding diluted to ~half its
    target weight → under-weight beyond threshold → buy_add, carrying the FULL
    target weight so the executor sizes the new cash in."""
    d = evaluate_target_vs_live(
        actual_weights=_weights(POSITIONS, 200_000.0), account_value=200_000.0, **_COMMON,
    )
    assert all(d[t].action == "buy_add" for t in TARGET), {t: d[t].action for t in TARGET}
    # buy_add carries the target weight (not the diluted actual) so sizing targets
    # account_value × target_weight — i.e. it buys back UP to target.
    assert d["NVDA"].current_weight == pytest.approx(0.12)
    assert d["AAPL"].weight_drift < -0.02   # genuinely under-weight


def test_small_deposit_below_threshold_does_not_buy():
    """A deposit too small to move any holding past drift_threshold (2%) generates
    NO buys — the idle cash just waits. AAPL at 10% target only crosses the 2%
    threshold once its actual weight drops below 8%, i.e. account_value > $125k."""
    # +$2k → $102k. AAPL: 10000/102000 = 9.80% vs 10% target → drift -0.20% < 2%.
    d = evaluate_target_vs_live(
        actual_weights=_weights(POSITIONS, 102_000.0), account_value=102_000.0, **_COMMON,
    )
    assert all(d[t].action == "hold" for t in TARGET), {t: d[t].action for t in TARGET}


def test_deposit_at_threshold_boundary_for_largest_target():
    """Only holdings whose dilution exceeds the threshold flip to buy_add; smaller
    deposits touch the biggest-target names first. At $130k, NVDA (12% target) is
    diluted to 12000/130000 = 9.23% (drift -2.77%, > threshold → buy_add) while
    MSFT (8% target) is at 8000/130000 = 6.15% (drift -1.85%, < threshold → hold)."""
    d = evaluate_target_vs_live(
        actual_weights=_weights(POSITIONS, 130_000.0), account_value=130_000.0, **_COMMON,
    )
    assert d["NVDA"].action == "buy_add", d["NVDA"].reason
    assert d["MSFT"].action == "hold", d["MSFT"].reason
