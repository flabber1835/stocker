"""Accounting and recovery-integrity corrections for the Alpaca hardening.

Kept separate from the transport overlay so these invariants are small and
reviewable: trade cash is never counted twice, recovery witnesses remain stable
as commands later progress, and an existing backup-capable database cannot
silently create its first physical-incarnation anchor after an unacknowledged
restore.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

_INSTALLED = False
_WITNESS_PREFIX = "terminal-recovery-witness:v3:"
_PROVENANCE_PREFIX = "broker-observation:v2:"
_DB_CURSOR = "broker-recovery-db-incarnation:v1"


def _json(raw, *, where: str) -> dict:
    if isinstance(raw, dict):
        value = raw
    else:
        try:
            value = json.loads(str(raw))
        except Exception as exc:
            raise RuntimeError(f"{where} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{where} must be a JSON object")
    return value


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from sentinel.execution import alpaca, broker_cash, journal
    from sentinel.execution.identity import is_sentinel_key
    from sentinel.execution.states import CommandState, TERMINAL
    from sentinel.execution import alpaca_remediation_final as final

    if getattr(alpaca, "_ACCOUNTING_INTEGRITY_INSTALLED", False):
        _INSTALLED = True
        return

    # ------------------------------------------------------------------
    # Cash authority: a Sentinel fill is already counted from its durable
    # command's cumulative fill quantity/price. Activity-SSE TRD is the
    # independent *fill evidence*, not a second cash-flow ledger entry.
    # ------------------------------------------------------------------
    broker_cls = alpaca.AlpacaExecutionBroker
    original_cash_activities = broker_cls.account_cash_activities

    async def cash_activities_without_trade_double_count(
            self, *, after, through):
        batch = await original_cash_activities(
            self, after=after, through=through)
        non_trade = tuple(
            activity for activity in batch.activities
            if activity.activity_type != "TRD")
        return replace(
            batch,
            activities=non_trade,
            last_activity_id=(
                non_trade[-1].activity_id if non_trade else None),
        )

    broker_cls.account_cash_activities = cash_activities_without_trade_double_count

    # ------------------------------------------------------------------
    # Terminal-recovery witness v3. The proof validates CURRENT durable state
    # covers the observed broker state, but hashes only immutable economics and
    # the retained observation. Later legitimate command progress therefore
    # cannot invalidate an already-earned recovery boundary.
    # ------------------------------------------------------------------
    def provenance_name(seq: int) -> str:
        return f"{_PROVENANCE_PREFIX}{int(seq)}"

    def witness_name(broker_name: str, account_id: str) -> str:
        return f"{_WITNESS_PREFIX}{broker_name}:{account_id}"

    def load_provenance(conn, seq: int) -> dict:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s",
                (provenance_name(seq),),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                f"broker observation {seq} has no account/asset provenance")
        state = _json(row[0], where=f"broker observation {seq} provenance")
        if (state.get("kind") != "broker-observation/v2"
                or state.get("observation_seq") != int(seq)):
            raise RuntimeError(
                f"broker observation {seq} provenance shape is invalid")
        return state

    def durable_covers_observed(*, command_row, observed_order: dict) -> bool:
        state = CommandState(str(command_row[5]))
        observed_state = CommandState(str(observed_order.get("state")))
        durable_filled = Decimal(str(command_row[7]))
        observed_filled = Decimal(
            str(observed_order.get("filled_quantity") or "0"))
        if durable_filled < observed_filled:
            return False
        # Terminal broker evidence must have been synchronized exactly. A
        # terminal command cannot legitimately move again later, so this check
        # remains stable forever.
        if observed_state in TERMINAL and state is not observed_state:
            return False
        # Nonterminal positive broker evidence cannot still be represented as a
        # local pre-transport state. Any later broker-facing/UNKNOWN state is a
        # processed state and may legitimately progress after this witness.
        if state in {CommandState.PLANNED, CommandState.SEND_PENDING}:
            return False
        return True

    def completion_proof(conn, through: datetime):
        through = journal._aware_utc(through, "terminal recovery witness")
        broker_name, account_id, _ = journal._terminal_recovery_binding(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT seq,observed_at FROM sentinel_observations"
                " WHERE terminal_recovery_through=%s AND completeness='COMPLETE'"
                " ORDER BY seq DESC",
                (through,),
            )
            candidates = cur.fetchall()

        for seq_raw, observed_at in candidates:
            seq = int(seq_raw)
            try:
                provenance = load_provenance(conn, seq)
            except RuntimeError:
                continue
            if (provenance.get("broker") != broker_name
                    or provenance.get("account_id") != account_id
                    or provenance.get("terminal_recovery_through")
                    != through.isoformat()
                    or provenance.get("completeness") != "COMPLETE"):
                continue

            immutable_commands = []
            complete = True
            for order in provenance.get("orders", []):
                key = order.get("client_key")
                if not is_sentinel_key(key):
                    continue
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT security_id,symbol,broker_instrument_id,side,"
                        " quantity,state,broker_order_id,filled_quantity,"
                        " filled_average_price FROM sentinel_commands"
                        " WHERE client_key=%s",
                        (key,),
                    )
                    command = cur.fetchone()
                if command is None:
                    complete = False
                    break
                immutable = {
                    "client_key": str(key),
                    "security_id": str(command[0]),
                    "symbol": str(command[1]),
                    "broker_id": None if command[2] is None else str(command[2]),
                    "side": str(command[3]),
                    "quantity": str(command[4]),
                    "broker_order_id": (
                        None if command[6] is None else str(command[6])),
                }
                observed_immutable = {
                    "client_key": str(key),
                    "security_id": str(order.get("security_id")),
                    "symbol": str(order.get("symbol")),
                    "broker_id": order.get("broker_id"),
                    "side": str(order.get("side")),
                    "quantity": str(order.get("quantity")),
                    "broker_order_id": str(order.get("broker_order_id")),
                }
                if immutable != observed_immutable:
                    complete = False
                    break
                if not durable_covers_observed(
                        command_row=command, observed_order=order):
                    complete = False
                    break
                immutable_commands.append(immutable)
            if not complete:
                continue

            evidence = {
                "kind": "terminal-recovery-completion/v3",
                "observation_seq": seq,
                "observed_at": journal._aware_utc(
                    observed_at, "broker observation").isoformat(),
                "processed_through": through.isoformat(),
                "provenance": provenance,
                "immutable_commands": sorted(
                    immutable_commands, key=lambda item: item["client_key"]),
            }
            digest = hashlib.sha256(json.dumps(
                evidence, sort_keys=True, separators=(",", ":"),
                default=str).encode("utf-8")).hexdigest()
            return seq, digest
        return None

    def strict_checkpoint(conn) -> datetime:
        broker_name, account_id, established_at = (
            journal._terminal_recovery_binding(conn))
        with conn.cursor() as cur:
            cur.execute(
                "SELECT broker,broker_account_id,processed_through"
                " FROM sentinel_terminal_recovery_watermark WHERE id=1")
            row = cur.fetchone()
        if row is None:
            return established_at
        if str(row[0]) != broker_name or str(row[1]) != account_id:
            raise RuntimeError(
                "terminal recovery watermark belongs to another account")
        processed = journal._aware_utc(
            row[2], "terminal recovery checkpoint")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s",
                (witness_name(broker_name, account_id),),
            )
            witness_row = cur.fetchone()
        if witness_row is None:
            # v1/v2/naked timestamps are not completion authority. Replay from
            # binding establishment once and earn a v3 witness.
            return established_at
        state = _json(
            witness_row[0], where="terminal recovery completion witness")
        proof = completion_proof(conn, processed)
        if proof is None:
            raise RuntimeError(
                "terminal recovery witness has no completed broker observation")
        seq, digest = proof
        expected = {
            "kind": "terminal-recovery-witness/v3",
            "broker": broker_name,
            "account_id": account_id,
            "processed_through": processed.isoformat(),
            "observation_seq": seq,
            "completion_sha256": digest,
        }
        if state != expected:
            raise RuntimeError(
                "terminal recovery watermark/completion witness disagree")
        return processed

    def strict_floor(conn) -> datetime:
        return strict_checkpoint(conn) - journal.TERMINAL_RECOVERY_OVERLAP

    def strict_advance(conn, through: datetime) -> datetime:
        candidate = journal._aware_utc(
            through, "terminal recovery upper boundary")
        current = strict_checkpoint(conn)
        processed = max(current, candidate)
        broker_name, account_id, _ = journal._terminal_recovery_binding(conn)
        proof = completion_proof(conn, processed)
        if proof is None:
            raise RuntimeError(
                "terminal recovery cannot advance: every Sentinel order in "
                "the exact COMPLETE observation is not yet durably reconciled")
        seq, digest = proof
        state = {
            "kind": "terminal-recovery-witness/v3",
            "broker": broker_name,
            "account_id": account_id,
            "processed_through": processed.isoformat(),
            "observation_seq": seq,
            "completion_sha256": digest,
        }
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_terminal_recovery_watermark"
                " (id,broker,broker_account_id,processed_through)"
                " VALUES (1,%s,%s,%s)"
                " ON CONFLICT (id) DO UPDATE SET"
                " broker=EXCLUDED.broker,broker_account_id=EXCLUDED.broker_account_id,"
                " processed_through=EXCLUDED.processed_through,updated_at=NOW()",
                (broker_name, account_id, processed),
            )
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
                " ON CONFLICT (cursor_name) DO UPDATE SET"
                " session=EXCLUDED.session,state=EXCLUDED.state,updated_at=NOW()",
                (witness_name(broker_name, account_id),
                 processed.date().isoformat(),
                 json.dumps(state, sort_keys=True)),
            )
        conn.commit()
        return processed

    journal.terminal_recovery_checkpoint = strict_checkpoint
    journal.terminal_recovery_floor = strict_floor
    journal.advance_terminal_recovery_watermark = strict_advance

    # ------------------------------------------------------------------
    # Upgrade boundary for restore-grade recovery. If this database already has
    # physical-backup history but no incarnation anchor, silently initializing
    # one could bless a database that was restored before this feature landed.
    # Require one explicit takeover acknowledgement instead. Fresh databases
    # with no backup marker history may initialize normally.
    # ------------------------------------------------------------------
    original_restore_reason = final.restore_increase_fence_reason

    def restore_reason_with_upgrade_fence(conn, deployment, today):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM sentinel_processed_sessions"
                " WHERE cursor_name=%s",
                (_DB_CURSOR,),
            )
            anchor = cur.fetchone()
            cur.execute(
                "SELECT takeover_epoch FROM sentinel_account_binding WHERE id=1")
            bound = cur.fetchone()
            cur.execute(
                "SELECT to_regclass('public.sentinel_backup_recovery_markers')")
            marker_relation = cur.fetchone()[0]
            marker_count = 0
            if marker_relation is not None:
                cur.execute("SELECT COUNT(*) FROM sentinel_backup_recovery_markers")
                marker_count = int(cur.fetchone()[0])
        if bound is None:
            return "restore-grade recovery has no durable account binding"
        if anchor is None and marker_count > 0 and int(bound[0]) <= 1:
            return (
                "backup-capable behavioral database predates the physical "
                "incarnation anchor. One explicit adopt-restored-account "
                "takeover is required before exposure increases; this prevents "
                "an already-restored database from silently self-certifying")
        return original_restore_reason(conn, deployment, today)

    final.restore_increase_fence_reason = restore_reason_with_upgrade_fence
    alpaca.restore_increase_fence_reason = restore_reason_with_upgrade_fence

    alpaca._ACCOUNTING_INTEGRITY_INSTALLED = True
    _INSTALLED = True


__all__ = ["install"]
