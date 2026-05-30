"""Tests for the trailing-stop feature in the Alpaca simulator.

Two layers:
  - the pure tracker (app.trailing): HWM ratchet + trigger math
  - the simulator state machine (app.main._evaluate_trailing_stops): fills, cash,
    position bookkeeping, and cancel-on-position-gone — with _last_price mocked so
    no database is required.
"""
import pytest

from app.trailing import TrailingStopState, arm


# ── Pure tracker ───────────────────────────────────────────────────────────────

class TestTrailingStopState:
    def test_arm_sets_initial_stop_below_price(self):
        ts = arm(5.0, 100.0)
        assert ts.hwm == 100.0
        assert ts.stop_price == pytest.approx(95.0)

    def test_arm_rejects_non_positive_trail(self):
        with pytest.raises(ValueError):
            arm(0.0, 100.0)
        with pytest.raises(ValueError):
            arm(-5.0, 100.0)

    def test_no_trigger_on_arm_day(self):
        ts = arm(5.0, 100.0)
        assert ts.update(100.0) is False

    def test_hwm_ratchets_up_on_new_peak(self):
        ts = arm(5.0, 100.0)
        assert ts.update(110.0) is False
        assert ts.hwm == 110.0
        assert ts.stop_price == pytest.approx(104.5)

    def test_hwm_never_moves_down(self):
        ts = arm(5.0, 100.0)
        ts.update(120.0)            # peak
        ts.update(115.0)            # pullback, but < 5% from 120 (stop=114)
        assert ts.hwm == 120.0
        assert ts.stop_price == pytest.approx(114.0)

    def test_triggers_exactly_at_trail_distance_from_peak(self):
        ts = arm(5.0, 100.0)
        ts.update(110.0)            # peak 110 → stop 104.5
        assert ts.update(105.0) is False    # only -4.5% from peak
        assert ts.update(104.5) is True     # exactly -5% from peak → fill

    def test_triggers_on_sharp_drop_below_arm_price(self):
        ts = arm(5.0, 100.0)
        # Never rose; a hard -10% gap down is well past the 5% stop.
        assert ts.update(90.0) is True

    def test_ten_percent_trail(self):
        ts = arm(10.0, 50.0)
        ts.update(60.0)            # peak 60 → stop 54
        assert ts.update(55.0) is False
        assert ts.update(54.0) is True


# ── Simulator state machine (_evaluate_trailing_stops) ──────────────────────────

@pytest.fixture
def sim(monkeypatch):
    """Fresh simulator module with a clean STATE and a controllable price feed."""
    import app.main as m
    m.STATE.reset()
    prices: dict[str, float] = {}

    async def _fake_last_price(ticker: str):
        return prices.get(ticker)

    monkeypatch.setattr(m, "_last_price", _fake_last_price)
    return m, prices


def _arm_position(m, ticker, qty, entry, trail=5.0):
    """Seed a held position plus an open trailing stop on it (as submit_order would)."""
    m.STATE.positions[ticker] = m._Position(ticker, qty, entry)
    order = {
        "id": f"ord-{ticker}", "symbol": ticker, "side": "sell",
        "type": "trailing_stop", "status": "new", "qty": str(qty),
        "filled_qty": "0", "filled_avg_price": None, "hwm": entry,
        "canceled_at": None, "filled_at": None, "created_at": "t0",
    }
    m.STATE.orders.append(order)
    m.STATE.trailing_stops.append(
        m._TrailingStop(order["id"], ticker, float(qty), arm(trail, entry))
    )
    return order


@pytest.mark.asyncio
async def test_rise_then_drop_fills_and_credits_cash(sim):
    m, prices = sim
    m.STATE.cash = 0.0
    _arm_position(m, "AMD", qty=10, entry=100.0, trail=5.0)

    prices["AMD"] = 120.0
    assert await m._evaluate_trailing_stops() == []      # new peak, no fill
    assert m.STATE.trailing_stops[0].state.hwm == 120.0

    prices["AMD"] = 113.9                                 # -5.08% from 120 → trigger
    filled = await m._evaluate_trailing_stops()
    assert len(filled) == 1
    assert filled[0]["status"] == "filled"
    assert float(filled[0]["filled_avg_price"]) == pytest.approx(113.9)
    # Position closed, proceeds (10 * 113.9) credited to cash, stop removed.
    assert "AMD" not in m.STATE.positions
    assert m.STATE.cash == pytest.approx(1139.0)
    assert m.STATE.trailing_stops == []


@pytest.mark.asyncio
async def test_no_fill_while_within_trail(sim):
    m, prices = sim
    _arm_position(m, "MSFT", qty=5, entry=200.0, trail=5.0)
    prices["MSFT"] = 210.0
    await m._evaluate_trailing_stops()
    prices["MSFT"] = 202.0                                # -3.8% from 210 → hold
    assert await m._evaluate_trailing_stops() == []
    assert "MSFT" in m.STATE.positions
    assert len(m.STATE.trailing_stops) == 1


@pytest.mark.asyncio
async def test_stop_canceled_when_position_already_closed(sim):
    """The system sold the position via a normal market exit — the resting stop
    must cancel itself rather than fill against a non-existent position."""
    m, prices = sim
    order = _arm_position(m, "NVDA", qty=3, entry=400.0, trail=5.0)
    del m.STATE.positions["NVDA"]                         # closed elsewhere
    prices["NVDA"] = 300.0                                # would have triggered
    filled = await m._evaluate_trailing_stops()
    assert filled == []
    assert order["status"] == "canceled"
    assert m.STATE.trailing_stops == []


@pytest.mark.asyncio
async def test_missing_price_keeps_stop_open(sim):
    m, prices = sim
    _arm_position(m, "GAP", qty=1, entry=50.0, trail=5.0)
    # No price for GAP today → leave the stop resting, do not fill or cancel.
    filled = await m._evaluate_trailing_stops()
    assert filled == []
    assert len(m.STATE.trailing_stops) == 1
    assert "GAP" in m.STATE.positions
