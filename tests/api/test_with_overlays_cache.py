"""Tests for the /rankings/with-overlays per-run cache.

The overlay query is expensive (rank_slope REGR + prior_rank over the full
rankings table, ~60s) and previously ran on every dashboard load/refresh — which
tripped the proxy's 60s timeout ("no data") and exhausted the DB connection pool
under concurrent refreshes. The endpoint is now a cache wrapper around
`_compute_with_overlays`, keyed by (limit, run-key) where run-key = latest
ranking/vetter/sync run ids:

  - identical run-key  → served from cache, compute runs ONCE
  - changed  run-key   → cache invalidated, recompute
  - concurrent misses  → single-flight (one compute), stale served meanwhile
"""
from __future__ import annotations

import asyncio

import pytest

from app import main


@pytest.fixture(autouse=True)
def _clear_cache():
    main._overlay_cache.clear()
    main._overlay_locks.clear()
    # The wrapper short-circuits to an empty payload when engine is None; give it a
    # truthy sentinel so it proceeds to the (patched) run-key + compute path.
    saved = main.engine
    main.engine = _FakeEngine()
    yield
    main.engine = saved
    main._overlay_cache.clear()
    main._overlay_locks.clear()


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeEngine:
    def connect(self):
        return _FakeConn()


def _patch_runkey(monkeypatch, key):
    async def _rk(_conn):
        return key
    monkeypatch.setattr(main, "_current_overlay_run_key", _rk)


def test_same_runkey_computes_once(monkeypatch):
    calls = {"n": 0}

    async def _compute(limit=100, only_tickers=None):
        calls["n"] += 1
        return {"count": 1, "limit": limit, "rankings": []}

    _patch_runkey(monkeypatch, ("r1", "v1", "s1"))
    monkeypatch.setattr(main, "_compute_with_overlays", _compute)

    async def _run():
        a = await main.get_rankings_with_overlays(limit=100)
        b = await main.get_rankings_with_overlays(limit=100)
        return a, b

    a, b = asyncio.run(_run())
    assert a == b
    assert calls["n"] == 1  # second call served from cache


def test_runkey_change_invalidates(monkeypatch):
    calls = {"n": 0}
    key = {"v": ("r1", "v1", "s1")}

    async def _compute(limit=100, only_tickers=None):
        calls["n"] += 1
        return {"n": calls["n"]}

    async def _rk(_conn):
        return key["v"]

    monkeypatch.setattr(main, "_current_overlay_run_key", _rk)
    monkeypatch.setattr(main, "_compute_with_overlays", _compute)

    async def _run():
        first = await main.get_rankings_with_overlays(limit=50)
        key["v"] = ("r2", "v1", "s1")  # a new ranking run landed
        second = await main.get_rankings_with_overlays(limit=50)
        return first, second

    first, second = asyncio.run(_run())
    assert calls["n"] == 2          # recomputed after key change
    assert first != second


def test_limit_keys_are_independent(monkeypatch):
    calls = {"n": 0}

    async def _compute(limit=100, only_tickers=None):
        calls["n"] += 1
        return {"limit": limit}

    _patch_runkey(monkeypatch, ("r1", "v1", "s1"))
    monkeypatch.setattr(main, "_compute_with_overlays", _compute)

    async def _run():
        await main.get_rankings_with_overlays(limit=100)
        await main.get_rankings_with_overlays(limit=50)
        await main.get_rankings_with_overlays(limit=100)  # cached

    asyncio.run(_run())
    assert calls["n"] == 2  # one per distinct limit; 3rd call cached


def test_tickers_scopes_normalizes_and_caches_by_set(monkeypatch):
    """`tickers=` (Target tab) scopes the compute to a set, normalizes it
    (upper/sorted/dedup), caches by that set, and is independent of the limit key."""
    calls = []

    async def _compute(limit=100, only_tickers=None):
        calls.append(only_tickers)
        return {"only": only_tickers}

    _patch_runkey(monkeypatch, ("r1", "v1", "s1"))
    monkeypatch.setattr(main, "_compute_with_overlays", _compute)

    async def _run():
        a = await main.get_rankings_with_overlays(tickers="aapl,msft")
        b = await main.get_rankings_with_overlays(tickers="MSFT, AAPL,msft")  # same set
        c = await main.get_rankings_with_overlays(limit=100)                   # separate key
        return a, b

    a, b = asyncio.run(_run())
    assert calls[0] == ["AAPL", "MSFT"]                 # normalized + sorted + deduped
    assert a == b                                       # same set → cache hit, no recompute
    ticker_computes = [x for x in calls if x is not None]
    assert len(ticker_computes) == 1                    # scoped compute ran exactly once
    assert None in calls                                # the limit=100 path computed separately


def test_single_flight_serves_stale_during_recompute(monkeypatch):
    """While a recompute for a new run-key is in flight, a concurrent request gets
    the prior (stale) payload immediately rather than queueing behind the ~60s
    compute — stale-while-revalidate."""
    started = asyncio.Event()
    release = asyncio.Event()
    key = {"v": ("r1", "v1", "s1")}

    async def _compute(limit=100, only_tickers=None):
        if key["v"][0] == "r2":
            started.set()
            await release.wait()      # hold the recompute open
            return {"run": "r2"}
        return {"run": "r1"}

    async def _rk(_conn):
        return key["v"]

    monkeypatch.setattr(main, "_current_overlay_run_key", _rk)
    monkeypatch.setattr(main, "_compute_with_overlays", _compute)

    async def _run():
        warm = await main.get_rankings_with_overlays(limit=100)   # cache r1
        key["v"] = ("r2", "v1", "s1")
        slow = asyncio.create_task(main.get_rankings_with_overlays(limit=100))
        await started.wait()                                       # recompute holds lock
        stale = await main.get_rankings_with_overlays(limit=100)   # must NOT block
        release.set()
        fresh = await slow
        return warm, stale, fresh

    warm, stale, fresh = asyncio.run(_run())
    assert warm == {"run": "r1"}
    assert stale == {"run": "r1"}   # served stale while r2 computed
    assert fresh == {"run": "r2"}
