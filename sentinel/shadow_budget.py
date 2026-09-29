"""One bounded wall-clock cutoff shared by shadow supervision and acquisition."""
from datetime import datetime, timedelta, timezone
import math
import os

DEADLINE_ENV = "SENTINEL_SHADOW_ADVANCE_DEADLINE_UTC"


def seconds():
    value = float(os.environ.get("SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS", "7200"))
    if not math.isfinite(value) or not 30 <= value <= 7200:
        raise ValueError("SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS must be in [30,7200]")
    return value


def now():
    return datetime.now(timezone.utc)


def cutoff():
    limit = now() + timedelta(seconds=seconds())
    raw = os.environ.get(DEADLINE_ENV)
    if raw is not None:
        supplied = datetime.fromisoformat(raw)
        if supplied.utcoffset() != timedelta(0):
            raise ValueError("shadow advance deadline must be explicit UTC")
        limit = min(limit, supplied)
    require_remaining(limit)
    return limit


def require_remaining(deadline):
    from sentinel.feed.rolling_jobs import JobDeadlineExceeded
    if deadline <= now():
        raise JobDeadlineExceeded("shadow advance deadline exhausted")
