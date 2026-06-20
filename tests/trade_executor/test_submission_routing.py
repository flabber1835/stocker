"""Unit tests for _route_to_drain — the drain-vs-inline submission decision.

'Approve now' (mode='immediate') while the market is OPEN submits SELLS inline
(they fill in seconds and free buying power) but routes BUYS to the fill-gated
open drain so a rotation's buys release only within real buying power (instead of
firing inline ahead of their funding sells and hitting "insufficient buying
power"). When CLOSED it falls back to the drain entirely. 'scheduled' always
uses the drain.
"""
from app.main import _route_to_drain


def _clock(is_open):
    return {"is_open": is_open, "next_open": None, "next_close": None}


# ── scheduled: always the drain ───────────────────────────────────────────────

def test_scheduled_open_routes_to_drain():
    assert _route_to_drain("scheduled", _clock(True)) is True


def test_scheduled_closed_routes_to_drain():
    assert _route_to_drain("scheduled", _clock(False)) is True


def test_scheduled_unknown_clock_routes_to_drain():
    assert _route_to_drain("scheduled", None) is True


# ── immediate + OPEN: sells inline, buys via the drain ────────────────────────

def test_immediate_open_sell_submits_inline():
    # A sell fills fast and frees buying power — submit it now.
    assert _route_to_drain("immediate", _clock(True), side="sell") is False


def test_immediate_open_buy_routes_to_drain():
    # A buy must wait for live buying power (sells settle first) — drain it.
    assert _route_to_drain("immediate", _clock(True), side="buy") is True


def test_immediate_open_no_side_defaults_inline():
    # Back-compat: with no side specified, immediate+open is not treated as a buy.
    assert _route_to_drain("immediate", _clock(True)) is False


# ── immediate + CLOSED: drain everything ──────────────────────────────────────

def test_immediate_closed_falls_back_to_drain():
    assert _route_to_drain("immediate", _clock(False), side="sell") is True
    assert _route_to_drain("immediate", _clock(False), side="buy") is True


def test_immediate_unknown_clock_buy_routes_to_drain():
    # FIX D: unknown clock (fetch failed) is do-not-submit-blind for BUYS — a real
    # buy must NOT submit inline with unknown market state (could fire ahead of its
    # funding sell / outside hours → "insufficient buying power"). Route to drain.
    assert _route_to_drain("immediate", None, side="buy") is True


def test_immediate_unknown_clock_sell_submits_inline():
    # FIX D: a SELL (de-risk / emergency close) is still allowed inline even when
    # the clock is unknown — closing must never be trapped by a clock outage.
    assert _route_to_drain("immediate", None, side="sell") is False


def test_immediate_clock_without_is_open_treated_as_closed():
    assert _route_to_drain("immediate", {}, side="buy") is True


# ── unknown modes never drain (fall through to inline) ────────────────────────

def test_unknown_mode_does_not_drain():
    assert _route_to_drain("", _clock(False)) is False
