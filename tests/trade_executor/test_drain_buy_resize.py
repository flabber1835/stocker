"""Audit P1 — the drain trims a deferred BUY down to available buying power instead
of expiring it unfunded.

A buy sized on account_value can land a few shares over the cash its funding sells
freed (fees/price drift). Rather than letting it expire at the close (the reported
"insufficient funds / entry never fills"), plan_drain re-sizes it to what BP affords,
provided the trimmed order is still >= min_fill_ratio of the intended shares.
Trimming down is strictly within the approved order, so no re-approval is needed.
"""
from datetime import datetime, timezone

from app.drain import DeferredOrder, plan_drain

NOW = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)


def _o(oid, side, notional=1000.0, qty=10.0, submitted_at=None, expires_at=None):
    return DeferredOrder(id=oid, side=side, notional=notional, qty=qty,
                         submitted_at=submitted_at, expires_at=expires_at)


def _plan(**kw):
    base = dict(
        is_open=True, now=NOW,
        deferred_sells=[], unfilled_submitted_sells=[], deferred_buys=[],
        buying_power=0.0, sell_fill_timeout_secs=300.0,
    )
    base.update(kw)
    return plan_drain(**base)


def test_full_fit_no_resize():
    d = _plan(deferred_buys=[_o("B1", "buy", notional=1000.0, qty=10.0)], buying_power=1000.0)
    assert d.submit_buys == ["B1"]
    assert d.resized == {}


def test_slightly_over_resizes_down():
    # price 100; bp 950 → 9 shares (90% of 10) ≥ 0.5 floor → trim & submit
    d = _plan(deferred_buys=[_o("B1", "buy", notional=1000.0, qty=10.0)], buying_power=950.0)
    assert d.submit_buys == ["B1"]
    assert d.resized == {"B1": 9.0}


def test_below_min_fill_ratio_is_skipped():
    # price 100; bp 300 → 3 shares (30%) < 0.5 floor → not submitted, not resized
    d = _plan(deferred_buys=[_o("B1", "buy", notional=1000.0, qty=10.0)], buying_power=300.0)
    assert d.submit_buys == []
    assert d.resized == {}


def test_cannot_afford_one_share_is_skipped():
    d = _plan(deferred_buys=[_o("B1", "buy", notional=1000.0, qty=10.0)], buying_power=50.0)
    assert d.submit_buys == []
    assert d.resized == {}


def test_ratio_one_disables_resizing():
    # min_fill_ratio=1.0 → only a full fit qualifies; a near-miss expires (legacy behavior)
    d = _plan(deferred_buys=[_o("B1", "buy", notional=1000.0, qty=10.0)],
              buying_power=950.0, min_fill_ratio=1.0)
    assert d.submit_buys == []
    assert d.resized == {}


def test_ratio_zero_always_trims_to_fit():
    d = _plan(deferred_buys=[_o("B1", "buy", notional=1000.0, qty=10.0)],
              buying_power=300.0, min_fill_ratio=0.0)
    assert d.submit_buys == ["B1"]
    assert d.resized == {"B1": 3.0}


def test_missing_qty_cannot_be_resized():
    d = _plan(deferred_buys=[_o("B1", "buy", notional=1000.0, qty=None)], buying_power=950.0)
    assert d.submit_buys == []
    assert d.resized == {}


def test_oldest_first_full_then_resize_remaining_bp():
    # B1 fully fits (600), leaving 400; B2 (price 100, 7 shares) → 4 shares (57%) ≥ 0.5
    d = _plan(
        deferred_buys=[
            _o("B1", "buy", notional=600.0, qty=6.0),
            _o("B2", "buy", notional=700.0, qty=7.0),
        ],
        buying_power=1000.0,
    )
    assert d.submit_buys == ["B1", "B2"]
    assert d.resized == {"B2": 4.0}


def test_resize_not_applied_to_expired_buy():
    past = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)  # before NOW
    d = _plan(deferred_buys=[_o("B1", "buy", notional=1000.0, qty=10.0, expires_at=past)],
              buying_power=950.0)
    assert "B1" in d.expire
    assert d.submit_buys == []
    assert d.resized == {}


def test_sells_pending_holds_resizes_too():
    d = _plan(
        deferred_sells=[_o("S1", "sell")],
        deferred_buys=[_o("B1", "buy", notional=1000.0, qty=10.0)],
        buying_power=950.0,
    )
    assert d.submit_buys == []
    assert d.resized == {}
    assert d.waiting_on_sells is True
