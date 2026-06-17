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
