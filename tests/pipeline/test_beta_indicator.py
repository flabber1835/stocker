"""Unit tests for _beta_map_from_rows — the pure 120d-vs-SPY market beta surfaced
on the screener detail card (display-only, not a scoring factor)."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.main import _beta_map_from_rows


def _row(ticker, d, close):
    return SimpleNamespace(ticker=ticker, date=d, adjusted_close=close)


def _series(ticker, returns, start=100.0, d0=date(2025, 1, 1)):
    """Build dated price rows from a daily-return list."""
    rows = []
    px = start
    d = d0
    rows.append(_row(ticker, d, px))
    for r in returns:
        px *= (1 + r)
        d += timedelta(days=1)
        rows.append(_row(ticker, d, px))
    return rows


def _spy_rows(returns, start=400.0, d0=date(2025, 1, 1), ticker="SPY"):
    return _series(ticker, returns, start=start, d0=d0)


def test_beta_of_exact_multiple_recovered():
    """Stock = 1.5x SPY each day → beta ≈ 1.5."""
    rng = [0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.008, -0.012] * 4   # 32 days
    spy = _spy_rows(rng)
    stock = _series("AAA", [1.5 * r for r in rng])
    m = _beta_map_from_rows(stock, spy, lookback=120, min_obs=10)
    assert abs(m["AAA"] - 1.5) < 0.02


def test_beta_aligns_by_date_when_ticker_has_gaps():
    """A ticker missing some SPY dates still gets a sensible beta from the
    overlapping pairs (date alignment, not positional)."""
    rng = [0.01, -0.01, 0.02, -0.015, 0.005, -0.008, 0.012, -0.006] * 4
    spy = _spy_rows(rng)
    stock = _series("BBB", [1.0 * r for r in rng])
    # Drop a few stock rows (simulate missing trading days) — beta still ≈ 1.0.
    stock = stock[:5] + stock[8:]
    m = _beta_map_from_rows(stock, spy, lookback=120, min_obs=10)
    assert abs(m["BBB"] - 1.0) < 0.1


def test_beta_clipped_to_zero_floor():
    """A negative-beta name is clipped to 0 (no shorting the market in display)."""
    rng = [0.01, -0.01] * 16
    spy = _spy_rows(rng)
    stock = _series("CCC", [-1.0 * r for r in rng])  # moves opposite SPY
    m = _beta_map_from_rows(stock, spy, lookback=120, min_obs=10)
    assert m["CCC"] == 0.0


def test_beta_clipped_to_high_cap():
    rng = [0.01, -0.01] * 16
    spy = _spy_rows(rng)
    stock = _series("DDD", [5.0 * r for r in rng])  # beta 5 → clipped to 3
    m = _beta_map_from_rows(stock, spy, lookback=120, min_obs=10, clip_hi=3.0)
    assert m["DDD"] == 3.0


def test_insufficient_overlap_omitted():
    spy = _spy_rows([0.01, -0.01, 0.02])
    stock = _series("EEE", [0.01, -0.01, 0.02])  # only 3 pairs
    m = _beta_map_from_rows(stock, spy, lookback=120, min_obs=20)
    assert "EEE" not in m


def test_no_spy_returns_empty():
    stock = _series("FFF", [0.01, -0.01] * 16)
    assert _beta_map_from_rows(stock, [], lookback=120, min_obs=10) == {}
