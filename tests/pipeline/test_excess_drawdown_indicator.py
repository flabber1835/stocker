"""Unit tests for _excess_drawdown_map_from_rows — the beta-adjusted (residual)
falling-knife signal surfaced display-only on the screener card (excess drawdown +
idiosyncratic vol). Mirrors the vetter's drawdown.excess_drawdown semantics: market
move stripped via beta, beta clamped to the veto's [0, 3] (NOT the display [-1, 3])."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.main import _excess_drawdown_map_from_rows, _beta_map_from_rows


def _row(ticker, d, close):
    return SimpleNamespace(ticker=ticker, date=d, adjusted_close=close)


def _series(ticker, returns, start=100.0, d0=date(2025, 1, 1)):
    rows, px, d = [], start, d0
    rows.append(_row(ticker, d, px))
    for r in returns:
        px *= (1 + r)
        d += timedelta(days=1)
        rows.append(_row(ticker, d, px))
    return rows


def _spy_rows(returns, start=400.0):
    return _series("SPY", returns, start=start)


def test_excess_zero_when_drop_is_all_market():
    """Stock returns identical to SPY → beta 1, residuals 0: any drawdown is fully
    market-explained, so excess ≈ 0 and idio_vol ≈ 0."""
    rng = [0.01, -0.03] * 30   # 60 days, oscillating with downward drift (var > 0)
    spy = _spy_rows(rng)
    stock = _series("AAA", rng)
    m = _excess_drawdown_map_from_rows(stock, spy, window=21, lookback=120, min_obs=10)
    assert "AAA" in m
    assert abs(m["AAA"]["excess_dd"]) < 1e-6
    assert m["AAA"]["idio_vol"] < 1e-6


def test_excess_uses_zero_beta_clamp_for_negative_beta():
    """A perfectly inverse name has true beta ≈ -1. The excess calc clamps beta to
    [0, 3] (the conservative veto clamp), so the market term drops out and
    excess_dd == raw_dd. The DISPLAY beta, by contrast, stays signed/negative."""
    rng = [0.02, -0.025, 0.018, -0.02, 0.015, -0.03] * 10   # 60 days, var > 0
    spy = _spy_rows(rng)
    stock = _series("BBB", [-1.0 * r for r in rng])
    m = _excess_drawdown_map_from_rows(stock, spy, window=21, lookback=120, min_obs=10)
    assert "BBB" in m

    closes = [r.adjusted_close for r in stock]
    win = closes[-21:]
    raw_dd = win[-1] / max(win) - 1.0
    # beta floored to 0 → no market strip → excess equals the raw drawdown.
    assert abs(m["BBB"]["excess_dd"] - raw_dd) < 1e-9

    # And the display beta (looser [-1, 3] clamp) is genuinely negative here — the
    # two clamps differ by design, which is the whole reason to show excess too.
    disp = _beta_map_from_rows(stock, spy, lookback=120, min_obs=10)
    assert disp["BBB"] < 0


def test_excess_high_beta_strips_more_market():
    """A 2x-beta name in a market selloff: most of the raw drop is market, so the
    excess is much milder than the raw drawdown (closer to 0)."""
    rng = [0.01, -0.04, 0.005, -0.035] * 15   # 60 days, net down
    spy = _spy_rows(rng)
    stock = _series("CCC", [2.0 * r for r in rng])
    m = _excess_drawdown_map_from_rows(stock, spy, window=21, lookback=120, min_obs=10)
    assert "CCC" in m
    closes = [r.adjusted_close for r in stock]
    win = closes[-21:]
    raw_dd = win[-1] / max(win) - 1.0
    # raw drop is large and negative; excess (market stripped) is much closer to 0.
    assert raw_dd < -0.05
    assert m["CCC"]["excess_dd"] > raw_dd + 0.03


def test_excess_skips_short_history():
    rng = [0.01, -0.01] * 3   # 6 days < min_obs + 1
    spy = _spy_rows(rng)
    stock = _series("DDD", rng)
    m = _excess_drawdown_map_from_rows(stock, spy, window=21, lookback=120, min_obs=20)
    assert m == {}


def test_excess_skips_zero_spy_variance():
    spy = _spy_rows([0.0] * 40)   # flat SPY → var_m = 0 → no beta → no entry
    stock = _series("EEE", [0.01, -0.02] * 20)
    m = _excess_drawdown_map_from_rows(stock, spy, window=21, lookback=120, min_obs=10)
    assert m == {}


# ── _excess_dd_limit (per-ticker vol-scaled trigger shown on the card) ─────────

def test_excess_dd_limit_scales_and_clamps(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "DRAWDOWN_EXCESS_PCT", 0.15)
    monkeypatch.setattr(m, "DRAWDOWN_VOL_SCALING", True)
    monkeypatch.setattr(m, "DRAWDOWN_VOL_ANCHOR", 0.35)
    monkeypatch.setattr(m, "DRAWDOWN_EXCESS_MIN", 0.10)
    monkeypatch.setattr(m, "DRAWDOWN_EXCESS_MAX", 0.30)
    # typical name (σ == anchor) → base
    assert abs(m._excess_dd_limit(0.35) - 0.15) < 1e-9
    # calm name → clamped up to MIN
    assert abs(m._excess_dd_limit(0.05) - 0.10) < 1e-9
    # wild name → clamped down to MAX
    assert abs(m._excess_dd_limit(2.0) - 0.30) < 1e-9
    # unknown vol → flat base
    assert abs(m._excess_dd_limit(None) - 0.15) < 1e-9


def test_excess_dd_limit_flat_when_scaling_off(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "DRAWDOWN_EXCESS_PCT", 0.10)
    monkeypatch.setattr(m, "DRAWDOWN_VOL_SCALING", False)
    assert abs(m._excess_dd_limit(0.05) - 0.10) < 1e-9
    assert abs(m._excess_dd_limit(2.0) - 0.10) < 1e-9
