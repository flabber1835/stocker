"""Independent external alert dispatcher for unattended Sentinel automation.

The trading worker only enqueues durable outbox rows. This process owns delivery
and requires a real HTTPS webhook; local logging is deliberately not accepted as
successful unattended notification. Database loss and scheduler silence are
reported directly because the failed component cannot be trusted to enqueue its
own incident.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from urllib.parse import urlparse

import httpx

from sentinel.automation import outbox
from sentinel.automation.health import read_health
from sentinel.automation_runtime import config_from_env
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store


class WebhookAlertAdapter:
    def __init__(self, url: str, *, timeout_seconds: float = 10.0) -> None:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password):
            raise ValueError("alert webhook must be an HTTPS URL without userinfo")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("alert webhook timeout must be in (0,30]")
        self._url = url
        self._timeout = timeout_seconds

    def _post(self, payload: dict, idempotency_key: str) -> None:
        with httpx.Client(timeout=self._timeout, follow_redirects=False) as client:
            response = client.post(
                self._url, json=payload,
                headers={"Idempotency-Key": idempotency_key})
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(
                f"alert webhook returned HTTP {response.status_code}")

    def deliver(self, alert, idempotency_key: str) -> None:
        self._post({
            "schema": "sentinel.external-alert/1",
            "alert_id": alert.alert_id,
            "idempotency_key": idempotency_key,
            "event_type": alert.event_type,
            "severity": alert.severity,
            "payload": dict(alert.payload),
            "created_at": alert.created_at.isoformat(),
        }, idempotency_key)

    def deliver_database_failure(self, detail: str, bucket: int) -> None:
        key = f"sentinel:alert-dispatcher:database-unreachable:{bucket}"
        self._post({
            "schema": "sentinel.external-alert/1",
            "idempotency_key": key,
            "event_type": "ALERT_DISPATCHER_DATABASE_UNREACHABLE",
            "severity": "CRITICAL",
            "payload": {"detail": detail[:1000]},
        }, key)

    def deliver_health_failure(self, policy_state: str, detail: dict,
                               bucket: int) -> None:
        key = f"sentinel:automation-health:{policy_state}:{bucket}"
        self._post({
            "schema": "sentinel.external-alert/1",
            "idempotency_key": key,
            "event_type": "AUTOMATION_EXTERNAL_HEALTH_FAILURE",
            "severity": "CRITICAL",
            "payload": {"policy_state": policy_state, **detail},
        }, key)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def run() -> int:
    config = SentinelConfig.from_env()
    if not config.database_url:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 2
    url = os.environ.get("SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL", "").strip()
    if not url:
        print("REFUSED: SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL is required",
              file=sys.stderr)
        return 2
    timeout = float(os.environ.get(
        "SENTINEL_AUTOMATION_ALERT_WEBHOOK_TIMEOUT_SECONDS", "10"))
    adapter = WebhookAlertAdapter(url, timeout_seconds=timeout)
    automation = config_from_env()
    poll = float(os.environ.get("SENTINEL_AUTOMATION_ALERT_POLL_SECONDS", "2"))
    if poll <= 0 or poll > 60:
        print("REFUSED: SENTINEL_AUTOMATION_ALERT_POLL_SECONDS must be in (0,60]",
              file=sys.stderr)
        return 2

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, signame, None)
        if signum is not None:
            try:
                loop.add_signal_handler(signum, stopped.set)
            except (NotImplementedError, RuntimeError):
                pass

    holder = f"alert-dispatcher-{os.getpid()}"
    last_database_bucket: int | None = None
    last_health_key: tuple[str, int] | None = None
    externally_critical = {
        "SCHEDULER_STALLED", "SCHEDULER_OVERDUE", "WAITING_FOR_LEADER",
        "AUTHORITY_FAILED", "AUTHORITY_INVALID", "BLOCKED",
        "KILLED_BROKER_OUTCOME_UNRESOLVED",
        "DISABLED_BROKER_OUTCOME_UNRESOLVED",
    }
    while not stopped.is_set():
        conn = None
        try:
            conn = feed_store.connect(config.database_url)
            health = read_health(conn)
            active_incident = bool(
                health.policy_state in externally_critical
                and ((health.enabled and not health.kill_switch_engaged)
                     or health.policy_state in {
                         "KILLED_BROKER_OUTCOME_UNRESOLVED",
                         "DISABLED_BROKER_OUTCOME_UNRESOLVED",
                     }))
            if active_incident:
                bucket = int(time.time() // 60)
                health_key = (health.policy_state, bucket)
                if health_key != last_health_key:
                    adapter.deliver_health_failure(
                        health.policy_state,
                        {
                            "control_generation": health.control_generation,
                            "leader_holder": health.leader_holder,
                            "latest_cycle_id": health.latest_cycle_id,
                            "latest_cycle_state": health.latest_cycle_state,
                            "broker_outcome_unresolved":
                                health.broker_outcome_unresolved,
                        },
                        bucket)
                    last_health_key = health_key
            result = await outbox.dispatch_once(
                conn, adapter=adapter, holder_id=holder,
                claim_seconds=automation.alert_claim_seconds,
                retry_base_seconds=automation.retry_base_seconds,
                retry_max_seconds=automation.retry_max_seconds)
            last_database_bucket = None
        except Exception as exc:  # noqa: BLE001
            # The database cannot durably record its own disappearance. Emit a
            # direct external critical signal, rate-limited to one per minute.
            bucket = int(time.time() // 60)
            if bucket != last_database_bucket:
                try:
                    adapter.deliver_database_failure(
                        f"{type(exc).__name__}: {exc}", bucket)
                    last_database_bucket = bucket
                except Exception as alert_exc:  # noqa: BLE001
                    print(
                        "alert dispatcher could not report database failure: "
                        f"{type(alert_exc).__name__}: {alert_exc}",
                        file=sys.stderr, flush=True)
            await _sleep_or_stop(stopped, poll)
            continue
        finally:
            if conn is not None:
                conn.close()
        if result.alert is None:
            await _sleep_or_stop(stopped, poll)
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
