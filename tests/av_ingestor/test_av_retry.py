"""Audit P1 — Alpha Vantage client retry/backoff + retryable classification.

The client now retries transient faults (network/timeout/5xx and AV in-band rate-limit
"Note"/"Information") with exponential backoff, and does NOT retry permanent ones
(bad symbol "Error Message", invalid key/plan "Information"). Newer AV rate-limits
arrive under the "Information" key and must be treated as retryable rate-limits, not a
fatal key error.
"""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.alpha_vantage import AVClient, AVError, _is_rate_limit_msg


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Kill both the throttle sleep and the backoff sleep so tests are instant.
    monkeypatch.setattr("app.alpha_vantage.asyncio.sleep", AsyncMock())


def _resp(json_body=None, *, status=200):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=json_body if json_body is not None else {})
    if status >= 400:
        err = httpx.HTTPStatusError("http", request=MagicMock(), response=r)
        r.raise_for_status = MagicMock(side_effect=err)
    else:
        r.raise_for_status = MagicMock()
    return r


def _client(max_retries=3):
    c = AVClient(api_key="k", rate_limit_rpm=75)
    c._max_retries = max_retries
    return c


# ── classifier ──────────────────────────────────────────────────────────────────

def test_is_rate_limit_msg():
    assert _is_rate_limit_msg("You have reached the 75 requests per minute rate limit")
    assert _is_rate_limit_msg("Thank you for using Alpha Vantage! standard API call frequency is 5 calls per minute")
    assert not _is_rate_limit_msg("the parameter apikey is invalid or missing")


# ── retryable paths ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_note_rate_limit_retries_then_succeeds():
    c = _client()
    c._client.get = AsyncMock(side_effect=[
        _resp({"Note": "Our standard API call frequency is 5 calls per minute"}),
        _resp({"ok": 1}),
    ])
    out = await c._get({"function": "X"})
    assert out == {"ok": 1}
    assert c._client.get.call_count == 2


@pytest.mark.asyncio
async def test_information_rate_limit_is_retryable():
    c = _client()
    c._client.get = AsyncMock(side_effect=[
        _resp({"Information": "you have reached the 75 requests per minute rate limit"}),
        _resp({"ok": 2}),
    ])
    out = await c._get({"function": "X"})
    assert out == {"ok": 2}
    assert c._client.get.call_count == 2


@pytest.mark.asyncio
async def test_transport_error_retried_then_succeeds():
    c = _client()
    c._client.get = AsyncMock(side_effect=[httpx.ConnectError("refused"), _resp({"ok": 3})])
    out = await c._get({"function": "X"})
    assert out == {"ok": 3}
    assert c._client.get.call_count == 2


@pytest.mark.asyncio
async def test_5xx_retried():
    c = _client()
    c._client.get = AsyncMock(side_effect=[_resp(status=503), _resp({"ok": 4})])
    out = await c._get({"function": "X"})
    assert out == {"ok": 4}


# ── non-retryable paths (raise immediately, no extra calls) ─────────────────────

@pytest.mark.asyncio
async def test_information_key_issue_not_retried():
    c = _client()
    c._client.get = AsyncMock(side_effect=[
        _resp({"Information": "the parameter apikey is invalid or missing"}),
        _resp({"ok": 9}),
    ])
    with pytest.raises(AVError) as ei:
        await c._get({"function": "X"})
    assert ei.value.retryable is False
    assert c._client.get.call_count == 1   # no retry on a permanent key issue


@pytest.mark.asyncio
async def test_error_message_not_retried():
    c = _client()
    c._client.get = AsyncMock(side_effect=[_resp({"Error Message": "Invalid API call / bad symbol"})])
    with pytest.raises(AVError) as ei:
        await c._get({"function": "X"})
    assert ei.value.retryable is False
    assert c._client.get.call_count == 1


@pytest.mark.asyncio
async def test_4xx_not_retried():
    c = _client()
    c._client.get = AsyncMock(side_effect=[_resp(status=400)])
    with pytest.raises(AVError) as ei:
        await c._get({"function": "X"})
    assert ei.value.retryable is False
    assert c._client.get.call_count == 1


# ── exhaustion ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persistent_rate_limit_exhausts_retries_then_raises():
    c = _client(max_retries=2)
    c._client.get = AsyncMock(return_value=_resp({"Note": "5 calls per minute rate limit"}))
    with pytest.raises(AVError) as ei:
        await c._get({"function": "X"})
    assert ei.value.retryable is True
    assert c._client.get.call_count == 3   # initial + 2 retries
