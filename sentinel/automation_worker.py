"""One supervised automation worker with an explicit durable holder id.

A secondary worker stays hot in STANDBY while another holder owns the live
PostgreSQL lease. It never attempts to steal a live lease; once that lease is no
longer live it enters the canonical automation loop and competes through the
existing fenced acquire operation.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sentinel import schema
from sentinel.automation import store as automation_store
from sentinel.automation_recovery import ProductionAutomation, config_from_env
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store


async def _wait_until_lease_is_acquirable(
        *, database_url: str, holder_id: str, heartbeat_seconds: int,
        stop: asyncio.Event) -> None:
    """Remain an observable passive worker while another live leader exists."""
    while not stop.is_set():
        conn = feed_store.connect(database_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT l.holder_id,l.control_generation,l.expires_at,"
                    " c.generation,c.enabled,c.kill_switch_engaged,"
                    " clock_timestamp() FROM sentinel_automation_lease l "
                    "JOIN sentinel_automation_control c ON c.id=1 WHERE l.id=1")
                row = cur.fetchone()
            conn.rollback()
            if row is None:
                return
            (leader, lease_generation, expires_at, control_generation,
             enabled, killed, database_now) = row
            other_live = bool(
                enabled and not killed and leader is not None
                and leader != holder_id
                and lease_generation == control_generation
                and expires_at is not None and expires_at > database_now)
            if not other_live:
                return
            wake = database_now + timedelta(seconds=heartbeat_seconds)
            automation_store.register_instance(
                conn, instance_id=holder_id, state="STANDBY",
                next_wake_at=wake,
                last_error=f"live leader is {leader}")
        finally:
            conn.close()
        try:
            await asyncio.wait_for(stop.wait(), timeout=heartbeat_seconds)
        except asyncio.TimeoutError:
            pass


async def _run() -> int:
    config = SentinelConfig.from_env()
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 2
    holder_id = os.environ.get("SENTINEL_AUTOMATION_HOLDER_ID", "").strip()
    if not holder_id:
        print("REFUSED: SENTINEL_AUTOMATION_HOLDER_ID is unset", file=sys.stderr)
        return 2
    automation_config = config_from_env()
    conn = feed_store.connect(config.database_url)
    try:
        schema.require_runtime_schema(conn)
    finally:
        conn.close()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, signame, None)
        if signum is not None:
            try:
                loop.add_signal_handler(signum, stop.set)
            except (NotImplementedError, RuntimeError):
                pass

    await _wait_until_lease_is_acquirable(
        database_url=config.database_url, holder_id=holder_id,
        heartbeat_seconds=automation_config.heartbeat_seconds, stop=stop)
    if stop.is_set():
        return 0

    runtime = ProductionAutomation(
        sentinel_config=config, automation_config=automation_config,
        holder_id=holder_id)
    # Unattended production never consumes its own alert outbox.  Alert
    # delivery is a separate broker-free process so a stalled/killed trading
    # worker cannot both fail and mark its notification DELIVERED.
    await runtime.service.run(
        runtime.connect, stop=stop,
        clock=lambda: datetime.now(ZoneInfo("UTC")),
        sleep=asyncio.sleep, alert_wake=None,
        control_wake=runtime.control_wake)
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
