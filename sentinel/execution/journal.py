"""Durable state for the execution layer, and the single-writer lock.

The crash-safety property of the whole layer is an ORDERING, and this module
exists to make that ordering the natural way to write the code:

```text
save_command(PLANNED)          durable, nothing sent
save_command(SEND_PENDING)     durable, BEFORE the network call
    -> broker.submit()
save_command(<outcome>)        durable, after
```

A crash anywhere in that sequence is recoverable, because the client key is
derived and the row is already there to be found. Reverse the middle two and a
crash in the gap leaves a live order with no local record and no key to look it
up by — the one genuinely unrecoverable case.

## Why the journal is two tables

`sentinel_commands` is the CURRENT answer, one row per client key, with a partial
unique index that makes "at most one in-flight command per security" a database
constraint rather than an application convention. `sentinel_command_events` is
how it got there. A post-mortem needs the second; a running appliance needs the
first; conflating them gives you a table that is either lossy or unqueryable.

## The lock

One appliance, one account, one writer. `pg_try_advisory_lock` is held for the
session rather than the transaction, so it survives the many small commits a
reconcile makes, and it is released automatically if the connection dies — which
is the behaviour you want when the holder is a process that just crashed.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerFill, BrokerInstrument, BrokerObservation, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState, IN_FLIGHT

#: Arbitrary but FIXED. Two appliances sharing a database would deadlock on
#: purpose, which is the intent — they must not both be writing.
WRITER_LOCK_KEY = 0x5E27_1E10


class WriterLockUnavailable(RuntimeError):
    """Another process holds the writer lock. Do not proceed."""


@contextmanager
def writer_lock(conn):
    """Exclusive write access, or refuse.

    `pg_try_advisory_lock`, not `pg_advisory_lock`: blocking would turn "another
    writer exists" into "this process hangs forever", and a hung trading
    appliance is harder to diagnose than one that says why it stopped.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (WRITER_LOCK_KEY,))
        acquired = bool(cur.fetchone()[0])
    if not acquired:
        raise WriterLockUnavailable(
            "another process holds the Sentinel writer lock on this database. "
            "One appliance controls one account and there is exactly one "
            "writer; a second would race every command it creates.")
    try:
        yield
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (WRITER_LOCK_KEY,))
        conn.commit()


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def save_plan(conn, plan: ExecutionPlan) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_execution_plans (plan_id, decision_session,"
            " effective_session, target_exposure, data_version,"
            " shadow_snapshot_hash, sentinel_transition_hash,"
            " strategy_fingerprint, target_basket)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            # IDEMPOTENT ON IDENTICAL CONTENT ONLY. A re-derived plan for the
            # same session is normal after a restart; a plan with the SAME id
            # and DIFFERENT content is a bug, and DO NOTHING would hide it. The
            # divergence check is in `load_plan`'s caller, not here, because a
            # constraint violation inside this statement would poison the
            # transaction before anything could compare the two.
            " ON CONFLICT (plan_id) DO NOTHING",
            (plan.plan_id, plan.decision_session, plan.effective_session,
             str(plan.target_exposure), plan.data_version,
             plan.shadow_snapshot_hash, plan.sentinel_transition_hash,
             plan.strategy_fingerprint,
             json.dumps({k: str(v) for k, v in plan.target_basket.items()},
                        sort_keys=True)))
    conn.commit()


def load_plan(conn, plan_id: str) -> Optional[ExecutionPlan]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT plan_id, decision_session, effective_session,"
            " target_exposure, data_version, shadow_snapshot_hash,"
            " sentinel_transition_hash, strategy_fingerprint, target_basket,"
            " superseded_by FROM sentinel_execution_plans WHERE plan_id = %s",
            (plan_id,))
        row = cur.fetchone()
    if row is None:
        return None
    basket = row[8] if isinstance(row[8], dict) else json.loads(row[8] or "{}")
    return ExecutionPlan(
        plan_id=str(row[0]), decision_session=row[1], effective_session=row[2],
        target_exposure=Decimal(str(row[3])),
        data_version=int(row[4]) if row[4] is not None else None,
        shadow_snapshot_hash=str(row[5] or ""),
        sentinel_transition_hash=str(row[6] or ""),
        strategy_fingerprint=str(row[7] or ""),
        target_basket={k: Decimal(v) for k, v in basket.items()},
        superseded_by=str(row[9]) if row[9] else None)


