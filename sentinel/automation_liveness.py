"""Strict per-worker liveness probe for unattended automation containers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

if __name__ == "__main__" and len(sys.argv) == 1:  # Docker's existing command
    from sentinel.automation_health_probe import probe

    raise SystemExit(probe())

from sentinel.automation.health import read_health
from sentinel.automation.env_config import config_from_env
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store

HOLDER_FILE = Path("/tmp/sentinel-automation-holder-id")


def observe(database_url, lease_seconds, *, connect=None) -> tuple[int, dict]:
    """Use one canonical health check and the freshly named supervised worker."""
    try:
        if not database_url:
            raise RuntimeError("SENTINEL_DATABASE_URL is unset")
        connect = feed_store.connect if connect is None else connect
        conn = connect(database_url)
        try:
            health = read_health(conn)
            if not health.enabled or health.kill_switch_engaged:
                return (0 if health.healthy else 1), health.model_dump(mode="json")
            holder_id = HOLDER_FILE.read_text(encoding="utf-8").strip()
            if not holder_id:
                raise RuntimeError("supervised automation holder id is absent")
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT heartbeat_at,clock_timestamp() FROM "
                    "sentinel_automation_service_instances WHERE instance_id=%s",
                    (holder_id,))
                row = cur.fetchone()
            conn.rollback()
            if HOLDER_FILE.read_text(encoding="utf-8").strip() != holder_id:
                raise RuntimeError("supervised automation holder changed")
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - health must fail closed
        return 1, {"healthy": False, "reason": str(exc)}

    if row is None or row[0] is None:
        return 1, {
            "healthy": False, "holder_id": holder_id,
            "reason": "supervised worker has no durable heartbeat",
        }
    heartbeat_age = (row[1] - row[0]).total_seconds()
    own_fresh = 0 <= heartbeat_age <= lease_seconds
    leader_overdue = bool(
        health.leader_holder == holder_id and health.scheduler_overdue)
    payload = {
        **health.model_dump(mode="json"),
        "supervised_holder_id": holder_id,
        "supervised_heartbeat_age_seconds": heartbeat_age,
        "supervised_heartbeat_fresh": own_fresh,
    }
    return (0 if health.operational_ready and own_fresh and not leader_overdue else 1), payload


def main() -> int:
    try:
        config = SentinelConfig.from_env()
        automation_config = config_from_env()
        status, payload = observe(config.database_url, automation_config.lease_seconds)
    except Exception as exc:  # noqa: BLE001 - health must fail closed
        status, payload = 1, {"healthy": False, "reason": str(exc)}
    print(json.dumps(payload, default=str, sort_keys=True))
    return status


if __name__ == "__main__":  # pragma: no cover
    if sys.argv[1:] != ["--direct"]:
        raise SystemExit("expected --direct or the supervisor's health probe")
    raise SystemExit(main())
