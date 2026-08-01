"""`POST /preview/factors` must persist NOTHING (real Postgres).

This is the load-bearing guarantee of the whole feature. The endpoint recomputes
the universe's factor scores under a config the LLM authored and nobody approved.
If it wrote a `factor_runs` / `factor_scores` / `regime_snapshots` row, the next
ranking would silently inherit a candidate's factors — the exact boundary
CLAUDE.md draws ("the LLM may suggest; Python validates and executes").

Nothing in FastAPI enforces read-only, and the endpoint reuses `_do_calculate`'s
loaders, which sit in a module that DOES write. So the property is asserted here
against a real, fully-migrated DB by counting rows either side of a live call.

Also covers the two refusals that keep the comparison honest — a `universe.*`
diff (unmodellable, because the preview deliberately reuses the prior run's
investable set) and lock contention.
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_COUNTED_TABLES = ("factor_runs", "factor_scores", "regime_snapshots",
                   "ranking_runs", "rankings", "execution_steps",
                   "execution_traces", "pipeline_runs")


class _pipeline_app_imported:
    """Import the pipeline's `app` package with redis stubbed, restore on exit.

    Mirrors `test_chain_no_rejectable_intent`'s isolation: sibling integration
    tests import a DIFFERENT service's `app`, so leaving ours resident would
    shadow them depending on collection order.
    """

    def __enter__(self):
        self._saved_path = list(sys.path)
        self._saved_mods = {k: v for k, v in sys.modules.items()
                            if k == "app" or k.startswith("app.")}
        for k in list(self._saved_mods):
            del sys.modules[k]
        self._saved_redis = {k: v for k, v in sys.modules.items()
                             if k == "redis" or k.startswith("redis.")}
        if "redis" not in sys.modules:
            _redis = types.ModuleType("redis")
            _ra = types.ModuleType("redis.asyncio")
            _re = types.ModuleType("redis.exceptions")

            class _T(Exception):
                pass

            _re.TimeoutError = _T

            class _FakeRedis:
                @classmethod
                def from_url(cls, *a, **k):
                    inst = MagicMock()
                    inst.xgroup_create = AsyncMock()
                    inst.xreadgroup = AsyncMock(return_value=[])
                    inst.xack = AsyncMock()
                    inst.aclose = AsyncMock()
                    return inst

            _ra.Redis = _FakeRedis
            _redis.asyncio = _ra
            _redis.exceptions = _re
            sys.modules["redis"] = _redis
            sys.modules["redis.asyncio"] = _ra
            sys.modules["redis.exceptions"] = _re
        sys.path.insert(0, os.path.join(_ROOT, "shared"))
        sys.path.insert(0, os.path.join(_ROOT, "services", "pipeline"))
        import app.main as pm  # noqa: E402
        self.pm = pm
        return pm

    def __exit__(self, *exc):
        for k in list(sys.modules):
            if k == "app" or k.startswith("app."):
                del sys.modules[k]
        sys.modules.update(self._saved_mods)
        sys.path[:] = self._saved_path
        return False


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    yield eng
    await eng.dispose()


async def _counts(eng) -> dict[str, int]:
    out = {}
    async with eng.connect() as conn:
        for t in _COUNTED_TABLES:
            out[t] = (await conn.execute(text(f"SELECT COUNT(*) FROM {t}"))).scalar_one()
    return out


async def _seed(eng) -> None:
    """A tiny but REAL dataset: enough history for the default 252-session
    momentum/vol windows would be huge, so the seeded config uses short windows.
    The point of this test is the write boundary, not factor quality."""
    import uuid
    from datetime import date, timedelta

    run_id = str(uuid.uuid4())
    tickers = ["AAA", "BBB", "CCC", "SPY"]
    d0 = date(2026, 1, 2)
    # The Postgres fixture is session-scoped; seed once and reuse.
    async with eng.connect() as conn:
        if (await conn.execute(text(
                "SELECT COUNT(*) FROM factor_runs WHERE strategy_id='test'"))).scalar_one():
            return
    async with eng.begin() as conn:
        await conn.execute(text(
            "INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count) "
            "VALUES ('TEST', :d, :n)"), {"d": d0, "n": len(tickers)})
        sid = (await conn.execute(text("SELECT MAX(id) FROM universe_snapshots"))).scalar_one()
        for t in tickers:
            await conn.execute(text(
                "INSERT INTO universe_tickers (snapshot_id, ticker, name, sector) "
                "VALUES (:s, :t, :n, 'Technology')"), {"s": sid, "t": t, "n": t})
        rows = []
        for t in tickers:
            px = 100.0
            for i in range(700):
                px *= 1.0 + (0.0006 if t != "SPY" else 0.0004) + 0.001 * ((i + len(t)) % 5 - 2)
                rows.append({"t": t, "d": d0 + timedelta(days=i), "p": round(px, 4)})
        for r in rows:
            await conn.execute(text(
                "INSERT INTO daily_prices (ticker, date, open, high, low, close, "
                "adjusted_close, volume) VALUES (:t, :d, :p, :p, :p, :p, :p, 5000000) "
                "ON CONFLICT DO NOTHING"), r)
        for t in tickers:
            if t == "SPY":
                continue
            await conn.execute(text(
                "INSERT INTO fundamentals (ticker, as_of_date, source, pe_ratio, pb_ratio, "
                "roe, debt_to_equity, revenue_growth, eps_growth, market_cap) "
                "VALUES (:t, :d, 'test', 15, 2, 0.15, 0.5, 0.08, 0.06, 5e9)"),
                {"t": t, "d": d0 + timedelta(days=699)})
        await conn.execute(text(
            "INSERT INTO factor_runs (run_id, strategy_id, status, score_date, completed_at) "
            "VALUES (CAST(:r AS uuid), 'test', 'success', :d, NOW())"),
            {"r": run_id, "d": d0 + timedelta(days=699)})
        for t in tickers:
            if t == "SPY":
                continue
            await conn.execute(text(
                "INSERT INTO factor_scores (run_id, ticker, score_date, momentum, scores) "
                "VALUES (CAST(:r AS uuid), :t, :d, 0.5, CAST('{\"momentum\": 0.5}' AS jsonb))"),
                {"r": run_id, "t": t, "d": d0 + timedelta(days=699)})


def _short_window_config(base: dict) -> dict:
    """700 seeded sessions is short for the shipped 252-day windows plus their 150-day
    buffer; shrink them so the preview produces a real ranking rather than an
    all-null one."""
    cfg = dict(base)
    fe = dict(cfg.get("factor_engine") or {})
    fe.update({"momentum_long_window": 126, "momentum_short_window": 21,
               "volatility_window": 63, "momentum_blend_windows": None,
               "spy_price_lookback_days": 400})
    cfg["factor_engine"] = fe
    uni = dict(cfg.get("universe") or {})
    uni.update({"min_price": 1.0, "min_avg_dollar_volume_20d": 0.0})
    cfg["universe"] = uni
    cfg["min_non_null_factors"] = 1
    cfg["required_factors"] = []
    return cfg


async def test_preview_writes_nothing(engine, async_dsn, monkeypatch, tmp_path):
    import json

    import yaml

    await _seed(engine)
    with _pipeline_app_imported() as pm:
        from stock_strategy_shared.loader import load_strategy

        base, _h = load_strategy(os.path.join(_ROOT, "strategies", "quality_core_v1.yaml"))
        cfg = _short_window_config(base.model_dump(mode="json"))
        path = tmp_path / "active.yaml"
        path.write_text(yaml.safe_dump(cfg))
        monkeypatch.setattr(pm, "STRATEGY_CONFIG_PATH", str(path))
        monkeypatch.setattr(pm, "engine", engine, raising=False)

        before = await _counts(engine)
        # a REAL factor_engine change: a different momentum method
        cand = json.loads(json.dumps(cfg))
        cand["factor_engine"]["momentum_method"] = "risk_adjusted"
        out = await pm.preview_factors({"config": cand})
        after = await _counts(engine)

    assert after == before, (
        "the preview wrote to the database: "
        + ", ".join(f"{k} {before[k]}->{after[k]}" for k in before if before[k] != after[k])
    )
    assert out["factor_engine_changed"] is True
    assert out["active_ranking"] and out["candidate_ranking"]
    assert set(out["active_ranking"][0]) == {"ticker", "rank", "composite_score"}


async def test_a_universe_change_is_refused_not_silently_ignored(engine, monkeypatch, tmp_path):
    """The preview reuses the prior run's investable set — that is WHY the diff is
    apples-to-apples. Honouring a universe change would break that silently, so it
    must 422 and name the rig that can model it."""
    import json

    import yaml
    from fastapi import HTTPException

    await _seed(engine)
    with _pipeline_app_imported() as pm:
        from stock_strategy_shared.loader import load_strategy

        base, _h = load_strategy(os.path.join(_ROOT, "strategies", "quality_core_v1.yaml"))
        cfg = _short_window_config(base.model_dump(mode="json"))
        path = tmp_path / "active.yaml"
        path.write_text(yaml.safe_dump(cfg))
        monkeypatch.setattr(pm, "STRATEGY_CONFIG_PATH", str(path))
        monkeypatch.setattr(pm, "engine", engine, raising=False)

        cand = json.loads(json.dumps(cfg))
        cand["universe"]["min_price"] = 25.0
        with pytest.raises(HTTPException) as ei:
            await pm.preview_factors({"config": cand})
    assert ei.value.status_code == 422
    assert "wind tunnel" in str(ei.value.detail)


async def test_a_candidate_with_a_longer_window_still_gets_its_history(
        engine, monkeypatch, tmp_path):
    """The loaders derive `price_lookback` from max(momentum_long_window,
    volatility_window). Loading against the ACTIVE config alone would hand a
    candidate that LENGTHENS either window a frame too short for it, nulling its
    factor — and that surfaces as a coverage collapse, which is the single
    artifact the tool's prompt tells the model to trust most. A false "this change
    destroys momentum" is worse than no preview at all.

    Active momentum_long_window is 126 (→ 276 days loaded); the candidate asks for
    504, which needs more history than the active lookback provides.
    """
    import json

    import yaml

    await _seed(engine)
    with _pipeline_app_imported() as pm:
        from stock_strategy_shared.loader import load_strategy

        base, _h = load_strategy(os.path.join(_ROOT, "strategies", "quality_core_v1.yaml"))
        cfg = _short_window_config(base.model_dump(mode="json"))
        path = tmp_path / "active.yaml"
        path.write_text(yaml.safe_dump(cfg))
        monkeypatch.setattr(pm, "STRATEGY_CONFIG_PATH", str(path))
        monkeypatch.setattr(pm, "engine", engine, raising=False)

        cand = json.loads(json.dumps(cfg))
        cand["factor_engine"]["momentum_long_window"] = 504
        out = await pm.preview_factors({"config": cand})

    mom = out["factor_coverage"]["momentum"]
    assert mom["active_non_null"] > 0, "baseline momentum is null — fixture is broken"
    assert mom["candidate_non_null"] > 0, (
        "the candidate's momentum was nulled by a too-short price frame, not by the "
        "config change — the loader lookback must widen to cover BOTH configs"
    )


async def test_lock_contention_returns_409_not_a_slow_success(engine, monkeypatch, tmp_path):
    """A preview must never queue behind the daily chain: it holds a
    universe-scale frame and the pipeline runs under a hard mem_limit."""
    import yaml
    from fastapi import HTTPException

    with _pipeline_app_imported() as pm:
        from stock_strategy_shared.loader import load_strategy

        base, _h = load_strategy(os.path.join(_ROOT, "strategies", "quality_core_v1.yaml"))
        cfg = _short_window_config(base.model_dump(mode="json"))
        path = tmp_path / "active.yaml"
        path.write_text(yaml.safe_dump(cfg))
        monkeypatch.setattr(pm, "STRATEGY_CONFIG_PATH", str(path))
        monkeypatch.setattr(pm, "engine", engine, raising=False)
        monkeypatch.setattr(pm, "PREVIEW_LOCK_TIMEOUT_SECS", 0.05)

        await _seed(engine)
        await pm._job_lock.acquire()
        try:
            with pytest.raises(HTTPException) as ei:
                await pm.preview_factors({"config": cfg})
        finally:
            pm._job_lock.release()
    assert ei.value.status_code == 409
    assert "busy" in str(ei.value.detail)
