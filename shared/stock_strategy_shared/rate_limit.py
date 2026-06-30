"""Shared cross-process rate limiter (G3) — an account-wide sliding-window budget
backed by Redis, so EVERY Alpha Vantage consumer (av-ingestor's per-ticker client,
the LISTING_STATUS path, and llm-vetter) draws from ONE 75-req/min pool that survives
restarts. The per-process limiter in av-ingestor reset its window every run and was
blind to other consumers, so the documented account-wide cap could be breached and a
degraded day re-ran the full fetch without the budget ever recovering.

Correctness: the window is maintained in a Redis sorted set of timestamps under a Lua
script run server-side, so the check-and-claim is ATOMIC across processes (the whole
point — two consumers can't both see "room" and both proceed). The Redis server clock
is the single time source (no cross-host skew). Falls back to a no-op (the caller's
own in-process limiter still applies) when Redis is unavailable, so a Redis outage
degrades to the prior behaviour rather than blocking ingestion.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

# Atomic sliding-window admission. KEYS[1]=bucket key; ARGV: window secs, limit,
# unique member. Uses redis server TIME as the clock. Returns 0 to proceed, else the
# seconds to wait before the oldest call ages out of the window.
_LUA = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local member = ARGV[3]
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000.0
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, math.ceil(window * 1000) + 1000)
  return '0'
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local wait = (tonumber(oldest[2]) + window) - now
if wait < 0 then wait = 0 end
return tostring(wait)
"""


class RedisRateLimiter:
    """Async sliding-window limiter. `acquire()` blocks until a slot is free."""

    def __init__(self, redis_client, key: str, rpm: int, window: float = 60.0,
                 poll_cap: float = 5.0):
        self._redis = redis_client
        self._key = key
        self._rpm = max(1, int(rpm))
        self._window = float(window)
        self._poll_cap = float(poll_cap)   # never sleep longer than this between checks

    async def acquire(self) -> None:
        while True:
            member = f"{uuid.uuid4()}"
            try:
                res = await self._redis.eval(
                    _LUA, 1, self._key, str(self._window), str(self._rpm), member
                )
            except Exception:
                # Redis unavailable → fail OPEN (don't block ingestion). The caller's
                # in-process limiter remains the floor; a brief Redis blip must not wedge
                # the fetch. Correctness of the shared cap is best-effort by design.
                return
            wait = float(res.decode() if isinstance(res, (bytes, bytearray)) else res)
            if wait <= 0:
                return
            await asyncio.sleep(min(wait + 0.01, self._poll_cap))


def make_av_limiter(redis_url: Optional[str], rpm: int,
                    key: str = "av:ratelimit:global") -> Optional[RedisRateLimiter]:
    """Build the account-wide AV limiter from REDIS_URL, or None when Redis isn't
    configured (caller falls back to its per-process limiter). Import of redis.asyncio
    is lazy so non-Redis deployments/tests don't require the dependency."""
    if not redis_url:
        return None
    try:
        from redis import asyncio as aioredis  # type: ignore
    except Exception:
        return None
    client = aioredis.from_url(redis_url)
    return RedisRateLimiter(client, key, rpm)


# Allow overriding the shared bucket key (e.g. a separate AV account per deploy).
AV_RATE_LIMIT_KEY = os.getenv("AV_RATE_LIMIT_KEY", "av:ratelimit:global")
