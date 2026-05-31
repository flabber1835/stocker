"""Tests that the pipeline computes chain_date in the SAME explicit zone the
scheduler uses (SCHEDULE_TZ), so the two services never disagree on "today".

The regression: scheduler was made TZ-explicit (ET) while the pipeline still used
the implicit container TZ (UTC) for chain_date. In the evening-ET window the
pipeline wrote chain_date one calendar day ahead of the scheduler's `today`, the
scheduler's done-check never matched, and it force-re-triggered the pipeline every
tick (infinite loop + vetter credit burn).
"""
import os as _os, sys as _sys, time as _time

from app import main as pmain


def test_pipeline_local_today_matches_schedule_tz():
    """pipeline._local_today() follows SCHEDULE_TZ regardless of the container TZ."""
    from datetime import datetime
    prev = _os.environ.get("TZ")
    _os.environ["TZ"] = "UTC"
    _time.tzset()
    try:
        if pmain._SCHEDULE_TZ is not None:
            expected = datetime.now(pmain._SCHEDULE_TZ).date()
        else:
            expected = datetime.now().date()
        assert pmain._local_today() == expected
    finally:
        if prev is None:
            _os.environ.pop("TZ", None)
        else:
            _os.environ["TZ"] = prev
        _time.tzset()


def test_pipeline_schedule_tz_defaults_eastern():
    assert pmain.SCHEDULE_TZ_NAME == "America/New_York"


def test_pipeline_and_scheduler_agree_on_today():
    """The whole point: pipeline._local_today() must equal what the scheduler
    computes, so chain_date and the scheduler's target are the same calendar date.
    Both read SCHEDULE_TZ, so for the same zone they must agree."""
    from datetime import datetime
    # Compute the scheduler-equivalent value directly from the same zone the
    # pipeline uses (we can't import the scheduler app here — different service —
    # but both helpers are defined identically against SCHEDULE_TZ).
    if pmain._SCHEDULE_TZ is not None:
        scheduler_equiv = datetime.now(pmain._SCHEDULE_TZ).date()
    else:
        scheduler_equiv = datetime.now().date()
    assert pmain._local_today() == scheduler_equiv
