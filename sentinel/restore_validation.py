"""Read-only semantic validation for a promoted physical restore.

This module is executed from the exact digest-qualified Sentinel runtime image
against an isolated restored PostgreSQL container. It does not contact a broker
or market-data provider and it cannot mutate the restored database.
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import quote
from itertools import batched

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


def _rolling_closure(conn):
    from sentinel import rolling_checkpoint, rolling_daily_checkpoint
    from sentinel import rolling_initialization, rolling_runtime
    from sentinel.feed import rolling_go_inputs, operational_snapshot, rolling_store
    from sentinel.feed import action_history, publication

    pub = rolling_go_inputs.current(conn)
    initial = rolling_checkpoint.read(conn)
    daily = rolling_daily_checkpoint.read(conn)
    if not rolling_go_inputs.is_rolling(pub):
        if initial is not None or daily is not None:
            raise RestoreValidationRefused("rolling checkpoint without rolling publication")
        return None
    publication._validate_publication(conn, pub, allow_snapshot=True)
    if publication.chain_gaps(conn):
        raise RestoreValidationRefused("rolling publication chain gap")
    snapshot = operational_snapshot._bound(conn, pub)
    rolling_store.verify_content(conn, snapshot['candidate_id'])
    row = conn.execute(
        "SELECT basis,through FROM sentinel_action_coverage WHERE publication_version=%s",
        (pub.version,)).fetchone()
    action_history.verify_coverage_chain(conn, version=pub.version)
    if row is not None:
        action_history.records(conn, version=pub.version, start=row[0], end=row[1])
    if initial is None:
        if daily is not None:
            raise RestoreValidationRefused("daily checkpoint without rolling origin")
        if rolling_checkpoint.lineage_names(conn):
            raise RestoreValidationRefused("strategy lineage without rolling origin")
        return {"state_present": False, "publication_version": pub.version}
    context = rolling_initialization._context(initial.observation_id, initial.starting_cash)
    checkpoint, _, _, attested, _ = rolling_runtime._closure(conn, context)
    from sentinel.rolling_authority import ReconstructionReceipt
    result = {"state_present": True, "publication_version": pub.version,
              "session": checkpoint.session,
              "attested": attested is not None and not isinstance(attested, ReconstructionReceipt)}
    if isinstance(attested, ReconstructionReceipt):
        result["reconstructed"] = True
    return result


def _verify_posted_fill_cash(conn) -> None:
    from sentinel.execution.contract import Side
    from sentinel.execution.fill_integrity import _posted_cash

    with conn.cursor() as cur:
        cur.execute(
            "SELECT s.cursor_name,s.state,f.fill_key,f.client_key,f.broker_order_id,"
            " f.quantity,f.price,c.side FROM sentinel_processed_sessions s"
            " LEFT JOIN sentinel_fills f ON f.broker_order_id=s.state->>'order_id'"
            " AND f.fill_key=right(s.cursor_name,64)"
            " LEFT JOIN sentinel_commands c ON c.client_key=f.client_key"
            " AND c.broker_order_id=f.broker_order_id"
            " WHERE s.cursor_name LIKE ANY(%s) ORDER BY s.cursor_name",
            ([prefix + "%" for prefix in journal.FILL_CASH_PREFIXES],))
        seen = set()
        for name, state, key, client_key, order_id, quantity, price, side in cur.fetchall():
            if (key is None or re.fullmatch(r"[0-9a-f]{64}", key) is None
                    or name not in {prefix + key for prefix in journal.FILL_CASH_PREFIXES}
                    or key in seen or side is None or not client_key
                    or not quantity.is_finite() or quantity <= 0
                    or not price.is_finite() or price <= 0):
                raise RestoreValidationRefused(
                    "posted fill cash has an orphan, duplicate, or invalid native fill binding")
            try:
                _posted_cash(state, order_id=order_id, client_key=client_key,
                             side=Side(side), qty=quantity, price=price)
            except ValueError as exc:
                raise RestoreValidationRefused(f"posted fill cash is invalid: {exc}") from exc
            seen.add(key)


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
    rolling = _rolling_closure(conn)
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
    _verify_posted_fill_cash(conn)

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
    from sentinel.paper.cash_retirement import PREFIX as cash_retirement_prefix, verify_retirements
    baselines = []
    for name in baseline_names:
        if name.startswith(cash_retirement_prefix):
            # A distinct authenticated subtype of existing execution metadata.
            # Its paired receipts are strictly validated below, not parsed as a
            # baseline or silently omitted from restored-state validation.
            continue
        plan_id = name.removeprefix(broker_cash.PLAN_BASELINE_PREFIX)
        if not plan_id or plan_id not in plan_by_id:
            raise RestoreValidationRefused(
                f"cash baseline {name!r} has no execution plan")
        baselines.append((name, plan_id))
    for batch in batched(baselines, 32):
        with conn.cursor() as cur:
            cur.execute("SELECT cursor_name,session,state FROM sentinel_processed_sessions"
                        " WHERE cursor_name=ANY(%s)", ([name for name, _ in batch],))
            rows = {str(name): (session, state) for name, session, state in cur.fetchall()}
        for name, plan_id in batch:
            if name not in rows:
                raise RestoreValidationRefused(
                    f"cash baseline for plan {plan_id!r} vanished during validation")
            baseline = broker_cash.decode_plan_baseline(plan_id, rows[name])
            row = plan_by_id[plan_id]
            if (baseline.decision_session != row[1]
                    or baseline.broker != str(row[2])
                    or baseline.account_id != str(row[3])):
                raise RestoreValidationRefused(
                    f"cash baseline for plan {plan_id!r} disagrees with its plan")
    cash_baseline_count = len(baselines)
    from sentinel.paper.model import PaperActivationRefused
    try:
        verify_retirements(conn)
        from sentinel.paper.policy_replacement import verify_receipts
        verify_receipts(conn)
    except PaperActivationRefused as exc:
        raise RestoreValidationRefused(str(exc)) from exc

    with conn.cursor() as cur:
        cur.execute(
            "SELECT cycle_id FROM sentinel_automation_cycles"
            " ORDER BY decision_session,created_at,cycle_id")
        cycle_ids = [str(row[0]) for row in cur.fetchall()]
    validated = {}
    for batch in batched(cycle_ids, 64):
        cycles = automation_store.load_cycle_batch(conn, list(batch))
        automation_integrity.verify_restored_cycle_batch(conn, cycles, validated)

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
        "restart_state_present": resumed is not None or bool(rolling and rolling['state_present']),
        "rolling": rolling,
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
