"""Database startup utilities."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def wait_for_db(engine, retries: int = 10, delay: float = 3.0) -> None:
    """
    Retry a lightweight DB ping until Postgres is ready to accept connections.

    pg_isready can return healthy before Postgres finishes initialising its
    data directory (especially on first boot on slow NAS hardware). This
    retry loop bridges that gap so services don't crash on startup.
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
                "DB not ready (attempt %d/%d): %s — retrying in %.0fs",
                attempt, retries, exc, delay,
            )
            await asyncio.sleep(delay)
