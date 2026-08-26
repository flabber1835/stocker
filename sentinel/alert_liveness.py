"""Docker health check for alert delivery, independent of the webhook path."""
from __future__ import annotations

import os
import sys

from sentinel import alert_health, schema
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store


def main() -> int:
    config = SentinelConfig.from_env()
    if not config.database_url:
        print("ALERT_DISPATCHER_UNHEALTHY: database URL is unset", file=sys.stderr)
        return 1
    dispatcher_id = os.environ.get(
        "SENTINEL_AUTOMATION_ALERT_DISPATCHER_ID", "primary").strip()
    try:
        maximum_age = float(os.environ.get(
            "SENTINEL_AUTOMATION_ALERT_HEALTH_MAX_AGE_SECONDS", "30"))
        startup_grace = float(os.environ.get(
            "SENTINEL_AUTOMATION_ALERT_STARTUP_GRACE_SECONDS", "330"))
    except ValueError as exc:
        print(f"ALERT_DISPATCHER_UNHEALTHY: {exc}", file=sys.stderr)
        return 1

    conn = None
    try:
        conn = feed_store.connect(config.database_url)
        schema.require_runtime_schema(conn)
        health = alert_health.require_healthy(
            conn, dispatcher_id=dispatcher_id,
            maximum_age_seconds=maximum_age,
            startup_grace_seconds=startup_grace)
    except Exception as exc:                                  # noqa: BLE001
        print(
            f"ALERT_DISPATCHER_UNHEALTHY: {type(exc).__name__}: {exc}",
            file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()
    print(
        "alert_dispatcher_healthy:true "
        f"dispatcher={health.dispatcher_id} state={health.state}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
