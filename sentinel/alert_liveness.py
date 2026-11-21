"""Docker health check for alert delivery, independent of the webhook path."""
from __future__ import annotations

import os
import sys

if __name__ == '__main__' and len(sys.argv) == 1:
    from sentinel.supervisor_health import probe

    raise SystemExit(probe('/tmp/sentinel-alert-health.sock'))

from sentinel import alert_health, schema
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store


def observe() -> tuple[int, dict]:
    config = SentinelConfig.from_env()
    if not config.database_url:
        return 1, {'healthy': False, 'reason': 'database URL is unset'}
    dispatcher_id = os.environ.get(
        "SENTINEL_AUTOMATION_ALERT_DISPATCHER_ID", "primary").strip()
    try:
        maximum_age = float(os.environ.get(
            "SENTINEL_AUTOMATION_ALERT_HEALTH_MAX_AGE_SECONDS", "30"))
        startup_grace = float(os.environ.get(
            "SENTINEL_AUTOMATION_ALERT_STARTUP_GRACE_SECONDS", "330"))
        alert_health.validate_health_intervals(
            maximum_age_seconds=maximum_age,
            startup_grace_seconds=startup_grace)
    except ValueError as exc:
        return 1, {'healthy': False, 'reason': str(exc)}

    conn = None
    try:
        conn = feed_store.connect(config.database_url, connect_timeout=2, statement_timeout_ms=2000)
        conn.read_only = True
        schema.require_runtime_schema(conn)
        health = alert_health.require_healthy(
            conn, dispatcher_id=dispatcher_id,
            maximum_age_seconds=maximum_age,
            startup_grace_seconds=startup_grace)
    except Exception as exc:                                  # noqa: BLE001
        return 1, {'healthy': False, 'reason': f'{type(exc).__name__}: {exc}'}
    finally:
        if conn is not None:
            conn.close()
    return 0, {'healthy': True, 'dispatcher': health.dispatcher_id, 'state': health.state}


def main() -> int:
    status, payload = observe()
    if status:
        print('ALERT_DISPATCHER_UNHEALTHY: '+payload['reason'], file=sys.stderr)
    else:
        print('alert_dispatcher_healthy:true '
              f"dispatcher={payload['dispatcher']} state={payload['state']}")
    return status


if __name__ == "__main__":  # pragma: no cover
    if sys.argv[1:] != ['--direct']:
        raise SystemExit('expected --direct or the supervised health probe')
    raise SystemExit(main())
