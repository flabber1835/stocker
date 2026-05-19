"""Database startup utilities."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


def create_db_engine(database_url: str, pool_size: int = 5, max_overflow: int = 10):
    """
    Create an async SQLAlchemy engine with ssl disabled.

    asyncpg defaults to trying SSL first. On some Docker/NAS network stacks
    the SSL probe hangs rather than being quickly refused, causing TimeoutError
    on every connection attempt. Disabling SSL avoids this entirely — the
    postgres container doesn't use SSL anyway.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        connect_args={"ssl": False},
    )


async def wait_for_db(engine, retries: int = 20, delay: float = 3.0) -> None:
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
                "DB not ready (attempt %d/%d): %r — retrying in %.0fs",
                attempt, retries, exc, delay,
            )
            await asyncio.sleep(delay)
