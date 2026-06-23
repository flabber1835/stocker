"""Audit P2 — sliding-window rate limiter: a hard cap of rate_limit_rpm calls per
trailing 60s (not just a fixed inter-call gap), so a post-idle resume can't burst past
the per-minute budget.
"""
from unittest.mock import AsyncMock

import pytest

from app.alpha_vantage import AVClient


@pytest.mark.asyncio
async def test_window_cap_engages_after_rpm_calls(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("app.alpha_vantage.time.monotonic", lambda: clock[0])
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr("app.alpha_vantage.asyncio.sleep", fake_sleep)

    c = AVClient(api_key="k", rate_limit_rpm=3)
    # 3 calls fill the window; the 4th (still at t=0) must request a ~60s window sleep.
    for _ in range(4):
        await c._throttle()
    assert any(s >= 60.0 for s in sleeps), f"expected a ~60s window sleep, got {sleeps}"


@pytest.mark.asyncio
async def test_no_window_sleep_under_cap(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("app.alpha_vantage.time.monotonic", lambda: clock[0])
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr("app.alpha_vantage.asyncio.sleep", fake_sleep)

    c = AVClient(api_key="k", rate_limit_rpm=5)
    for _ in range(2):           # under the cap of 5
        await c._throttle()
    assert all(s < 60.0 for s in sleeps), f"no window sleep expected under cap, got {sleeps}"


@pytest.mark.asyncio
async def test_window_clears_after_time_passes(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("app.alpha_vantage.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.alpha_vantage.asyncio.sleep", AsyncMock())

    c = AVClient(api_key="k", rate_limit_rpm=3)
    for _ in range(3):
        await c._throttle()
    assert len(c._call_times) == 3
    clock[0] = 61.0              # all prior calls age out of the 60s window
    await c._throttle()
    assert len(c._call_times) == 1   # window pruned, only the new call remains
