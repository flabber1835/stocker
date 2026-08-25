"""Strict per-worker liveness probe for unattended automation containers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sentinel.automation.health import read_health
from sentinel.automation_runtime import config_from_env
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store

HOLDER_FILE = Path("/tmp/sentinel-automation-holder-id")


def main() -> int:
    try:
        config = SentinelConfig.from_env()
        automation_config = config_from_env()
        if not config.database_url:
            raise RuntimeError("SENTINEL_DATABASE_URL is unset")
        conn = feed_store.connect(config.database_url)
        try:
            health = read_health(conn)
            if not health.enabled or health.kill_switch_engaged:
                payload = health.model_dump(mode="json")
                print(json.dumps(payload, default=str, sort_keys=True))
                return 0 if health.healthy else 1
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
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - health must fail closed
        print(json.dumps({"healthy": False, "reason": str(exc)}))
        return 1

    if row is None or row[0] is None:
        print(json.dumps({
            "healthy": False, "holder_id": holder_id,
            "reason": "supervised worker has no durable heartbeat",
        }, sort_keys=True))
        return 1
    heartbeat_age = (row[1] - row[0]).total_seconds()
    own_fresh = 0 <= heartbeat_age <= automation_config.lease_seconds
    leader_overdue = bool(
        health.leader_holder == holder_id and health.scheduler_overdue)
    payload = {
        **health.model_dump(mode="json"),
        "supervised_holder_id": holder_id,
        "supervised_heartbeat_age_seconds": heartbeat_age,
        "supervised_heartbeat_fresh": own_fresh,
    }
    print(json.dumps(payload, default=str, sort_keys=True))
    return 0 if health.healthy and own_fresh and not leader_overdue else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
