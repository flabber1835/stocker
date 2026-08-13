"""Wealth Core certification endpoint.

This service is certification-only. Startup schema creation and orphan recovery
are readiness requirements: a process that cannot prove either must not report
healthy and must not accept a rehearsal.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import wealth_core_api
from app.jobs_busy import (
    CorpusGenerationUnavailable,
    acquire_engine_process_lease,
    load_ready_data_generation,
    release_engine_process_lease,
)

BT_DATABASE_URL = os.environ.get("BT_DATABASE_URL", "")
if not BT_DATABASE_URL:
    raise RuntimeError("Missing required env var: BT_DATABASE_URL")

engine = create_async_engine(
    BT_DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=3)
_ready = False


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Own this database, initialize it, or fail before recovery writes."""
    global _ready
    lease_conn = await engine.connect()
    lease_acquired = False
    try:
        # SESSION-SCOPED and held on this dedicated connection until shutdown.
        # A second process must fail HERE, before its startup pass can call an
        # active first process's background run an abandoned one.
        await acquire_engine_process_lease(lease_conn)
        await lease_conn.commit()
        lease_acquired = True
        async with engine.begin() as conn:
            for ddl in wealth_core_api.WEALTH_CORE_DDL:
                await conn.execute(text(ddl))
            await conn.execute(text(
                "UPDATE bt_wealth_core_runs SET status='failed', "
                "completed_at=NOW(), "
                "error_message='RESTART_ABORTED: engine restarted mid-run; the "
                "background task did not survive. Re-submit.' "
                "WHERE status='running'"))
        _ready = True
        yield
    finally:
        _ready = False
        try:
            if lease_acquired:
                await release_engine_process_lease(lease_conn)
                await lease_conn.commit()
        finally:
            await lease_conn.close()
            await engine.dispose()


app = FastAPI(title="bt-engine (wealth-core certification)", lifespan=lifespan)
wealth_core_api.configure(engine=engine)
app.include_router(wealth_core_api.router)


@app.get("/health")
async def health():
    """Readiness, not process liveness."""
    if not _ready:
        raise HTTPException(503, "startup schema/orphan recovery is incomplete")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM bt_wealth_core_runs LIMIT 1"))
            generation = await load_ready_data_generation(conn)
    except CorpusGenerationUnavailable as exc:
        raise HTTPException(
            503, f"certification corpus not ready: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - readiness fails closed
        raise HTTPException(503, f"database/schema not ready: {exc}") from exc
    return {
        "ok": True,
        "surface": "wealth-core-certification",
        "data_generation": generation.to_dict(),
    }
