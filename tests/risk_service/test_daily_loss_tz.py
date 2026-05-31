"""Tests for the risk-service daily-loss baseline trading-day anchoring.

The MAX_DAILY_LOSS_PCT baseline ("the day's opening account value") must reset on
the TRADING day (ET), not the UTC calendar day. Postgres CURRENT_DATE rolls over at
~19–20:00 ET, mid-session for late-ET trading, which would put the baseline on the
wrong side of the session. _trading_day_today() computes the reset date in RISK_TZ
(default America/New_York) and it is passed to the baseline query as a bound param.
"""
import os as _os, sys as _sys

_RISK_PATH = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "services", "risk-service"))
_app = _sys.modules.get("app")
if _app is None or _RISK_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(_sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]
    if _RISK_PATH not in _sys.path:
        _sys.path.insert(0, _RISK_PATH)

import time as _time
from datetime import datetime, timezone

from app import main as risk_main


def test_trading_day_today_uses_risk_tz_not_process_tz():
    """_trading_day_today() follows RISK_TZ (ET) even when the process is in UTC.
    In the evening-ET window the ET date is still 'yesterday' relative to UTC."""
    prev = _os.environ.get("TZ")
    _os.environ["TZ"] = "UTC"
    _time.tzset()
    try:
        td = risk_main._trading_day_today()
        if risk_main._RISK_TZ is not None:
            expected = datetime.now(risk_main._RISK_TZ).date().isoformat()
        else:
            expected = datetime.now().date().isoformat()
        assert td == expected
    finally:
        if prev is None:
            _os.environ.pop("TZ", None)
        else:
            _os.environ["TZ"] = prev
        _time.tzset()


def test_trading_day_today_is_iso_date_string():
    td = risk_main._trading_day_today()
    # Parses as a date and round-trips.
    parsed = datetime.fromisoformat(td).date()
    assert parsed.isoformat() == td


def test_risk_tz_defaults_to_eastern():
    assert risk_main.RISK_TZ_NAME == "America/New_York"


def test_trading_day_differs_from_utc_date_in_evening_et(monkeypatch):
    """Sanity: when 'now' is 01:30 UTC, the ET trading day is the prior calendar
    date — proving the helper would not bucket a late-ET sync into the UTC tomorrow."""
    if risk_main._RISK_TZ is None:
        import pytest
        pytest.skip("zoneinfo unavailable")

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 5, 31, 1, 30, tzinfo=timezone.utc)
            return base.astimezone(tz) if tz else base

    monkeypatch.setattr(risk_main, "datetime", _FixedDatetime)
    # 01:30 UTC May 31 == 21:30 ET May 30.
    assert risk_main._trading_day_today() == "2026-05-30"
