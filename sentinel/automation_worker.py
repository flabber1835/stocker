"""One supervised automation worker with an explicit durable holder id."""
from __future__ import annotations

import asyncio
import os
import signal
import sys

from sentinel import schema
from sentinel.automation_runtime import ProductionAutomation, config_from_env
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store


async def _run() -> int:
    config = SentinelConfig.from_env()
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 2
    holder_id = os.environ.get("SENTINEL_AUTOMATION_HOLDER_ID", "").strip()
    if not holder_id:
        print("REFUSED: SENTINEL_AUTOMATION_HOLDER_ID is unset", file=sys.stderr)
        return 2
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
    runtime = ProductionAutomation(
        sentinel_config=config, automation_config=config_from_env(),
        holder_id=holder_id)
    await runtime.run(stop=stop)
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
