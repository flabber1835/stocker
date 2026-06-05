"""Unit tests for _route_to_drain — the drain-vs-inline submission decision.

'Approve now' (mode='immediate') submits inline as a market order when the
market is OPEN, but falls back to the fill-gated open drain when CLOSED so an
off-hours immediate click can't bypass the sells-first buying-power sequencing.
'scheduled' always uses the drain.
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


# ── immediate: inline when open, drain when closed ────────────────────────────

def test_immediate_open_submits_inline():
    assert _route_to_drain("immediate", _clock(True)) is False


def test_immediate_closed_falls_back_to_drain():
    assert _route_to_drain("immediate", _clock(False)) is True


def test_immediate_unknown_clock_submits_inline():
    # No creds / unreachable: Step 6's credential guard records the outcome;
    # we don't silently defer (dev/paper/mock immediate still submits).
    assert _route_to_drain("immediate", None) is False


def test_immediate_clock_without_is_open_treated_as_closed():
    assert _route_to_drain("immediate", {}) is True


# ── unknown modes never drain (fall through to inline) ────────────────────────

def test_unknown_mode_does_not_drain():
    assert _route_to_drain("", _clock(False)) is False
