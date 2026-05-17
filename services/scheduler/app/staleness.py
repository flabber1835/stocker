from datetime import date, timedelta


def count_missed_trading_days(last_run_date: date, today: date) -> int:
    """
    Count weekday trading days that have closed between last_run_date and today.
    Both endpoints are exclusive: last_run_date (we have that data) and today
    (market hasn't closed yet).
    Does not account for US market holidays — a holiday is treated as a missed
    trading day, which triggers an extra fetch that exits quickly (false positive
    is acceptable; false negative is not).
    """
    count = 0
    d = last_run_date + timedelta(days=1)
    while d < today:
        if d.weekday() < 5:  # Mon–Fri
            count += 1
        d += timedelta(days=1)
    return count


def is_stale(last_run_date: date | None, today: date) -> bool:
    """
    Return True if there are closed trading days whose data we don't have yet.

    Examples:
      Friday → Monday  : 0 missed days (weekend) → not stale
      Friday → Tuesday : 1 missed day (Monday)   → stale
      None             : always stale
    """
    if last_run_date is None:
        return True
    if today <= last_run_date:
        return False
    return count_missed_trading_days(last_run_date, today) > 0


def last_trading_day(today: date) -> date:
    """Return the most recent weekday on or before today."""
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d
