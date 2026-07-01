"""Regression: _detect_config_skew must NOT throw on the missing vetter_runs.config_hash
column (it queried a column that doesn't exist → UndefinedColumnError every run, which
aborted the check and — with DELTA_FAIL_ON_CONFIG_SKEW — could wedge the delta). Runs
against the real migrated schema.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
sys.path.insert(0, os.path.join(_ROOT, "shared"))
sys.path.insert(0, os.path.join(_ROOT, "services", "pipeline"))
import app.main as pl  # noqa: E402

pytestmark = pytest.mark.asyncio
D = date(2026, 6, 30)


@pytest_asyncio.fixture
async def engine(async_dsn):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        for t in ("portfolio_runs", "ranking_runs", "factor_runs"):
            await conn.execute(text(f"TRUNCATE {t} RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


async def _portfolio(conn, cfg_hash):
    fr, rr, pr = (str(uuid.uuid4()) for _ in range(3))
    await conn.execute(text("INSERT INTO factor_runs (run_id, strategy_id, status, score_date) "
                            "VALUES (CAST(:r AS uuid),'t','success',:d)"), {"r": fr, "d": D})
    await conn.execute(text(
        "INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, regime, rank_date, "
        "status, config_hash) VALUES (CAST(:r AS uuid),CAST(:f AS uuid),'t','bull_calm',:d,'success',:c)"),
        {"r": rr, "f": fr, "d": D, "c": cfg_hash})
    await conn.execute(text(
        "INSERT INTO portfolio_runs (run_id, source_ranking_run_id, strategy_id, config_hash, regime, "
        "portfolio_date, status, completed_at) VALUES (CAST(:p AS uuid),CAST(:r AS uuid),'t',:c,"
        "'bull_calm',:d,'success',NOW())"), {"p": pr, "r": rr, "c": cfg_hash, "d": D})


async def test_no_throw_and_detects_portfolio_skew(engine, monkeypatch):
    monkeypatch.setattr(pl, "engine", engine, raising=False)
    monkeypatch.setattr(pl, "config_hash", "AAAA", raising=False)

    # Consistent: portfolio built under the same config as the delta → no skew, no throw.
    async with engine.begin() as conn:
        await _portfolio(conn, "AAAA")
    skew = await pl._detect_config_skew("AAAA")
    assert skew == {}, f"expected no skew, got {skew}"

    # Portfolio built under a DIFFERENT config → detected (and still no UndefinedColumnError).
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE portfolio_runs, ranking_runs, factor_runs RESTART IDENTITY CASCADE"))
        await _portfolio(conn, "BBBB")
    skew = await pl._detect_config_skew("AAAA")
    assert skew.get("portfolio") == "BBBB", f"expected portfolio skew, got {skew}"


async def test_ranking_arg_skew(engine, monkeypatch):
    monkeypatch.setattr(pl, "engine", engine, raising=False)
    monkeypatch.setattr(pl, "config_hash", "AAAA", raising=False)
    async with engine.begin() as conn:
        await _portfolio(conn, "AAAA")
    # The ranking the delta anchors on was scored under a different config → flagged.
    skew = await pl._detect_config_skew("OLDHASH")
    assert skew.get("ranking") == "OLDHASH"
