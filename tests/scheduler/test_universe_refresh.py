"""Weekly universe-refresh gate (pure). fetch-universe previously fired only on
cold start — the universe was frozen at first boot (no new listings, no
delisting cleanup). The gate: weekend-only, age-thresholded, empty-case owned
by the cold-start branch, 0 disables."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.staleness import universe_refresh_due

ET = ZoneInfo("America/New_York")
SAT = datetime(2026, 7, 18, 9, 0, tzinfo=ET)
WED = datetime(2026, 7, 15, 9, 0, tzinfo=ET)


def _utc(days_ago: float, anchor: datetime = SAT) -> datetime:
    return (anchor - timedelta(days=days_ago)).astimezone(timezone.utc)


def test_due_on_weekend_when_stale():
    assert universe_refresh_due(SAT, _utc(10)) is True
    assert universe_refresh_due(SAT, _utc(7.1)) is True


def test_not_due_when_fresh():
    assert universe_refresh_due(SAT, _utc(2)) is False
    assert universe_refresh_due(SAT, _utc(6.9)) is False


def test_never_on_weekdays_even_if_ancient():
    assert universe_refresh_due(WED, _utc(90, anchor=WED)) is False


def test_empty_universe_owned_by_cold_start_branch():
    assert universe_refresh_due(SAT, None) is False


def test_zero_threshold_disables():
    assert universe_refresh_due(SAT, _utc(365), threshold_days=0) is False


def test_naive_timestamp_treated_as_local():
    naive = (SAT - timedelta(days=10)).replace(tzinfo=None)
    assert universe_refresh_due(SAT, naive) is True
