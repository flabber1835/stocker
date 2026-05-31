"""Tests for _comparable_run_date — the timezone-correct date extraction the
supervisor uses to decide whether a step ran "today".

The regression this guards against: a service stamps started_at in UTC
(datetime.now(timezone.utc)), but the supervisor computes `today = date.today()`
in the container-local zone (TZ=America/New_York). In the evening-ET window
(roughly 19:00–24:00 ET) the UTC date is already "tomorrow" while ET is still
"today". Taking started_at[:10] naively yielded tomorrow's date, which never
matched `today`, so the vet step re-triggered every tick and the vetter re-billed
LLM credits ~every 16 min until ET rolled over.

_comparable_run_date converts a wall-clock timestamp to LOCAL time before taking
the date, and passes pure DATE strings through unchanged.
"""
import os
import sys
import time
import types
from datetime import datetime, timezone

from unittest.mock import MagicMock
import pytest


def _make_apscheduler_stubs():
    for name in ("apscheduler", "apscheduler.schedulers", "apscheduler.schedulers.asyncio",
                 "apscheduler.triggers", "apscheduler.triggers.cron", "apscheduler.triggers.interval"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["apscheduler.schedulers.asyncio"].AsyncIOScheduler = MagicMock()
    sys.modules["apscheduler.triggers.cron"].CronTrigger = MagicMock()
    sys.modules["apscheduler.triggers.interval"].IntervalTrigger = MagicMock()


_make_apscheduler_stubs()

from app.main import _comparable_run_date  # noqa: E402


@pytest.fixture(autouse=True)
def _force_eastern_tz():
    """Pin the process to US/Eastern so .astimezone() is deterministic regardless
    of the CI runner's zone — this is what the scheduler container runs as."""
    prev = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    yield
    if prev is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = prev
    time.tzset()


# ── Pure DATE columns pass through unchanged ─────────────────────────────────

def test_pure_date_passthrough():
    assert _comparable_run_date("2026-05-30") == "2026-05-30"


def test_pure_date_with_extra_chars_truncates():
    assert _comparable_run_date("2026-05-30 ") == "2026-05-30"


def test_empty_returns_empty():
    assert _comparable_run_date("") == ""
    assert _comparable_run_date(None) == ""


# ── The regression: UTC timestamp in the evening-ET window ───────────────────

def test_utc_timestamp_in_evening_et_window_maps_to_et_today():
    """2026-05-31T01:50 UTC is still 2026-05-30 21:50 in ET. The naive [:10] gave
    '2026-05-31' (the bug); the fix returns '2026-05-30' (ET local date)."""
    assert _comparable_run_date("2026-05-31T01:50:00+00:00") == "2026-05-30"


def test_naive_utc_timestamp_assumed_utc_then_converted():
    """A naive timestamp (no tz suffix) is assumed UTC, then converted to ET."""
    assert _comparable_run_date("2026-05-31T01:50:00") == "2026-05-30"


def test_z_suffix_handled():
    assert _comparable_run_date("2026-05-31T01:50:00Z") == "2026-05-30"


def test_utc_timestamp_outside_window_same_date():
    """Midday UTC (well within the same ET day) maps to the same calendar date."""
    # 2026-05-30T18:00 UTC = 14:00 ET → still the 30th.
    assert _comparable_run_date("2026-05-30T18:00:00+00:00") == "2026-05-30"


def test_morning_et_no_shift():
    """Early-UTC morning that is the prior evening in ET shifts back a day."""
    # 2026-05-30T02:00 UTC = 2026-05-29 22:00 ET.
    assert _comparable_run_date("2026-05-30T02:00:00+00:00") == "2026-05-29"


def test_malformed_timestamp_falls_back_to_prefix():
    """An unparseable value with a 'T' degrades gracefully to the first 10 chars."""
    assert _comparable_run_date("2026-13-99Tgarbage") == "2026-13-99"


def test_matches_date_today_for_a_just_now_utc_stamp():
    """End-to-end: a UTC 'now' stamp must resolve to the same local date that
    date.today() (the supervisor's `today`) would produce — i.e. they always match
    for a run that genuinely happened today, regardless of the UTC/ET split."""
    from datetime import date
    now_utc = datetime.now(timezone.utc).isoformat()
    assert _comparable_run_date(now_utc) == date.today().isoformat()
