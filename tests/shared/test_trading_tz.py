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
