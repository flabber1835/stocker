from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from sentinel import __main__ as cli
from sentinel.feed import ingest, manual_daily

ET = ZoneInfo("America/New_York")


def test_extract_requires_exactly_one_explicit_through():
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid):
        manual_daily.extract_through(["feed-daily"])
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid):
        manual_daily.extract_through([
            "feed-daily", "--through", "2026-08-24",
            "--through=2026-08-24",
        ])
    clean, value = manual_daily.extract_through([
        "--config", "x", "feed-daily", "--through=2026-08-24"])
    assert clean == ["--config", "x", "feed-daily"]
    assert value == "2026-08-24"


def test_latest_fully_closed_session_is_accepted_and_future_is_refused():
    after_close = dt.datetime(2026, 8, 24, 16, 30, tzinfo=ET)
    boundary = manual_daily.validate_through("2026-08-24", now_et=after_close)
    assert boundary.through == "2026-08-24"
    assert boundary.latest_closed == "2026-08-24"
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid, match="latest closed"):
        manual_daily.validate_through("2026-08-25", now_et=after_close)


def test_current_session_before_official_close_is_refused():
    before_close = dt.datetime(2026, 8, 24, 15, 59, tzinfo=ET)
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid, match="latest closed"):
        manual_daily.validate_through("2026-08-24", now_et=before_close)


@pytest.mark.parametrize("value", [
    "2026-08-23",       # Sunday
    "2026-07-04",       # holiday/weekend
    "2026-8-24",        # noncanonical
    "2026-02-30",       # invalid date
])
def test_non_session_or_malformed_boundary_refuses(value):
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid):
        manual_daily.validate_through(
            value, now_et=dt.datetime(2026, 8, 24, 17, 0, tzinfo=ET))


def test_utc_tomorrow_does_not_advance_exchange_session():
    # 20:30 PT is already the next UTC date, but XNYS authority remains Aug 24.
    instant = dt.datetime(2026, 8, 24, 20, 30,
                          tzinfo=ZoneInfo("America/Los_Angeles"))
    boundary = manual_daily.validate_through("2026-08-24", now_et=instant)
    assert boundary.latest_closed == "2026-08-24"
    with pytest.raises(manual_daily.ManualDailyBoundaryInvalid):
        manual_daily.validate_through("2026-08-25", now_et=instant)


def test_ingest_daily_has_no_wall_clock_fallback():
    with pytest.raises(ValueError, match="explicit through-session"):
        ingest.daily(object())


def test_ingest_daily_passes_explicit_session_verbatim(monkeypatch):
    observed = {}

    def legacy(conn, **kwargs):
        observed.update(kwargs)
        return "ok"

    monkeypatch.setattr(ingest, "_legacy_daily", legacy)
    assert ingest.daily("conn", today="2026-08-24") == "ok"
    assert observed["today"] == "2026-08-24"


def test_cli_missing_boundary_refuses_before_retained_cli(monkeypatch, capsys):
    called = False

    def forbidden(_argv):
        nonlocal called
        called = True
        raise AssertionError("retained CLI must not construct DB/vendor state")

    monkeypatch.setattr(cli._base, "main", forbidden)
    assert cli.main(["feed-daily"]) == cli._base.EXIT_CONFIG
    assert called is False
    assert "requires" in capsys.readouterr().err


def test_cli_prints_and_passes_resolved_session(monkeypatch, capsys):
    observed = {}
    boundary = manual_daily.ManualDailyBoundary(
        through="2026-08-24", latest_closed="2026-08-24",
        calendar_version="XNYS/test")
    monkeypatch.setattr(
        manual_daily, "validate_through", lambda _value: boundary)

    def original_daily(_conn, **kwargs):
        observed.update(kwargs)
        return "done"

    monkeypatch.setattr(ingest, "daily", original_daily)

    def retained(argv):
        assert argv == ["feed-daily"]
        ingest.daily("conn")
        return 0

    monkeypatch.setattr(cli._base, "main", retained)
    assert cli.main(["feed-daily", "--through", "2026-08-24"]) == 0
    assert observed["today"] == "2026-08-24"
    assert "through-session 2026-08-24" in capsys.readouterr().out
