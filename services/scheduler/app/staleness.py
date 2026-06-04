from __future__ import annotations

from datetime import date, datetime, time as _time, timedelta
from functools import lru_cache

import pandas as pd

# NYSE regular session close in exchange-local (ET) time. A session only counts
# as the "latest closed session" once this wall-clock time on its date has
# passed. 16:00 is the regular close; early-close half-days (1:00pm) settle
# earlier but the scheduler only ever STARTS a chain in the evening, so a
# conservative 16:00 boundary is correct in practice and keeps the rule simple.
REGULAR_CLOSE = _time(16, 0)


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


def is_trading_day(d: date) -> bool:
    """Return True if `d` is an NYSE trading session (not a weekend or an
    exchange holiday like Memorial Day, Good Friday, Christmas, etc.)."""
    return last_trading_day(d) == d


def latest_closed_session(now_local: datetime, close: _time = REGULAR_CLOSE) -> date:
    """The most recent NYSE session whose regular close has already passed as of
    `now_local` (which MUST be in exchange-local / ET time).

    This is the date the scheduler pins a chain to. Its defining property is
    stability across midnight: from a session's close until the NEXT session's
    close it returns the SAME date. Concretely, a chain that starts at 22:30 ET
    on Monday's session and runs past midnight still computes "Monday" at 00:09
    Tuesday (Tuesday's session has not closed yet), so the supervisor does not
    mistake the in-flight chain for a new cycle and abandon it. The key only
    rolls when the next session actually closes (≈16:00 the next trading day).

    Contrast with `last_trading_day(today)`, which on a weekday flips to *today*
    at midnight — long before that session has closed — and is what made a chain
    spanning midnight look like a fresh day and get reset.
    """
    today = now_local.date()
    sess = last_trading_day(today)
    if sess == today and now_local.time() < close:
        # `today` is a trading session but it has not closed yet; the latest
        # CLOSED session is the previous one.
        sess = last_trading_day(today - timedelta(days=1))
    return sess


def should_run_chain(today: date, last_processed_session: date | None) -> bool:
    """Trading-calendar-aware decision: should the daily chain START today?

    - On an NYSE trading session: always run. (A separate scheduled-time gate
      ensures we only run after the close, so today's bar is available.)
    - On a non-trading day (weekend/holiday): run ONLY to catch up a trading
      session whose data has not been processed yet. Once that session has been
      processed, further weekend/holiday ticks are no-ops — this is what stops
      the chain (and the expensive vetter step) from re-running pointlessly on
      every weekend day and on weekday holidays.

    `last_processed_session` is the data date of the last completed chain
    (the latest delta proposal date). None means "never run" → always run.
    """
    if is_trading_day(today):
        return True
    return is_stale(last_processed_session, today)

