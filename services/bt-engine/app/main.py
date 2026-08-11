"""bt-engine — the Wealth Core certification endpoint, and nothing else.

CERTIFICATION-ONLY. This service must never enter the production dependency
graph; see CLAUDE.md. Sentinel is the appliance, and it has its own database,
its own corpus and its own execution layer. What lives here is the rehearsal
surface Wealth Core is certified against, running on the backtest machine
against bt-postgres.

## What this file used to be

1,039 lines of the retired Stocker backtester: `/jobs/run` stepping
`app/sim.py`, `/sweeps/run` driving a parameter search, coverage and parity
gates, `bt_sweeps` DDL. The Wealth Core router was mounted at the bottom of it,
almost as an afterthought.

The legacy eradication (ac0c71f) deleted `app/sim.py`, `app/sweep.py`,
`app/coverage.py`, `app/parity.py`, `app/postmortem.py` and
`stock_strategy_shared.loader` — and left this file importing all of them. The
result was worse than dead code: **the service could not start at all**, so the
Wealth Core endpoint the eradication deliberately preserved was mounted on an
entrypoint that raised `ModuleNotFoundError` before FastAPI ever saw it. The
certification path was broken by the cleanup that was supposed to leave it
alone, and nothing said so — the container simply crash-looped.

The repair is subtraction, not restoration. Nothing deleted is brought back to
satisfy an import; what is kept is what has a named certification purpose. The
retired API is recoverable from `stocker-legacy-2026-08` if it is ever wanted,
which it should not be.

## What remains, and why each piece

```text
engine            bt-postgres. The corpus and the run tables both live there
WEALTH_CORE_DDL   the rehearsal's own tables, created at startup
orphan reclaim    a run whose background task died reads `running` FOREVER
/health           liveness for compose
/wealth-core/*    the certification surface itself
```

The orphan reclaim is the one piece of startup logic worth keeping in full. A
Wealth Core run lives in a background task; when the engine restarts the task is
gone and nothing updates its row, so it reads `running` indefinitely — which is
indistinguishable from a run legitimately still loading its corpus, exactly the
state an operator watches during the first minutes of a multi-hour job.
Measured cost of the gap: a three-year rehearsal killed 16 minutes in by a
container restart, then waited on for half an hour with no query running and no
process behind it.

`bt_runs` and `bt_sweeps` are NOT reclaimed here any more, because nothing in
this service can create them.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import wealth_core_api

BT_DATABASE_URL = os.environ.get("BT_DATABASE_URL", "")
if not BT_DATABASE_URL:
    raise RuntimeError("Missing required env var: BT_DATABASE_URL")

# Small pool, deliberately. One rehearsal at a time is the whole operating
# model — `wealth_core_api` enforces it with a `running` row check — so a large
# pool would only buy the ability to start work that must not run concurrently.
engine = create_async_engine(BT_DATABASE_URL, pool_pre_ping=True,
                             pool_size=3, max_overflow=3)


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        async with engine.begin() as conn:
            for ddl in wealth_core_api.WEALTH_CORE_DDL:
                await conn.execute(text(ddl))
            # A RUN WHOSE PROCESS IS GONE MUST NOT READ `running`.
            #
            # The task died with the container; nothing will ever update the
            # row. Left alone it is indistinguishable from a healthy run still
            # loading its corpus — the row says running, `/progress` says not
            # started, and both are what a working run looks like too.
            await conn.execute(text(
                "UPDATE bt_wealth_core_runs SET status='failed', "
                "completed_at=NOW(), "
                "error_message='RESTART_ABORTED: engine restarted mid-run. The "
                "job lived in a background task and did not survive; nothing "
                "was written and nothing is still working. Re-submit.' "
                "WHERE status='running'"))
    except Exception as exc:  # noqa: BLE001 — tables may predate init on first boot
        print(f"[bt-engine] startup DDL/orphan pass skipped: {exc}")
    yield
    await engine.dispose()


app = FastAPI(title="bt-engine (wealth-core certification)", lifespan=lifespan)

wealth_core_api.configure(engine=engine)
app.include_router(wealth_core_api.router)


@app.get("/health")
async def health():
    return {"ok": True, "surface": "wealth-core-certification"}
