"""Dedicated broker-free unattended shadow observation service.

This module deliberately imports neither ProductionAutomation nor any Sentinel
execution/broker adapter. Deployed shadow mode uses Alpaca credentials only
through the GET-only market-data client, requires an Alpaca/OpenFIGI rolling
publication, and rejects account identity and Sharadar credentials. The legacy
path remains for offline historical fixtures and cannot be entered by the
deployed shadow service.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
import signal
import sys
import time
from typing import Optional, Sequence

from sentinel import schema, shadow_runtime
from sentinel.feed import calendar, ingest, readiness, writer_schedule
from sentinel.feed import store as feed_store
from sentinel.shadow_service_config import (
    ShadowServiceConfig, ShadowServiceRefused, ShadowServiceRetry, ShadowServiceWaiting,
    _OBSERVATION_ID, _SHA256, _BROKER_AUTHORITY_ENV,
)


PREFLIGHT_SCHEMA = "sentinel.shadow-service-preflight/1"


def _preflight(conn, config: ShadowServiceConfig, *,
               now: Optional[datetime] = None,
               allow_stale_frontier: bool = False) -> dict:
    """Classify only empty, attested, or exactly recoverable lineage state."""
    with conn.cursor() as cur:
        cur.execute("BEGIN TRANSACTION READ ONLY")
    schema.require_runtime_schema(conn)
    if config.operational_source_only:
        from sentinel.feed import operational_snapshot, readers
        current = readers.current(conn)
        if not readers.is_rolling(current):
            raise ShadowServiceRefused(
                "operational shadow requires rolling Alpaca inputs")
        try:
            operational_snapshot.require_alpaca_openfigi(conn, current)
        except operational_snapshot.OperationalSnapshotRefused as exc:
            raise ShadowServiceRefused(str(exc)) from exc
    classified = shadow_runtime.classify_shadow_lineage(
        conn, observation_id=config.observation_id,
        starting_cash=config.starting_cash,
        clock=(None if now is None else lambda: now),
        structural_only=allow_stale_frontier)
    contract = {}
    if isinstance(classified, dict) and "input_contract" in classified:
        from sentinel.rolling_runtime import SCHEMA
        if classified["input_contract"] != SCHEMA:
            raise ShadowServiceRefused("unknown shadow runtime input contract")
        classified = dict(classified)
        contract["input_contract"] = classified.pop("input_contract")
    status = classified.get("status") if isinstance(classified, dict) else None
    if status in {"RECONSTRUCTION_REQUIRED", "RECONSTRUCTED_STRUCTURAL"} and contract:
        if set(classified) != {"status", "latest_session"} or not isinstance(classified["latest_session"], str):
            raise ShadowServiceRefused("reconstruction classification is malformed")
        return {**contract, **classified, "schema": PREFLIGHT_SCHEMA,
                "mode": "BROKER_FREE_SHADOW", "broker_mutations_authorized": False}
    if status == "NOT_STARTED" and set(classified) == {"status"}:
        return {
            **contract,
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
            **contract,
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
            **contract,
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
        **contract,
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
        _causal_target(preflight_status="NOT_STARTED", now=now,
                       allow_state_preparation=config.operational_source_only)
    return result


def service_health(config: ShadowServiceConfig, *,
                   now: Optional[datetime] = None) -> dict:
    """Structural liveness without mislabeling an ordinary daily gap red."""
    retained = preflight(
        config, now=now, allow_stale_frontier=True)
    if config.operational_source_only:
        from sentinel.rolling_runtime import SCHEMA
        if retained.get("input_contract") != SCHEMA:
            raise ShadowServiceRefused(
                "operational shadow requires rolling Alpaca inputs")
    status = str(retained.get("status") or "")
    if "input_contract" in retained and status in {
            "ATTESTED_STRUCTURAL", "RECONSTRUCTION_REQUIRED", "RECONSTRUCTED_STRUCTURAL"}:
        instant = now or datetime.now(timezone.utc)
        target = calendar.latest_closed_session(instant)
        following = calendar.next_session(retained["latest_session"])
        opened, _ = calendar.session_window(calendar.next_session(following))
        return {**retained, "service_health": "RECONSTRUCTION_PENDING" if
                status != "ATTESTED_STRUCTURAL" or following < target
                or following <= target and instant >= opened
                else "HEALTHY_ATTESTED" if retained["latest_session"] == target else "HEALTHY_WAITING",
                "target_session": target}
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
                   now: Optional[datetime] = None,
                   allow_state_preparation: bool = False) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ShadowServiceRefused("shadow service clock must be timezone-aware")
    target = calendar.latest_closed_session(instant)
    eligible = shadow_runtime.publication_not_before(target)
    if instant.astimezone(timezone.utc) < eligible:
        raise ShadowServiceWaiting(
            "shadow observation is waiting for the reviewed daily "
            f"publication not-before {eligible.isoformat()}")
    if preflight_status == "NOT_STARTED" and not allow_state_preparation:
        following = calendar.next_session(target)
        following_open, _following_close = calendar.session_window(following)
        if instant.astimezone(timezone.utc) >= following_open.astimezone(timezone.utc):
            raise ShadowServiceWaiting(
                "new shadow lineage is waiting for the next freshly completed close")
    return target


def advance_once(config: ShadowServiceConfig, *,
                 now: Optional[datetime] = None) -> dict:
    """Advance the current fully published close and append one verified row."""
    from sentinel import shadow_budget
    acquisition_deadline = shadow_budget.cutoff()
    # Prove immutable lineage structure before allowing the corpus to move.
    # Full current-corpus status is deliberately postponed until after ingest:
    # at the source-final boundary an honest database is exactly one session
    # behind, so wall-clock readiness cannot pass yet. A trailing candidate,
    # config/source identity drift, or malformed authority still refuses here.
    retained = preflight(
        config, now=now, allow_stale_frontier=True)
    if config.operational_source_only:
        from sentinel.rolling_runtime import SCHEMA
        if retained.get("input_contract") != SCHEMA:
            raise ShadowServiceRefused(
                "operational shadow requires rolling Alpaca inputs")
    retained_status = str(retained.get("status") or "")
    target = (str(retained.get("recovery_session"))
              if retained_status == "RECOVERY_REQUIRED"
              else _causal_target(
                  preflight_status=retained_status, now=now,
                  allow_state_preparation=config.operational_source_only))
    if "input_contract" in retained:
        from sentinel import rolling_runtime
        if retained["input_contract"] != rolling_runtime.SCHEMA:
            raise ShadowServiceRefused("unknown shadow runtime input contract")
        conn = feed_store.connect(config.database_url)
        discard_connection = False
        try:
            return rolling_runtime.service_advance(conn, through=target,
                observation_id=config.observation_id, starting_cash=config.starting_cash,
                acquisition_deadline=acquisition_deadline).to_dict()
        except BaseException as exc:
            discard_connection = writer_schedule.connection_discarded(exc)
            if discard_connection or not isinstance(exc, Exception):
                raise
            from sentinel.rolling_reconstruction_evidence import InputsUnavailable
            from sentinel.feed.rolling_jobs import JobDeadlineExceeded
            from sentinel.feed.source_wait import SourceCoveragePending
            from sentinel.feed.rolling_go_inputs import RollingSourceFrontierPending
            if isinstance(exc, RollingSourceFrontierPending):
                raise ShadowServiceWaiting(str(exc)) from exc
            if isinstance(exc, SourceCoveragePending):
                raise ShadowServiceWaiting(str(exc)) from exc
            if isinstance(exc, InputsUnavailable):
                raise ShadowServiceWaiting(str(exc)) from exc
            if isinstance(exc, JobDeadlineExceeded):
                raise ShadowServiceRetry("rolling shadow acquisition deadline exhausted") from exc
            from sentinel.shadow_worker import _availability_failure
            if _availability_failure(exc):
                raise ShadowServiceRetry("rolling shadow source/backup unavailable") from exc
            raise ShadowServiceRefused("rolling shadow service refused: " + str(exc)) from exc
        finally:
            if not discard_connection:
                conn.rollback()
                conn.close()
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
                        "legacy publication is not ready (%s)" %
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
        maintenance_pending = True
        while not stopped and time.monotonic() < deadline:
            if maintenance_pending:
                from sentinel.feed import retention
                maintenance_pending = retention.idle_pass(config.database_url)
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dedicated broker-free Sentinel shadow observer")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--operational-inputs", action="store_true",
                        help="Validate operational inputs in a read-only preflight")
    parser.add_argument("--service-health", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.operational_inputs and (
            not args.preflight or args.service_health or args.once):
        parser.error("--operational-inputs requires only --preflight")
    try:
        config = ShadowServiceConfig.from_env()
        if args.preflight:
            if args.operational_inputs:
                # The installer has no provider credentials and cannot ingest.
                # Read-only input/lineage checks still use operational timing.
                config = replace(config, operational_source_only=True)
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
