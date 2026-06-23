"""Audit P0 — price-bar validation in _upsert_prices and the chain-advance gate.

H1: close/open/high/low/volume were written verbatim (only adjusted_close was guarded),
so a 0/negative close from a halted/thin name corrupted dollar-volume/liquidity.
H2: a NULL adjusted_close bar still advanced MAX(date), stranding the ticker as
"current". Both are fixed by validating the bar in _upsert_prices (skip if close OR
adjusted_close invalid; null individually-bad OHLC/volume) and returning the count
actually written. The chain-advance gate withholds session_date on low coverage / no SPY.
"""
import datetime as dt

import pytest

from app.main import _upsert_prices, _valid_px, _chain_advance_decision


class _CapSession:
    """Captures the params list passed to session.execute (the cleaned rows)."""
    def __init__(self):
        self.params = None
        self.calls = 0

    async def execute(self, stmt, params=None):
        self.calls += 1
        self.params = params
        return None


# ── _valid_px ───────────────────────────────────────────────────────────────────

def test_valid_px():
    assert _valid_px(10.5)
    assert _valid_px(0.01)
    assert not _valid_px(0)
    assert not _valid_px(0.0)
    assert not _valid_px(-1.0)
    assert not _valid_px(None)
    assert not _valid_px(float("nan"))
    assert not _valid_px(float("inf"))
    assert not _valid_px(2_000_000)   # absurd
    assert not _valid_px("10.5")      # string, not a number


# ── _upsert_prices validation ─────────────────────────────────────────────────

def _bar(d, close, adj, **kw):
    base = {"date": d, "open": close, "high": close, "low": close,
            "close": close, "adjusted_close": adj, "volume": 1000}
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_skips_zero_and_negative_close():
    rows = [
        _bar("2026-06-20", 10.5, 10.5),     # good
        _bar("2026-06-21", 0, 0),           # zero → skip (H1)
        _bar("2026-06-22", -5, 12.0),       # negative close → skip (H1)
    ]
    s = _CapSession()
    written = await _upsert_prices(s, "AAA", rows)
    assert written == 1
    assert len(s.params) == 1
    assert s.params[0]["close"] == 10.5


@pytest.mark.asyncio
async def test_skips_null_or_zero_adjusted_close():
    # H2: a fresh date with NULL/0 adjusted_close must NOT be written (would advance
    # MAX(date) and strand the ticker as "current").
    rows = [
        _bar("2026-06-22", 12.0, None),     # null adjusted → skip
        _bar("2026-06-23", 12.0, 0.0),      # zero adjusted → skip
    ]
    s = _CapSession()
    written = await _upsert_prices(s, "AAA", rows)
    assert written == 0
    assert s.calls == 0          # nothing executed when no valid rows
    assert s.params is None


@pytest.mark.asyncio
async def test_nulls_bad_ohlc_and_volume_but_keeps_bar():
    # close+adjusted valid → keep the bar, but individually-bad open/high/low/volume → NULL
    rows = [_bar("2026-06-22", 12.0, 12.0, open=0, high=-1, low=None, volume=-5)]
    s = _CapSession()
    written = await _upsert_prices(s, "AAA", rows)
    assert written == 1
    p = s.params[0]
    assert p["close"] == 12.0 and p["adjusted_close"] == 12.0
    assert p["open"] is None and p["high"] is None and p["low"] is None
    assert p["volume"] is None


@pytest.mark.asyncio
async def test_zero_volume_is_kept():
    # 0 volume is a legitimate no-trade day (only negatives are invalid)
    rows = [_bar("2026-06-22", 12.0, 12.0, volume=0)]
    s = _CapSession()
    written = await _upsert_prices(s, "AAA", rows)
    assert written == 1
    assert s.params[0]["volume"] == 0


@pytest.mark.asyncio
async def test_all_valid_written_in_order():
    rows = [_bar("2026-06-20", 10.5, 10.5), _bar("2026-06-21", 10.7, 10.7)]
    s = _CapSession()
    written = await _upsert_prices(s, "AAA", rows)
    assert written == 2 and len(s.params) == 2


# ── chain-advance gate ──────────────────────────────────────────────────────────

D = dt.date(2026, 6, 20)


def test_gate_blocks_when_no_spy():
    ready, reason = _chain_advance_decision(None, 0.99, 0.80)
    assert not ready and "SPY" in reason


def test_gate_blocks_low_coverage():
    ready, reason = _chain_advance_decision(D, 0.50, 0.80)
    assert not ready and "coverage" in reason


def test_gate_allows_full_coverage():
    ready, reason = _chain_advance_decision(D, 1.0, 0.80)
    assert ready and reason is None


def test_gate_allows_at_floor():
    ready, _ = _chain_advance_decision(D, 0.80, 0.80)
    assert ready


def test_gate_none_coverage_does_not_block():
    # empty universe → pcp None → can't judge coverage → don't block on it (SPY still required)
    ready, reason = _chain_advance_decision(D, None, 0.80)
    assert ready and reason is None
