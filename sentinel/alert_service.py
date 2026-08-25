"""Independent external alert dispatcher for unattended Sentinel automation.

The trading worker only enqueues durable outbox rows.  This process owns delivery
and requires a real HTTPS webhook; local logging is deliberately not accepted as
successful unattended notification.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from urllib.parse import urlparse

import httpx

from sentinel.automation import outbox
from sentinel.automation_runtime import config_from_env
from sentinel.config import SentinelConfig
from sentinel.feed import store as feed_store


class WebhookAlertAdapter:
    def __init__(self, url: str, *, timeout_seconds: float = 10.0) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("alert webhook must be an HTTPS URL without userinfo")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("alert webhook timeout must be in (0,30]")
        self._url = url
        self._timeout = timeout_seconds

    def deliver(self, alert, idempotency_key: str) -> None:
        payload = {
            "schema": "sentinel.external-alert/1",
            "alert_id": alert.alert_id,
            "idempotency_key": idempotency_key,
            "event_type": alert.event_type,
            "severity": alert.severity,
            "payload": dict(alert.payload),
            "created_at": alert.created_at.isoformat(),
        }
        with httpx.Client(timeout=self._timeout, follow_redirects=False) as client:
            response = client.post(
                self._url,
                json=payload,
                headers={"Idempotency-Key": idempotency_key})
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(
                f"alert webhook returned HTTP {response.status_code}")


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
    while not stopped.is_set():
        conn = feed_store.connect(config.database_url)
        try:
            result = await outbox.dispatch_once(
                conn, adapter=adapter, holder_id=holder,
                claim_seconds=automation.alert_claim_seconds,
                retry_base_seconds=automation.retry_base_seconds,
                retry_max_seconds=automation.retry_max_seconds)
        finally:
            conn.close()
        if result.alert is None:
            try:
                await asyncio.wait_for(stopped.wait(), timeout=poll)
            except asyncio.TimeoutError:
                pass
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
