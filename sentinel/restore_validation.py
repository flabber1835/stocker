"""Read-only semantic validation for a promoted physical restore.

This module is executed from the exact digest-qualified Sentinel runtime image
against an isolated restored PostgreSQL container. It does not contact a broker
or market-data provider and it cannot mutate the restored database.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import quote

from sentinel import administrative_authority, authority, binding, schema, trial
from sentinel.automation import integrity as automation_integrity
from sentinel.automation import store as automation_store
from sentinel.core import catchup
from sentinel.execution import broker_cash, journal
from sentinel.feed import store as feed_store


class RestoreValidationRefused(RuntimeError):
    """The restored database cannot prove runtime-equivalent semantics."""


def _database_url() -> str:
    configured = os.environ.get("SENTINEL_DATABASE_URL", "").strip()
    if configured:
        return configured
    host = os.environ.get("SENTINEL_RESTORE_DATABASE_HOST", "").strip()
    password = os.environ.get(
        "SENTINEL_RESTORE_DATABASE_PASSWORD", "")
    if not host or not password:
        raise RestoreValidationRefused(
            "isolated restore database host/password are required")
    return (
        "postgresql://sentinel:"
        f"{quote(password, safe='')}@{host}:5432/sentinel")


def _force_session_read_only(conn) -> None:
    """Make every subsequent transaction read-only, including after rollback."""
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        row = cur.fetchone()
    if row is None or str(row[0]).lower() != "on":
        raise RestoreValidationRefused(
            "restored-database validator did not enter read-only mode")
    conn.rollback()


def _scalar(conn, statement: str) -> int:
    with conn.cursor() as cur:
        cur.execute(statement)
        row = cur.fetchone()
    if row is None:
        raise RestoreValidationRefused(
            "restored-database aggregate returned no row")
    return int(row[0])


def validate_restored_database(conn) -> dict:
    """Validate schemas and durable economic chains without writing a row."""
    _force_session_read_only(conn)
    schema.require_runtime_schema(conn)
    feed_store.require_feed_schema(conn)

    rollout = authority.load_rollout_state(conn)
    legacy_certificate = authority.load_active_certificate(conn)
    administrative = administrative_authority.administrative_authority_status(
        conn)
    account = binding.load(conn)
    control = automation_store.load_control(conn)
    latest = journal.latest_plan(conn)
    resumed = catchup.resume_state(conn)
    verifications = trial.load_verifications(conn)

    command_count = _scalar(conn, "SELECT COUNT(*) FROM sentinel_commands")
    if account is None and command_count:
        raise RestoreValidationRefused(
            "command journal exists without a durable account binding")
    commands = (
        journal.load_commands(conn, account.identity)
        if account is not None else ())
    if len(commands) != command_count:
        raise RestoreValidationRefused(
            "not every restored command could be reconstructed")

    terminal_checkpoint = None
    cash_activity = None
    if account is not None:
        terminal_checkpoint = journal.terminal_recovery_checkpoint(conn)
        cash_activity = broker_cash.load_activity_state(
            conn, broker=account.broker, account_id=account.broker_account_id)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT plan_id,decision_session,broker,broker_account_id"
            " FROM sentinel_execution_plans ORDER BY plan_id")
        plan_rows = cur.fetchall()
        cur.execute(
            "SELECT cursor_name FROM sentinel_processed_sessions"
            " WHERE cursor_name LIKE %s ORDER BY cursor_name",
            (f"{broker_cash.PLAN_BASELINE_PREFIX}%",))
        baseline_names = [str(row[0]) for row in cur.fetchall()]
    plan_by_id = {str(row[0]): row for row in plan_rows}
    baseline_ids = []
    for name in baseline_names:
        plan_id = name.removeprefix(broker_cash.PLAN_BASELINE_PREFIX)
        if not plan_id or plan_id not in plan_by_id:
            raise RestoreValidationRefused(
                f"cash baseline {name!r} has no execution plan")
        baseline_ids.append(plan_id)
    for plan_id in baseline_ids:
        baseline = broker_cash.load_plan_baseline(conn, plan_id=plan_id)
        if baseline is None:  # selected by the exact baseline namespace above
            raise RestoreValidationRefused(
                f"cash baseline for plan {plan_id!r} vanished during validation")
        row = plan_by_id[plan_id]
        if (baseline.decision_session != row[1]
                or baseline.broker != str(row[2])
                or baseline.account_id != str(row[3])):
            raise RestoreValidationRefused(
                f"cash baseline for plan {plan_id!r} disagrees with its plan")
    cash_baseline_count = len(baseline_ids)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT cycle_id FROM sentinel_automation_cycles"
            " ORDER BY decision_session,created_at,cycle_id")
        cycle_ids = [str(row[0]) for row in cur.fetchall()]
    for cycle_id in cycle_ids:
        cycle = automation_store.load_cycle(conn, cycle_id)
        automation_integrity.validate_cycle_lineage(conn, cycle)

    with conn.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        read_only = cur.fetchone()
    if read_only is None or str(read_only[0]).lower() != "on":
        raise RestoreValidationRefused(
            "semantic validation escaped its read-only database session")
    conn.rollback()

    return {
        "schema": "sentinel.restore-semantics/1",
        "transaction_read_only": True,
        "account_bound": account is not None,
        "takeover_epoch": account.takeover_epoch if account else None,
        "rollout_mode": rollout.mode.value,
        "rollout_version": rollout.version,
        "legacy_certificate_present": legacy_certificate is not None,
        "administrative_generation": administrative.get("generation", 0),
        "automation_enabled": control.enabled,
        "kill_switch_engaged": control.kill_switch_engaged,
        "control_generation": control.generation,
        "current_plan_id": latest.plan_id if latest else None,
        "plan_count": len(plan_rows),
        "restart_state_present": resumed is not None,
        "command_count": command_count,
        "terminal_checkpoint": (
            terminal_checkpoint.isoformat() if terminal_checkpoint else None),
        "cash_activity_state_present": cash_activity is not None,
        "cash_baseline_count": cash_baseline_count,
        "cycle_count": len(cycle_ids),
        "trial_verification_count": len(verifications),
    }


def main() -> int:
    conn = None
    try:
        conn = feed_store.connect(_database_url())
        result = validate_restored_database(conn)
    except Exception as exc:                                  # noqa: BLE001
        print(
            "RESTORE_SEMANTICS_REFUSED: "
            f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 4
    finally:
        if conn is not None:
            conn.close()
    print(
        "restored_database_semantics_ready:true "
        + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "RestoreValidationRefused", "main", "validate_restored_database",
]
