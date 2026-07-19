"""Single source for the trading-day timezone — used by scheduler, pipeline, and
risk-service so they cannot disagree on "today/now in ET".

Why this exists (split-brain): the scheduler keys the daily chain on the trading
SESSION date in SCHEDULE_TZ; the pipeline must compute `chain_date` in the SAME
zone (a mismatch re-introduces the evening re-trigger loop); and risk-service buckets
the daily-loss baseline + turnover day by the trading date. These three each
duplicated `ZoneInfo(os.getenv(...))` with a SILENT fallback to the process zone
(UTC) when tzdata was missing — so a broken image could make them disagree on the
calendar date with no error. This module centralizes resolution and FAILS FAST
(raises) instead of silently using the wrong zone, and supports one canonical env
(`STOCKER_TZ`) so they can be set together.
"""
from __future__ import annotations

import os
from datetime import date, datetime

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TRADING_TZ = "America/New_York"


def resolve_trading_tz(*override_env_names: str, default: str = DEFAULT_TRADING_TZ) -> ZoneInfo:
    """Resolve the trading-day timezone, FAILING FAST on an unloadable zone.

    Precedence: the canonical `STOCKER_TZ` env, then any service-specific override
    env names (back-compat, e.g. SCHEDULE_TZ / RISK_TZ), then `default`.

    Raises RuntimeError if the chosen zone can't be loaded (tzdata missing / typo).
    Silently falling back to UTC was the bug — wrong trading dates with no signal.
    The deployed base image ships tzdata, so this only trips on a genuinely broken
    environment, which is exactly when we WANT a loud startup failure.
    """
    name = os.getenv("STOCKER_TZ")
    if not name:
        for env_name in override_env_names:
            v = os.getenv(env_name)
            if v:
                name = v
                break
    name = name or default
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, Exception) as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Cannot load trading timezone '{name}' (tzdata missing or invalid name?): {exc}. "
            f"Set STOCKER_TZ to a valid IANA zone, or install tzdata in the image."
        ) from exc


def trading_now(tz: ZoneInfo) -> datetime:
    """Current timezone-aware datetime in the trading zone."""
    return datetime.now(tz)


def trading_today(tz: ZoneInfo) -> date:
    """Today's calendar date in the trading zone."""
    return datetime.now(tz).date()


def market_today(*override_env_names: str) -> date:
    """CANONICAL "today" for any market-coupled decision (audit findings #1/#2).

    Containers run in UTC, so `date.today()` / `datetime.now(timezone.utc).date()`
    flip to the NEXT calendar day at 20:00 ET — splitting one US trading evening
    (chain at 22:30 ET, auto-approve, ingest rotation) across two "days". Every
    service that needs a market-day should call THIS instead of its own clock.
    Same resolution rules as resolve_trading_tz (STOCKER_TZ → overrides → ET).
    """
    return trading_today(resolve_trading_tz(*override_env_names))


def weekday_sessions_between(earlier: date, later: date) -> int:
    """Approximate market sessions elapsed: weekdays in the half-open (earlier,
    later]. Friday close checked on Monday = 1, not 3 — so session-freshness
    thresholds don't mis-fire over weekends (audit finding #9). Holidays are
    still counted (no exchange calendar here); thresholds should keep a small
    margin for them. 0 when later <= earlier."""
    if later <= earlier:
        return 0
    full_weeks, rem = divmod((later - earlier).days, 7)
    count = full_weeks * 5
    start_wd = earlier.weekday()
    for i in range(1, rem + 1):
        if (start_wd + i) % 7 < 5:
            count += 1
    return count
