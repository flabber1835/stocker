"""G1/G3: AV throttle classification + the shared Redis rate limiter."""
from unittest.mock import AsyncMock

import pytest

from app.alpha_vantage import AVClient, AVError
from stock_strategy_shared.rate_limit import RedisRateLimiter


# ── G1: rate-limit classification feeds the circuit-breaker ──────────────────

def test_classify_marks_note_rate_limited():
    c = AVClient(api_key="k")
    with pytest.raises(AVError) as ei:
        c._classify({"Note": "Thank you for using Alpha Vantage! ... 25 requests per day"})
    assert ei.value.retryable is True and ei.value.rate_limited is True


def test_classify_marks_rate_limit_information():
    c = AVClient(api_key="k")
    with pytest.raises(AVError) as ei:
        c._classify({"Information": "Our standard API rate limit is 25 requests per day"})
    assert ei.value.rate_limited is True


def test_classify_keyplan_information_is_terminal_not_rate_limited():
    c = AVClient(api_key="k")
    with pytest.raises(AVError) as ei:
        c._classify({"Information": "the parameter apikey is invalid"})
    assert ei.value.retryable is False and ei.value.rate_limited is False


def test_classify_error_message_not_rate_limited():
    c = AVClient(api_key="k")
    with pytest.raises(AVError) as ei:
        c._classify({"Error Message": "Invalid API call"})
    assert ei.value.rate_limited is False


# ── G3: AVClient defers to a shared limiter when provided ─────────────────────

@pytest.mark.asyncio
async def test_throttle_uses_shared_limiter(monkeypatch):
    limiter = AsyncMock()
    sleeps = []
    monkeypatch.setattr("app.alpha_vantage.asyncio.sleep",
                        lambda s: sleeps.append(s) or _noop())
    c = AVClient(api_key="k", rate_limit_rpm=3, limiter=limiter)
    await c._throttle()
    limiter.acquire.assert_awaited_once()
    # the per-process window sleep path is skipped when a shared limiter is wired
    assert not sleeps


async def _noop():
    return None


# ── G3: RedisRateLimiter acquire semantics ───────────────────────────────────

class _FakeRedis:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    async def eval(self, *a, **k):
        self.calls += 1
        r = self._results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.mark.asyncio
async def test_limiter_proceeds_when_slot_free(monkeypatch):
    slept = []
    monkeypatch.setattr("stock_strategy_shared.rate_limit.asyncio.sleep",
                        AsyncMock(side_effect=lambda s: slept.append(s)))
    lim = RedisRateLimiter(_FakeRedis([b"0"]), "k", rpm=75)
    await lim.acquire()
    assert not slept


@pytest.mark.asyncio
async def test_limiter_waits_then_proceeds(monkeypatch):
    slept = []
    async def _sleep(s):
        slept.append(s)
    monkeypatch.setattr("stock_strategy_shared.rate_limit.asyncio.sleep", _sleep)
    lim = RedisRateLimiter(_FakeRedis([b"0.5", b"0"]), "k", rpm=75)
    await lim.acquire()
    assert slept and slept[0] >= 0.5


@pytest.mark.asyncio
async def test_limiter_fails_open_on_redis_error(monkeypatch):
    # A Redis outage must NOT block ingestion — acquire returns (caller's in-process
    # limiter remains the floor).
    lim = RedisRateLimiter(_FakeRedis([RuntimeError("redis down")]), "k", rpm=75)
    await lim.acquire()   # must not raise
