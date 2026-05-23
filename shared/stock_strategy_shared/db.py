"""Database startup utilities."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def wait_for_db(engine, retries: int = 30, delay: float = 3.0) -> None:
    """
    Retry a lightweight DB ping until Postgres is ready to accept connections.

    pg_isready can return healthy before Postgres finishes initialising its
    data directory (especially on first boot on slow NAS hardware). This
    retry loop bridges that gap so services don't crash on startup.
    Default: 30 retries × 3s = 90s max wait — sufficient for cold NAS boot.
    """
    from sqlalchemy import text

    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            if attempt == retries:
                raise RuntimeError(
                    f"Database not ready after {retries} attempts: {exc}"
                ) from exc
            log.warning(
                "DB not ready (attempt %d/%d): %r — retrying in %.0fs",
                attempt, retries, exc, delay,
            )
            await asyncio.sleep(delay)


def warm_up_db_in_background(engine, service_name: str = "service") -> asyncio.Task:
    """Schedule wait_for_db as a background task so the FastAPI lifespan can
    yield immediately and the service starts serving /health right away.

    Why this exists: with `await wait_for_db(engine)` inside lifespan, uvicorn
    does not accept HTTP requests until the ping succeeds. On slow NAS hardware
    this can take 60-90s, but docker's healthcheck is `start_period=20s +
    5 retries × 5s = 45s` — so the container is marked unhealthy and
    `restart: unless-stopped` triggers a restart loop the service can never
    escape (each restart begins another wait_for_db that outlasts another
    45s healthcheck window). User-visible symptom: "Container … Error78.4s"
    in `docker compose up` output on Synology NAS.

    Returning a task lets the caller hold a reference (FastAPI lifespan
    typically just discards it). The task logs success/failure on its own
    so callers don't need to await it.
    """
    async def _warm_up():
        try:
            await wait_for_db(engine)
            print(f"[{service_name}] DB connected; persistence enabled", flush=True)
        except Exception as exc:
            # Don't raise — service stays up serving /health. Endpoints that
            # need the DB will fail naturally at engine.begin() until the next
            # successful pool connection (pool_pre_ping=True is recommended).
            print(f"[{service_name}] DB warm-up failed after retries: {exc}", flush=True)

    return asyncio.create_task(_warm_up())
