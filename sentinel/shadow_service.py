"""Dedicated broker-free unattended shadow observation service.

This module deliberately imports neither ProductionAutomation nor any Sentinel
execution/broker adapter.  Its environment contract rejects Alpaca authority,
and its only external mutation is the canonical Sharadar ingest/publication
path plus the append-only shadow observation tables.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import re
import signal
import sys
import time
from typing import Mapping, Optional, Sequence

from sentinel import schema, shadow_runtime
from sentinel.feed import calendar, ingest, readiness
from sentinel.feed import store as feed_store


PREFLIGHT_SCHEMA = "sentinel.shadow-service-preflight/1"
_OBSERVATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BROKER_AUTHORITY_ENV = (
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "SENTINEL_PAPER_ACCOUNT_ID")


class ShadowServiceRefused(RuntimeError):
    """The service cannot preserve an attributable shadow lineage."""


class ShadowServiceRetry(RuntimeError):
    """A vendor publication is not ready yet; retry without changing lineage."""


class ShadowServiceWaiting(RuntimeError):
    """No causally eligible first close exists yet; poll without writing."""


@dataclass(frozen=True)
class ShadowServiceConfig:
    database_url: str
    observation_id: str
    starting_cash: Decimal
    publication_timing_policy: str
    poll_seconds: int

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None
                 ) -> "ShadowServiceConfig":
        source = os.environ if env is None else env
        leaked = [name for name in _BROKER_AUTHORITY_ENV
                  if str(source.get(name) or "").strip()]
        if leaked:
            raise ShadowServiceRefused(
                "broker authority is forbidden in the shadow service environment")
        enabled = str(source.get(
            "SENTINEL_SHADOW_OBSERVATION_ENABLED", "0")).strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            raise ShadowServiceRefused(
                "reviewed shadow observation is not explicitly enabled")
        reviewed_hashes = (
            "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256",
            "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256",
            "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256",
            "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256",
        )
        for name in reviewed_hashes:
            if _SHA256.fullmatch(str(source.get(name, "")).strip()) is None:
                raise ShadowServiceRefused("%s is required" % name)
        reviewed_mode = str(source.get(
            "SENTINEL_REVIEWED_DEPLOYMENT_MODE", "")).strip().lower()
        if reviewed_mode not in {"shadow", "dual"}:
            raise ShadowServiceRefused(
                "SENTINEL_REVIEWED_DEPLOYMENT_MODE must authorize shadow or "
                "dual operation")
        database_url = str(source.get("SENTINEL_DATABASE_URL") or "").strip()
        if not database_url:
            raise ShadowServiceRefused("SENTINEL_DATABASE_URL is required")
        observation_id = str(source.get(
            "SENTINEL_SHADOW_OBSERVATION_ID", "primary")).strip()
        if _OBSERVATION_ID.fullmatch(observation_id) is None:
            raise ShadowServiceRefused("shadow observation id is malformed")
        try:
            starting_cash = Decimal(str(source.get(
                "SENTINEL_SHADOW_STARTING_CASH", "100000")).strip())
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ShadowServiceRefused(
                "shadow starting cash must be a positive decimal") from exc
        if not starting_cash.is_finite() or starting_cash <= 0:
            raise ShadowServiceRefused(
                "shadow starting cash must be a positive decimal")
        publication_timing_policy = str(source.get(
            "SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY",
            shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY)).strip()
        if (publication_timing_policy
                != shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY):
            raise ShadowServiceRefused(
                "shadow publication timing policy differs from review")
        try:
            poll_seconds = int(str(source.get(
                "SENTINEL_SHADOW_POLL_SECONDS", "300")).strip())
        except (TypeError, ValueError) as exc:
            raise ShadowServiceRefused(
                "SENTINEL_SHADOW_POLL_SECONDS must be an integer") from exc
        if poll_seconds < 5 or poll_seconds > 3600:
            raise ShadowServiceRefused(
                "SENTINEL_SHADOW_POLL_SECONDS must be in [5, 3600]")
        return cls(
            database_url, observation_id, starting_cash,
            publication_timing_policy, poll_seconds)


def _preflight(conn, config: ShadowServiceConfig, *,
               now: Optional[datetime] = None,
               allow_stale_frontier: bool = False) -> dict:
    """Classify only empty, attested, or exactly recoverable lineage state."""
    with conn.cursor() as cur:
        cur.execute("BEGIN TRANSACTION READ ONLY")
    schema.require_runtime_schema(conn)
    classified = shadow_runtime.classify_shadow_lineage(
        conn, observation_id=config.observation_id,
        starting_cash=config.starting_cash,
        clock=(None if now is None else lambda: now),
        structural_only=allow_stale_frontier)
    status = classified.get("status") if isinstance(classified, dict) else None
    if status == "NOT_STARTED" and set(classified) == {"status"}:
        return {
            "schema": PREFLIGHT_SCHEMA,
            "mode": "BROKER_FREE_SHADOW",
            "status": "NOT_STARTED",
            "broker_mutations_authorized": False,
        }
    if status == "RECOVERY_REQUIRED":
        required = {
            "status", "recovery_kind", "recovery_session", "execution_session",
            "recovery_cutoff_at",
        }
        if (set(classified) != required
                or classified.get("recovery_kind") not in {
                    "GENESIS_ONLY", "TRAILING_CANDIDATE"}
                or not isinstance(classified.get("recovery_session"), str)
                or not isinstance(classified.get("execution_session"), str)
                or not isinstance(classified.get("recovery_cutoff_at"), str)):
            raise ShadowServiceRefused(
                "recoverable shadow lineage classification is malformed")
        return {
            "schema": PREFLIGHT_SCHEMA,
            "mode": "BROKER_FREE_SHADOW",
            "status": "RECOVERY_REQUIRED",
            "broker_mutations_authorized": False,
            "recovery_kind": classified["recovery_kind"],
            "recovery_session": classified["recovery_session"],
            "execution_session": classified["execution_session"],
            "recovery_cutoff_at": classified["recovery_cutoff_at"],
        }
    if status == "ATTESTED_STRUCTURAL":
        if (set(classified) != {"status", "latest_session"}
                or not isinstance(classified.get("latest_session"), str)):
            raise ShadowServiceRefused(
                "structural shadow lineage classification is malformed")
        return {
            "schema": PREFLIGHT_SCHEMA,
            "mode": "BROKER_FREE_SHADOW",
            "status": "ATTESTED_STRUCTURAL",
            "broker_mutations_authorized": False,
            "latest_session": classified["latest_session"],
        }
    result = classified.get("result") if status == "VERIFIED" else None
    if set(classified) != {"status", "result"} or result is None:
        raise ShadowServiceRefused(
            "shadow lineage classification is not an allowed state")
    value = result.to_dict()
    if (value.get("shadow_verdict") != "SHADOW_GO"
            or value.get("verification") != "VERIFIED"):
        raise ShadowServiceRefused(
            "retained shadow lineage is not fully runtime-attested")
    return {
        "schema": PREFLIGHT_SCHEMA,
        "mode": "BROKER_FREE_SHADOW",
        "status": "VERIFIED",
        "broker_mutations_authorized": False,
        "lineage": value,
    }


def preflight(config: ShadowServiceConfig, *,
              now: Optional[datetime] = None,
              allow_stale_frontier: bool = False) -> dict:
    conn = feed_store.connect(config.database_url)
    try:
        result = _preflight(
            conn, config, now=now,
            allow_stale_frontier=allow_stale_frontier)
    finally:
        conn.rollback()
        conn.close()
    if result.get("status") == "NOT_STARTED":
        # A deploy/health preflight must not advertise a fresh lineage as
        # startable when its only source-final close is already retrospective.
        # No database or ingest is touched by this clock-only eligibility gate.
        _causal_target(preflight_status="NOT_STARTED", now=now)
    return result


def service_health(config: ShadowServiceConfig, *,
                   now: Optional[datetime] = None) -> dict:
    """Structural liveness without mislabeling an ordinary daily gap red."""
    retained = preflight(
        config, now=now, allow_stale_frontier=True)
    status = str(retained.get("status") or "")
    if status == "ATTESTED_STRUCTURAL":
        instant = now or datetime.now(timezone.utc)
        target = calendar.latest_closed_session(instant)
        latest = str(retained["latest_session"])
        if latest != target:
            if calendar.next_session(latest) != target:
                raise ShadowServiceRefused(
                    "shadow service health found more than one missing XNYS "
                    "session")
            execution = calendar.next_session(target)
            execution_open, _close = calendar.session_window(execution)
            if instant.astimezone(timezone.utc) >= execution_open.astimezone(
                    timezone.utc):
                raise ShadowServiceRefused(
                    "shadow service health found an uncommitted session past "
                    "its following-open cutoff")
        return {
            **retained,
            "service_health": "HEALTHY_WAITING" if latest != target
            else "HEALTHY_ATTESTED",
            "target_session": target,
        }
    return {**retained, "service_health": "HEALTHY"}


def _causal_target(*, preflight_status: str,
                   now: Optional[datetime] = None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ShadowServiceRefused("shadow service clock must be timezone-aware")
    target = calendar.latest_closed_session(instant)
    eligible = shadow_runtime.publication_not_before(target)
    if instant.astimezone(timezone.utc) < eligible:
        raise ShadowServiceWaiting(
            "shadow observation is waiting for the reviewed Sharadar "
            f"publication not-before {eligible.isoformat()}")
    if preflight_status == "NOT_STARTED":
        following = calendar.next_session(target)
        following_open, _following_close = calendar.session_window(following)
        if instant.astimezone(timezone.utc) >= following_open.astimezone(timezone.utc):
            raise ShadowServiceWaiting(
                "new shadow lineage is waiting for the next freshly completed close")
    return target


def advance_once(config: ShadowServiceConfig, *,
                 now: Optional[datetime] = None) -> dict:
    """Advance the current fully published close and append one verified row."""
    # Prove immutable lineage structure before allowing the corpus to move.
    # Full current-corpus status is deliberately postponed until after ingest:
    # at the source-final boundary an honest database is exactly one session
    # behind, so wall-clock readiness cannot pass yet. A trailing candidate,
    # config/source identity drift, or malformed authority still refuses here.
    retained = preflight(
        config, now=now, allow_stale_frontier=True)
    retained_status = str(retained.get("status") or "")
    target = (str(retained.get("recovery_session"))
              if retained_status == "RECOVERY_REQUIRED"
              else _causal_target(
                  preflight_status=retained_status, now=now))
    retained_lineage = retained.get("lineage")
    retained_session = (
        retained.get("latest_session")
        if retained_status == "ATTESTED_STRUCTURAL"
        else (retained_lineage or {}).get("session")
        if retained_status == "VERIFIED" else None)
    if retained_status in {"VERIFIED", "ATTESTED_STRUCTURAL"}:
        if retained_session == target:
            # Re-earn the complete current-corpus/revision/readiness status
            # before surfacing P/L. Structural evidence alone is never GO.
            verified = preflight(config, now=now)
            lineage = verified.get("lineage")
            if (verified.get("status") != "VERIFIED"
                    or not isinstance(lineage, dict)
                    or lineage.get("session") != target):
                raise ShadowServiceRefused(
                    "same-session shadow lineage did not re-earn VERIFIED")
            return lineage
        if (not isinstance(retained_session, str)
                or calendar.next_session(retained_session) != target):
            raise ShadowServiceRefused(
                "shadow lineage is not exactly one XNYS session behind the "
                "causal target")
        instant = now or datetime.now(timezone.utc)
        following = calendar.next_session(target)
        following_open, _following_close = calendar.session_window(following)
        if instant.astimezone(timezone.utc) >= following_open.astimezone(
                timezone.utc):
            raise ShadowServiceRefused(
                f"shadow lineage missed the following-open cutoff for {target}")
    conn = feed_store.connect(config.database_url)
    try:
        feed_store.require_feed_schema(conn)
        schema.require_runtime_schema(conn)
        if retained_status != "RECOVERY_REQUIRED":
            visible = feed_store.latest_visible_session(conn)
            if visible != target:
                try:
                    ingest.daily(conn, today=target)
                except Exception as exc:  # vendor/network failures are retryable
                    conn.rollback()
                    raise ShadowServiceRetry(
                        "Sharadar publication is not ready (%s)" %
                        type(exc).__name__) from exc
                visible = feed_store.latest_visible_session(conn)
            report = readiness.check_readiness(conn)
            if visible != target or not report.ready:
                failures = [str(item.name) for item in report.failures]
                raise ShadowServiceRetry(
                    "canonical data is not ready at exact frontier %s: %s" % (
                        target, ", ".join(failures[:10])))
        # Recovery deliberately bypasses ingest. The runtime holds the full
        # corpus pin and must reproduce the candidate from the unchanged exact
        # live frontier before it can append the missing authority.
        result = shadow_runtime.advance_ready_shadow(
            conn, through=target, observation_id=config.observation_id,
            starting_cash=config.starting_cash)
        value = result.to_dict()
        if (value.get("shadow_verdict") != "SHADOW_GO"
                or value.get("verification") != "VERIFIED"):
            raise ShadowServiceRefused(
                "shadow advance did not produce a verified strategy result")
        return value
    finally:
        conn.rollback()
        conn.close()


def run(config: ShadowServiceConfig) -> int:
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # Startup is an explicit lineage gate. Do not print a healthy service
    # banner before this has passed.
    print(json.dumps(service_health(config), sort_keys=True), flush=True)
    while not stopped:
        try:
            result = advance_once(config)
            print(json.dumps({
                "schema": "sentinel.shadow-service-result/1",
                "result": result,
            }, sort_keys=True), flush=True)
        except (ShadowServiceRefused,
                shadow_runtime.ShadowRuntimeRefused) as exc:
            print("REFUSED: %s" % exc, file=sys.stderr, flush=True)
            return 2
        except ShadowServiceRetry as exc:
            print("RETRY: %s" % exc, file=sys.stderr, flush=True)
        except ShadowServiceWaiting as exc:
            print("WAITING: %s" % exc, file=sys.stderr, flush=True)
        deadline = time.monotonic() + config.poll_seconds
        while not stopped and time.monotonic() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dedicated broker-free Sentinel shadow observer")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--service-health", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = ShadowServiceConfig.from_env()
        if args.preflight:
            print(json.dumps(preflight(config), sort_keys=True))
            return 0
        if args.service_health:
            print(json.dumps(service_health(config), sort_keys=True))
            return 0
        if args.once:
            print(json.dumps(advance_once(config), sort_keys=True))
            return 0
        return run(config)
    except (ShadowServiceRefused, ShadowServiceRetry, ShadowServiceWaiting,
            shadow_runtime.ShadowRuntimeRefused) as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
