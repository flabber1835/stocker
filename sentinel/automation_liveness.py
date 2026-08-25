"""Strict liveness probe for the unattended automation container.

Unlike ``sentinel automation-health`` this command is a supervisor contract:
when automation is enabled, scheduler progress is mandatory. Disabled/killed
states remain healthy because they are deliberate fail-closed policy states.
"""
from __future__ import annotations

import json
import sys

from sentinel.automation.health import read_health
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store


def main() -> int:
    try:
        config = SentinelConfig.from_env()
        if not config.database_url:
            raise RuntimeError("SENTINEL_DATABASE_URL is unset")
        conn = feed_store.connect(config.database_url)
        try:
            health = read_health(conn)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - health must fail closed
        print(json.dumps({"healthy": False, "reason": str(exc)}))
        return 1

    payload = health.model_dump(mode="json")
    print(json.dumps(payload, default=str, sort_keys=True))
    if not health.healthy:
        return 1
    if health.enabled and not health.kill_switch_engaged:
        return 0 if health.operational_ready else 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
