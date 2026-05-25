from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import pandas as pd


@lru_cache(maxsize=1)
def _nyse():
    import exchange_calendars as xcals  # lazy: heavy import, loaded once
    return xcals.get_calendar("XNYS")


def last_trading_day(today: date) -> date:
    """Return the most recent NYSE trading session on or before today.

    Correctly handles weekends AND exchange holidays (Memorial Day, Christmas,
    Good Friday, etc.).  Previously this function only skipped weekends, which
    caused the scheduler to compute the wrong trading_day on market holidays
    and trigger an infinite portfolio-builder re-trigger loop.
    """
    return _nyse().date_to_session(pd.Timestamp(today), direction="previous").date()


def count_missed_trading_days(last_run_date: date, today: date) -> int:
    """
    Count NYSE trading sessions that closed between last_run_date and today.
    Both endpoints are exclusive: last_run_date (we have that data) and today
    (market hasn't closed yet).
    Holidays are correctly NOT counted as missed trading days.
    """
    if last_run_date >= today:
        return 0
    start = pd.Timestamp(last_run_date + timedelta(days=1))
    end   = pd.Timestamp(today - timedelta(days=1))
    if start > end:
        return 0
    return len(_nyse().sessions_in_range(start, end))


def is_stale(last_run_date: date | None, today: date) -> bool:
    """
    Return True if there are closed NYSE trading sessions whose data we don't
    have yet.

    Examples:
      Friday → Monday           : 0 missed days (weekend only)     → not stale
      Friday → Tuesday          : 1 missed day  (Monday)           → stale
      Friday → Mon Memorial Day : 0 missed days (holiday)          → not stale
      Friday → Tue after holiday: 0 missed days (Mon was holiday)  → not stale
      None                      : always stale
    """
    if last_run_date is None:
        return True
    if today <= last_run_date:
        return False
    return count_missed_trading_days(last_run_date, today) > 0
