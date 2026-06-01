"""Unit tests for the fill-gated market-open drain planner (Option B).

Covers the trading-behaviour decisions confirmed in design:
  - sells submitted first; ALL sells filled before ANY buy
  - buys released one at a time within live buying power
  - unfunded buys expire at session close (never carry over)
  - a halted sell times out so it can't wedge the book forever
  - market-closed passes do nothing but expire overdue buys

The planner is pure (no Alpaca, no DB), so these run fast and deterministically.
"""
from datetime import datetime, timedelta, timezone

from app.drain import DeferredOrder, plan_drain

NOW = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
TIMEOUT = 300.0


def _o(oid, side, notional=1000.0, submitted_at=None, expires_at=None):
    return DeferredOrder(id=oid, side=side, notional=notional,
                         submitted_at=submitted_at, expires_at=expires_at)


def _plan(**kw):
    base = dict(
        is_open=True, now=NOW,
        deferred_sells=[], unfilled_submitted_sells=[], deferred_buys=[],
        buying_power=0.0, sell_fill_timeout_secs=TIMEOUT,
    )
    base.update(kw)
    return plan_drain(**base)


# ── sells-first / gate ────────────────────────────────────────────────────────

def test_sells_submitted_and_buys_held_same_pass():
    """First pass: sells go out, buys wait (sells not yet filled)."""
    d = _plan(
        deferred_sells=[_o("S1", "sell"), _o("S2", "sell")],
        deferred_buys=[_o("B1", "buy")],
        buying_power=100000.0,
    )
    assert d.submit_sells == ["S1", "S2"]
    assert d.submit_buys == []
    assert d.waiting_on_sells is True


def test_buys_held_while_submitted_sell_unfilled():
    """A sell submitted last pass but not yet filled still blocks buys."""
    d = _plan(
        unfilled_submitted_sells=[_o("S1", "sell", submitted_at=NOW - timedelta(seconds=30))],
        deferred_buys=[_o("B1", "buy")],
        buying_power=100000.0,
    )
    assert d.submit_buys == []
    assert d.waiting_on_sells is True


def test_buys_release_once_all_sells_filled():
    """No deferred and no unfilled sells ⇒ sells are done ⇒ buys release."""
    d = _plan(
        deferred_buys=[_o("B1", "buy", 1000.0), _o("B2", "buy", 2000.0)],
        buying_power=100000.0,
    )
    assert d.submit_sells == []
    assert d.waiting_on_sells is False
    assert d.submit_buys == ["B1", "B2"]


def test_pure_buy_day_releases_immediately():
    """No sells at all ⇒ buys are not gated."""
    d = _plan(deferred_buys=[_o("B1", "buy", 500.0)], buying_power=1000.0)
    assert d.submit_buys == ["B1"]
    assert d.waiting_on_sells is False


# ── buying-power gating, one at a time ────────────────────────────────────────

def test_buys_capped_by_buying_power_oldest_first():
    """Only buys that fit (oldest-first, subtracting as we go) are released."""
    d = _plan(
        deferred_buys=[_o("B1", "buy", 600.0), _o("B2", "buy", 600.0), _o("B3", "buy", 600.0)],
        buying_power=1000.0,   # fits B1 (→400 left), not B2
    )
    assert d.submit_buys == ["B1"]


def test_buys_pack_within_buying_power():
    d = _plan(
        deferred_buys=[_o("B1", "buy", 400.0), _o("B2", "buy", 400.0), _o("B3", "buy", 400.0)],
        buying_power=1000.0,   # B1+B2=800 fit, B3 would be 1200
    )
    assert d.submit_buys == ["B1", "B2"]


def test_no_buys_when_buying_power_unknown():
    d = _plan(deferred_buys=[_o("B1", "buy", 100.0)], buying_power=None)
    assert d.submit_buys == []


# ── expiry ────────────────────────────────────────────────────────────────────

def test_unfunded_buy_past_session_close_expires():
    past = NOW - timedelta(minutes=1)
    d = _plan(
        deferred_buys=[_o("B1", "buy", 100.0, expires_at=past)],
        buying_power=100000.0,
    )
    assert d.expire == ["B1"]
    assert "B1" not in d.submit_buys   # expired buys are never also submitted


def test_expiry_happens_even_when_market_closed():
    past = NOW - timedelta(minutes=1)
    d = _plan(
        is_open=False,
        deferred_buys=[_o("B1", "buy", 100.0, expires_at=past)],
    )
    assert d.expire == ["B1"]
    assert d.submit_sells == [] and d.submit_buys == []


# ── halted-sell timeout ───────────────────────────────────────────────────────

def test_timed_out_sell_stops_blocking_buys():
    """A sell submitted longer ago than the timeout no longer wedges buys."""
    old = NOW - timedelta(seconds=TIMEOUT + 60)
    d = _plan(
        unfilled_submitted_sells=[_o("S1", "sell", submitted_at=old)],
        deferred_buys=[_o("B1", "buy", 100.0)],
        buying_power=100000.0,
    )
    assert d.waiting_on_sells is False
    assert d.submit_buys == ["B1"]


# ── market closed ─────────────────────────────────────────────────────────────

def test_market_closed_submits_nothing():
    d = _plan(
        is_open=False,
        deferred_sells=[_o("S1", "sell")],
        deferred_buys=[_o("B1", "buy")],
        buying_power=100000.0,
    )
    assert d.submit_sells == [] and d.submit_buys == []
    assert d.waiting_on_sells is True   # there ARE sells pending, just not while closed