def supersede_plan(conn, plan_id: str, by_plan_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_execution_plans SET superseded_by = %s"
                    " WHERE plan_id = %s AND superseded_by IS NULL",
                    (by_plan_id, plan_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def save_command(conn, command: Command, *, previous: Optional[CommandState] = None
                 ) -> None:
    """Persist the current state AND append the transition that produced it.

    Both in one transaction: a command row that moved without a matching event,
    or an event with no corresponding row, is a history that cannot be trusted
    to explain itself.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_commands (client_key, plan_id, security_id,"
            " revision, symbol, broker_instrument_id, side, quantity, state,"
            " broker_order_id, filled_quantity, detail)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (client_key) DO UPDATE SET"
            " state = EXCLUDED.state,"
            " broker_order_id = COALESCE(EXCLUDED.broker_order_id,"
            "                            sentinel_commands.broker_order_id),"
            " filled_quantity = EXCLUDED.filled_quantity,"
            " detail = EXCLUDED.detail, updated_at = NOW()",
            (command.client_key, command.identity.plan_id, command.security_id,
             command.identity.revision, command.instrument.symbol,
             command.instrument.broker_id, command.side.value,
             str(command.quantity), command.state.value,
             command.broker_order_id, str(command.filled_quantity),
             command.detail))
        cur.execute(
            "INSERT INTO sentinel_command_events (client_key, from_state,"
            " to_state, filled_quantity, detail) VALUES (%s,%s,%s,%s,%s)",
            (command.client_key, previous.value if previous else None,
             command.state.value, str(command.filled_quantity), command.detail))
    conn.commit()


def _row_to_command(row, deployment: DeploymentIdentity) -> Command:
    (client_key, plan_id, security_id, revision, symbol, broker_instrument_id,
     side, quantity, state, broker_order_id, filled, detail) = row
    identity = CommandIdentity(deployment=deployment, plan_id=str(plan_id),
                               security_id=str(security_id),
                               revision=int(revision))
    command = Command(
        identity=identity,
        instrument=BrokerInstrument(security_id=str(security_id),
                                    symbol=str(symbol),
                                    broker_id=broker_instrument_id),
        side=Side(side), quantity=Decimal(str(quantity)),
        state=CommandState(state), broker_order_id=broker_order_id,
        filled_quantity=Decimal(str(filled)), detail=str(detail or ""))
    if command.client_key != str(client_key):
        # THE KEY IS DERIVED, so a stored key that no longer recomputes means
        # the binding changed under us — a different account or a bumped
        # takeover epoch. Loading it silently would attribute a predecessor's
        # order to the current generation.
        raise StoredKeyMismatch(
            f"stored client_key {client_key} does not recompute from its own "
            f"row under the current binding (would be {command.client_key}). "
            f"The account binding or takeover epoch has changed; these commands "
            f"belong to a previous generation and must be recovered, not "
            f"resumed.")
    return command


class StoredKeyMismatch(RuntimeError):
    """A journal row cannot be reconstructed under the current binding."""


_COMMAND_COLUMNS = ("client_key, plan_id, security_id, revision, symbol,"
                    " broker_instrument_id, side, quantity, state,"
                    " broker_order_id, filled_quantity, detail")


def load_commands(conn, deployment: DeploymentIdentity, *,
                  plan_id: Optional[str] = None,
                  states: Optional[Iterable[CommandState]] = None
                  ) -> tuple:
    sql = f"SELECT {_COMMAND_COLUMNS} FROM sentinel_commands WHERE TRUE"
    params: list = []
    if plan_id is not None:
        sql += " AND plan_id = %s"
        params.append(plan_id)
    if states is not None:
        sql += " AND state = ANY(%s)"
        params.append([s.value for s in states])
    sql += " ORDER BY client_key"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return tuple(_row_to_command(r, deployment) for r in rows)


def in_flight_commands(conn, deployment: DeploymentIdentity) -> tuple:
    """Everything that could still move a position — including UNKNOWN.

    This is the set `authorize` consults, and the set a restart has to resolve
    before it may create anything new.
    """
    return load_commands(conn, deployment, states=sorted(IN_FLIGHT,
                                                         key=lambda s: s.value))


def command_history(conn, client_key: str) -> tuple:
    with conn.cursor() as cur:
        cur.execute("SELECT from_state, to_state, filled_quantity, detail, at"
                    " FROM sentinel_command_events WHERE client_key = %s"
                    " ORDER BY seq", (client_key,))
        return tuple({"from": r[0], "to": r[1],
                      "filled": str(r[2]) if r[2] is not None else None,
                      "detail": r[3], "at": r[4]} for r in cur.fetchall())


# ---------------------------------------------------------------------------
# Fills and observations
# ---------------------------------------------------------------------------

def record_fills(conn, fills: Sequence[BrokerFill]) -> int:
    """Idempotent on (broker_order_id, seq).

    A recovery that re-reads the broker's recent fills MUST NOT double-count
    them: the same fill arriving twice would inflate the position Sentinel
    believes it holds and generate a spurious sell. `seq` is the fill's ordinal
    within its order, which is stable across re-reads in a way a timestamp is
    not.
    """
    written = 0
    with conn.cursor() as cur:
        per_order: dict = {}
        for fill in fills:
            seq = per_order.get(fill.broker_order_id, 0)
            per_order[fill.broker_order_id] = seq + 1
            cur.execute(
                "INSERT INTO sentinel_fills (broker_order_id, seq, client_key,"
                " quantity, price, filled_at) VALUES (%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (broker_order_id, seq) DO NOTHING",
                (fill.broker_order_id, seq, fill.client_key,
                 str(fill.quantity), str(fill.price), fill.filled_at))
            written += cur.rowcount
    conn.commit()
    return written


def record_observation(conn, observation: BrokerObservation,
                       runtime_state: str = "") -> None:
    """Retained because a reconciliation dispute is unanswerable without knowing
    what the broker actually said at the time."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_observations (observed_at, completeness,"
            " positions, orders, runtime_state) VALUES (%s,%s,%s,%s,%s)",
            (observation.observed_at, observation.completeness.value,
             json.dumps({k: str(v) for k, v in
                         sorted(observation.positions_by_security().items())}),
             json.dumps([{"id": o.broker_order_id, "key": o.client_key,
                          "security_id": o.instrument.security_id,
                          "side": o.side.value, "state": o.state.value,
                          "qty": str(o.quantity),
                          "filled": str(o.filled_quantity)}
                         for o in observation.orders]),
             runtime_state))
    conn.commit()
