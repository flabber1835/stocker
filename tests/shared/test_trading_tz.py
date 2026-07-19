"""Tests for the shared trading-timezone resolver (scheduler/pipeline/risk share it)."""
import pytest

from stock_strategy_shared.trading_tz import (
    DEFAULT_TRADING_TZ,
    resolve_trading_tz,
    trading_now,
    trading_today,
)


def test_defaults_to_new_york(monkeypatch):
    monkeypatch.delenv("STOCKER_TZ", raising=False)
    monkeypatch.delenv("SCHEDULE_TZ", raising=False)
    tz = resolve_trading_tz("SCHEDULE_TZ")
    assert str(tz) == DEFAULT_TRADING_TZ == "America/New_York"


def test_canonical_stocker_tz_wins(monkeypatch):
    monkeypatch.setenv("STOCKER_TZ", "Europe/London")
    monkeypatch.setenv("SCHEDULE_TZ", "America/New_York")  # override ignored when canonical set
    tz = resolve_trading_tz("SCHEDULE_TZ")
    assert str(tz) == "Europe/London"


def test_service_override_used_when_no_canonical(monkeypatch):
    monkeypatch.delenv("STOCKER_TZ", raising=False)
    monkeypatch.setenv("RISK_TZ", "America/Chicago")
    tz = resolve_trading_tz("RISK_TZ")
    assert str(tz) == "America/Chicago"


def test_all_services_agree_when_canonical_set(monkeypatch):
    # The whole point: one STOCKER_TZ makes scheduler/pipeline/risk resolve the SAME
    # zone regardless of their distinct back-compat env names.
    monkeypatch.setenv("STOCKER_TZ", "America/Los_Angeles")
    sched = resolve_trading_tz("SCHEDULE_TZ")
    risk = resolve_trading_tz("RISK_TZ")
    assert str(sched) == str(risk) == "America/Los_Angeles"


def test_invalid_zone_fails_fast(monkeypatch):
    monkeypatch.setenv("STOCKER_TZ", "Not/AZone")
    with pytest.raises(RuntimeError):
        resolve_trading_tz("SCHEDULE_TZ")


def test_helpers_return_aware_now_and_date(monkeypatch):
    monkeypatch.delenv("STOCKER_TZ", raising=False)
    tz = resolve_trading_tz("SCHEDULE_TZ")
    assert trading_now(tz).tzinfo is not None
    assert trading_today(tz) == trading_now(tz).date()


# ── market_today + weekday_sessions_between (audit findings #1/#2/#9) ─────────

def test_market_today_uses_trading_zone(monkeypatch):
    from stock_strategy_shared.trading_tz import market_today
    monkeypatch.setenv("STOCKER_TZ", "America/New_York")
    from datetime import datetime
    from zoneinfo import ZoneInfo
    assert market_today() == datetime.now(ZoneInfo("America/New_York")).date()


def test_weekday_sessions_friday_close_on_monday_is_one():
    from datetime import date
    from stock_strategy_shared.trading_tz import weekday_sessions_between
    fri, mon = date(2026, 7, 17), date(2026, 7, 20)
    assert weekday_sessions_between(fri, mon) == 1     # not 3 calendar days


@pytest.mark.parametrize("earlier,later,expected", [
    ((2026, 7, 17), (2026, 7, 17), 0),   # same day
    ((2026, 7, 17), (2026, 7, 18), 0),   # Fri → Sat: no session elapsed
    ((2026, 7, 17), (2026, 7, 19), 0),   # Fri → Sun
    ((2026, 7, 16), (2026, 7, 17), 1),   # Thu → Fri
    ((2026, 7, 13), (2026, 7, 20), 5),   # Mon → next Mon: one full week
    ((2026, 7, 3),  (2026, 7, 20), 11),  # long span incl. two weekends
    ((2026, 7, 20), (2026, 7, 17), 0),   # reversed → 0, never negative
])
def test_weekday_sessions_between_cases(earlier, later, expected):
    from datetime import date
    from stock_strategy_shared.trading_tz import weekday_sessions_between
    assert weekday_sessions_between(date(*earlier), date(*later)) == expected


def test_weekday_sessions_matches_bruteforce():
    from datetime import date, timedelta
    from stock_strategy_shared.trading_tz import weekday_sessions_between
    start = date(2026, 1, 1)
    for span in range(0, 40):
        end = start + timedelta(days=span)
        brute = sum(1 for i in range(1, span + 1)
                    if (start + timedelta(days=i)).weekday() < 5)
        assert weekday_sessions_between(start, end) == brute, span
