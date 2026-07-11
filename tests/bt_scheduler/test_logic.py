"""bt-scheduler due-ness rules — pure, no I/O."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.logic import (artifact_needed, derive_windows, sweep_due, sweep_needed,
                       topup_due)

ET = ZoneInfo("America/New_York")


def _dt(y, m, d, h):
    return datetime(y, m, d, h, tzinfo=ET)


# ── derive_windows ────────────────────────────────────────────────────────────

def test_windows_relative_anchoring():
    w = derive_windows({"tune_years": 6, "validate_years": 2}, date(2026, 7, 11))
    assert w["validate_end"] == "2026-07-11"
    assert w["validate_start"] == w["tune_end"]           # walk-forward contiguous
    assert w["tune_start"] < w["tune_end"] < w["validate_end"]


def test_windows_clamped_to_earliest_viable():
    w = derive_windows({"tune_years": 6, "validate_years": 2}, date(2026, 7, 11),
                       earliest_viable_start=date(2022, 1, 1))
    assert w["tune_start"] == "2022-01-01"


def test_windows_none_when_tune_too_short():
    # earliest viable barely before the validate window → tune < 180d → skip
    w = derive_windows({"tune_years": 6, "validate_years": 2}, date(2026, 7, 11),
                       earliest_viable_start=date(2024, 6, 1))
    assert w is None


# ── topup_due ─────────────────────────────────────────────────────────────────

def test_topup_weekday_hour_and_daily_once():
    assert topup_due(_dt(2026, 7, 10, 23), date(2026, 7, 9))        # Fri 23:00, stale
    assert not topup_due(_dt(2026, 7, 10, 22), date(2026, 7, 9))    # before hour
    assert not topup_due(_dt(2026, 7, 11, 23), date(2026, 7, 9))    # Saturday
    assert not topup_due(_dt(2026, 7, 10, 23), date(2026, 7, 10))   # already today
    assert topup_due(_dt(2026, 7, 10, 23), None)                    # never fetched


# ── sweep_due ─────────────────────────────────────────────────────────────────

def test_sweep_once_per_iso_week_on_saturday():
    sat = _dt(2026, 7, 11, 3)     # Saturday 03:00 ET
    assert sweep_due(sat, None)                                       # never ran
    assert sweep_due(sat, {"status": "success",
                           "started_at": "2026-07-04T02:00:00"})      # last week
    assert not sweep_due(sat, {"status": "success",
                               "started_at": "2026-07-11T02:00:00"})  # this week done
    assert not sweep_due(sat, {"status": "running",
                               "started_at": "2026-07-04T02:00:00"})  # in flight
    assert not sweep_due(_dt(2026, 7, 10, 3), None)                   # Friday
    assert not sweep_due(_dt(2026, 7, 11, 1), None)                   # before hour


def test_failed_sweep_this_week_not_retried():
    sat_later = _dt(2026, 7, 11, 9)
    assert not sweep_due(sat_later, {"status": "failed",
                                     "started_at": "2026-07-11T02:00:00"})


# ── sweep_needed (skip-if-unchanged, Phase 6b) ────────────────────────────────

def test_sweep_needed_first_run_and_spec_change():
    ok, why = sweep_needed("h1", None, 0, date(2026, 7, 11))
    assert ok and why == "first run"
    state = {"last_spec_hash": "h0", "last_fired_at": "2026-07-10T19:00:00"}
    ok, why = sweep_needed("h1", state, 0, date(2026, 7, 11))
    assert ok and why == "spec changed"


def test_sweep_needed_pending_proposals_fire():
    state = {"last_spec_hash": "h1", "last_fired_at": "2026-07-10T19:00:00"}
    ok, why = sweep_needed("h1", state, 2, date(2026, 7, 11))
    assert ok and "2 pending" in why


def test_sweep_needed_skips_unchanged_until_forced_refresh():
    state = {"last_spec_hash": "h1", "last_fired_at": "2026-07-04T19:00:00"}
    ok, why = sweep_needed("h1", state, 0, date(2026, 7, 11))
    assert not ok and "refresh not due" in why
    # 28 days later the monthly refresh fires even with nothing new
    ok, why = sweep_needed("h1", state, 0, date(2026, 8, 1))
    assert ok and "forced refresh" in why


def test_sweep_needed_bad_state_fails_open():
    assert sweep_needed("h1", {"last_spec_hash": "h1"}, 0, date(2026, 7, 11))[0]
    assert sweep_needed("h1", {"last_spec_hash": "h1",
                               "last_fired_at": "garbage"}, 0, date(2026, 7, 11))[0]


# ── artifact_needed ───────────────────────────────────────────────────────────

def test_artifact_export_rules():
    done = {"status": "success", "sweep_id": "s1"}
    assert artifact_needed(done, None)                       # never exported
    assert artifact_needed(done, {"sweep_id": "s0"})         # newer sweep
    assert not artifact_needed(done, {"sweep_id": "s1"})     # already exported
    assert not artifact_needed({"status": "running", "sweep_id": "s2"}, None)
    assert not artifact_needed(None, None)
