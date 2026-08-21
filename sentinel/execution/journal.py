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

import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from sentinel.execution.commands import Command
from sentinel.execution.contract import (
    BrokerFill, BrokerInstrument, BrokerObservation, Side)
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState, IN_FLIGHT


# Re-read a small boundary on every closed-order recovery. Alpaca filters order
# history by its submission clock while PostgreSQL stamps the durable watermark
# with the host clock; replay is idempotent and a gap is not.
TERMINAL_RECOVERY_OVERLAP = timedelta(minutes=5)

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
    except BaseException:
        # Never let the housekeeping commit in ``finally`` make a caller's
        # failed transaction durable. Migration in particular defers its final
        # ownership event and binding to one commit; an exception between them
        # must lose both before the session lock is released.
        conn.rollback()
        raise
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (WRITER_LOCK_KEY,))
        conn.commit()


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

class PlanEconomicsChanged(RuntimeError):
    """A stored plan_id was rebuilt with DIFFERENT economics.

    Commands have had this protection since the command-identity work; plans
    did not, and the asymmetry was invisible because `save_plan`'s comment
    delegated the check to "load_plan's caller" — and the caller that matters,
    `core.catchup.catch_up`, does not perform one.

    ```text
    plan_id = P    basket {A: 100}          stored
    restart, reconstruction defect
    plan_id = P    basket {A: 50, B: 50}    INSERT ... DO NOTHING -> no-op
                                            load_plan(P) -> {A: 100}
    ```

    Catch-up then supersedes every other plan in favour of P and proceeds with
    the OLD basket as though it were the newly calculated intent. Durable
    intent that silently is not what was computed is not immutable intent; it
    is a label, which is the same thing `CommandEconomicsChanged` exists to
    prevent one level down.

    Raised rather than reconciled, for the same reason: the stored plan may
    already have been acted on at the broker.
    """


class PlanAuthorityMissing(RuntimeError):
    """A genuine legacy plan has no durable rollout-authority stamp.

    The behavioral migration deliberately leaves all three fields NULL rather
    than manufacturing PINNED/version-1 intent. Such a row remains historical
    evidence, but it cannot be loaded as an executable :class:`ExecutionPlan`;
    an operator must prepare a new plan under the current durable rollout.
    """


#: The fields that make a plan MEAN something. A difference in any of these
#: under one plan_id is a different intention wearing the same name.
#:
#: `superseded_by` is deliberately absent — supersession is a lifecycle fact
#: about a plan, not part of its economics, and including it would make a
#: re-save of an already-superseded plan look like a divergence.
_PLAN_ECONOMICS = ("decision_session", "effective_session", "target_exposure",
                   "data_version", "shadow_snapshot_hash",
                   "sentinel_transition_hash", "strategy_fingerprint",
                   "deployment_id", "broker", "broker_account_id",
                   "takeover_epoch", "publication_fingerprint", "account_nav",
                   "account_cash", "cash_residual", "unpriced_securities",
                   "defensive_security", "rollout_mode", "rollout_version",
                   "rollout_certificate_sha256",
                   "target_basket")


def _plan_economics(plan: ExecutionPlan) -> dict:
    return {
        "decision_session": str(plan.decision_session),
        "effective_session": str(plan.effective_session),
        "target_exposure": str(plan.target_exposure),
        "data_version": plan.data_version,
        "shadow_snapshot_hash": plan.shadow_snapshot_hash,
        "sentinel_transition_hash": plan.sentinel_transition_hash,
        "strategy_fingerprint": plan.strategy_fingerprint,
        "deployment_id": plan.deployment_id,
        "broker": plan.broker,
        "broker_account_id": plan.broker_account_id,
        "takeover_epoch": plan.takeover_epoch,
        "publication_fingerprint": plan.publication_fingerprint,
        "account_nav": str(plan.account_nav),
        "account_cash": str(plan.account_cash),
        "cash_residual": str(plan.cash_residual),
        "unpriced_securities": sorted(plan.unpriced_securities),
        "defensive_security": plan.defensive_security,
        "rollout_mode": plan.rollout_mode,
        "rollout_version": plan.rollout_version,
        "rollout_certificate_sha256": plan.rollout_certificate_sha256,
        "target_basket": {k: str(v) for k, v in sorted(plan.target_basket.items())},
    }


def save_plan(conn, plan: ExecutionPlan, *, commit: bool = True) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_execution_plans (plan_id, decision_session,"
            " effective_session, target_exposure, data_version,"
            " shadow_snapshot_hash, sentinel_transition_hash,"
            " strategy_fingerprint, deployment_id, broker, broker_account_id,"
            " takeover_epoch, publication_fingerprint, account_nav,"
            " account_cash, cash_residual, unpriced_securities, defensive_security,"
            " rollout_mode,rollout_version,rollout_certificate_sha256,"
            " target_basket)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
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
             plan.strategy_fingerprint, plan.deployment_id, plan.broker,
             plan.broker_account_id, plan.takeover_epoch,
             plan.publication_fingerprint, str(plan.account_nav),
             str(plan.account_cash),
             str(plan.cash_residual),
             json.dumps(sorted(plan.unpriced_securities)),
             plan.defensive_security,
             plan.rollout_mode, plan.rollout_version,
             plan.rollout_certificate_sha256,
             json.dumps({k: str(v) for k, v in plan.target_basket.items()},
                        sort_keys=True)))
    if commit:
        conn.commit()

    # DIVERGENCE IS CHECKED HERE, not left to a caller. The original comment
    # said the check lived in `load_plan`'s caller; `core.catchup.catch_up`
    # is that caller and never performed one, so a re-derived plan with the
    # same id and different content was a silent no-op followed by a load of
    # the OLD basket.
    #
    # After the insert rather than as a constraint, and that ordering is the
    # reason the check was placed elsewhere in the first place: a constraint
    # violation inside the statement aborts the transaction before anything can
    # compare the two rows, so the error could not say WHAT differed. Reading
    # the stored row back keeps the diff available.
    stored = load_plan(conn, plan.plan_id)
    if stored is None:                                    # pragma: no cover
        raise RuntimeError(f"plan {plan.plan_id} vanished immediately after "
                           f"being written")
    want, got = _plan_economics(plan), _plan_economics(stored)
    if want != got:
        differing = {k: {"stored": got[k], "incoming": want[k]}
                     for k in _PLAN_ECONOMICS if got[k] != want[k]}
        raise PlanEconomicsChanged(
            f"plan {plan.plan_id} already exists with different economics: "
            f"{differing}. The insert is ON CONFLICT DO NOTHING, so the stored "
            f"row wins silently and every later read returns intent nobody "
            f"computed. A plan id must determine the plan.")


def load_plan(conn, plan_id: str) -> Optional[ExecutionPlan]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT plan_id, decision_session, effective_session,"
            " target_exposure, data_version, shadow_snapshot_hash,"
            " sentinel_transition_hash, strategy_fingerprint, deployment_id,"
            " broker, broker_account_id, takeover_epoch,"
            " publication_fingerprint, account_nav, account_cash, cash_residual,"
            " unpriced_securities, defensive_security, target_basket,"
            " rollout_mode,rollout_version,rollout_certificate_sha256,"
            " superseded_by FROM sentinel_execution_plans WHERE plan_id = %s",
            (plan_id,))
        row = cur.fetchone()
    if row is None:
        return None
    rollout_triple = (row[19], row[20], row[21])
    if rollout_triple == (None, None, None):
        raise PlanAuthorityMissing(
            f"plan {plan_id!r} is an unstamped legacy plan with no durable "
            "rollout authority; prepare a new plan under the current rollout "
            "version before execution")
    if row[19] is None or row[20] is None:
        raise PlanAuthorityMissing(
            f"plan {plan_id!r} has a corrupt partial rollout-authority stamp")
    unpriced = row[16] if isinstance(row[16], list) else json.loads(row[16] or "[]")
    basket = row[18] if isinstance(row[18], dict) else json.loads(row[18] or "{}")
    return ExecutionPlan(
        plan_id=str(row[0]), decision_session=row[1], effective_session=row[2],
        target_exposure=Decimal(str(row[3])),
        data_version=int(row[4]) if row[4] is not None else None,
        shadow_snapshot_hash=str(row[5] or ""),
        sentinel_transition_hash=str(row[6] or ""),
        strategy_fingerprint=str(row[7] or ""),
        deployment_id=str(row[8] or ""), broker=str(row[9] or ""),
        broker_account_id=str(row[10] or ""),
        takeover_epoch=int(row[11] or 0),
        publication_fingerprint=str(row[12] or ""),
        account_nav=Decimal(str(row[13] or 0)),
        account_cash=Decimal(str(row[14] or 0)),
        cash_residual=Decimal(str(row[15] or 0)),
        unpriced_securities=tuple(str(item) for item in unpriced),
        defensive_security=str(row[17]) if row[17] else None,
        target_basket={k: Decimal(v) for k, v in basket.items()},
        rollout_mode=str(row[19]), rollout_version=int(row[20]),
        rollout_certificate_sha256=str(row[21]) if row[21] else None,
        superseded_by=str(row[22]) if row[22] else None)


def latest_plan(conn) -> Optional[ExecutionPlan]:
    """The newest UNSUPERSEDED plan — the only one that may be executed.

    Ordered by `created_at` then `plan_id` so the answer is total even when two
    plans land in the same transaction timestamp; a non-deterministic "latest"
    would be worse than none. Wholly unstamped legacy plans are historical and
    deliberately unexecutable, so current-plan discovery skips them. That lets
    preparation create a stamped replacement which supersedes the legacy row;
    direct :func:`load_plan` remains a refusal for that same row.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT plan_id,rollout_mode,rollout_version,"
                    " rollout_certificate_sha256"
                    " FROM sentinel_execution_plans"
                    " WHERE superseded_by IS NULL"
                    " ORDER BY created_at DESC, plan_id DESC")
        rows = cur.fetchall()
    stamped_plan_id = None
    unstamped_plan_ids = []
    for row in rows:
        rollout_triple = (row[1], row[2], row[3])
        if rollout_triple == (None, None, None):
            unstamped_plan_ids.append(str(row[0]))
            continue
        if row[1] is None or row[2] is None:
            raise PlanAuthorityMissing(
                f"plan {row[0]!r} has a corrupt partial rollout-authority "
                "stamp")
        if stamped_plan_id is None:
            stamped_plan_id = str(row[0])
    if stamped_plan_id is not None and unstamped_plan_ids:
        raise PlanAuthorityMissing(
            "stamped and unstamped plans are both current; no plan is "
            "executable until the ambiguous supersession state is resolved")
    return load_plan(conn, stamped_plan_id) if stamped_plan_id else None


def supersede_all_but(conn, plan_id: str, *, commit: bool = True) -> int:
    """Mark every other unsuperseded plan as replaced by this one.

    Catch-up produces one plan per missed session, and only the last of them
    describes current intent. Superseding the rest is what makes "historical
    sessions advance state, historical execution intent is never replayed" a
    property of the DATABASE rather than a habit of the caller.
    """
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_execution_plans SET superseded_by = %s"
                    " WHERE superseded_by IS NULL AND plan_id <> %s",
                    (plan_id, plan_id))
        n = cur.rowcount
    if commit:
        conn.commit()
    return n


def adopt_current_plan(conn, plan: ExecutionPlan, *, commit: bool = True
                       ) -> ExecutionPlan:
    """Persist and supersede as one transaction.

    The previous two-call form committed after the insert and again after
    supersession. A crash between those commits left two unsuperseded plans,
    which makes "the durable current plan" ambiguous at the exact boundary
    preparation exists to establish.
    """
    try:
        save_plan(conn, plan, commit=False)
        supersede_all_but(conn, plan.plan_id, commit=False)
        if commit:
            conn.commit()
    except BaseException:
        if commit:
            conn.rollback()
        raise
    stored = load_plan(conn, plan.plan_id)
    if stored is None:                                      # pragma: no cover
        raise RuntimeError(f"plan {plan.plan_id} vanished after adoption")
    return stored


def supersede_plan(conn, plan_id: str, by_plan_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE sentinel_execution_plans SET superseded_by = %s"
                    " WHERE plan_id = %s AND superseded_by IS NULL",
                    (by_plan_id, plan_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

class CommandEconomicsChanged(RuntimeError):
    """A stored client key was rebuilt with DIFFERENT economics.

    The advertised property is "deterministic key -> deterministic side effect".
    Without this check it was only "deterministic key -> deterministic plan and
    security", with the quantity trusted to whatever the caller happened to
    reconstruct — and since the upsert deliberately does not rewrite quantity,
    the database could hold X while the wire carried Y under one identity.

    Raised rather than reconciled. There is no safe automatic answer: the stored
    row may already have been acted on at the broker.
    """


#: Fields a client key is a promise about. They may never change under it; a
#: genuinely new intent needs `CommandIdentity.superseding()`, which mints a new
#: key precisely so the old promise stays intact.
_IMMUTABLE = ("security_id", "side", "quantity", "symbol",
              "broker_instrument_id",
              "deployment_id", "broker", "broker_account_id",
              "takeover_epoch")


def _assert_economics_unchanged(cur, command: Command) -> None:
    cur.execute("SELECT security_id, side, quantity, symbol,"
                " broker_instrument_id, deployment_id, broker,"
                " broker_account_id, takeover_epoch"
                " FROM sentinel_commands"
                " WHERE client_key = %s", (command.client_key,))
    row = cur.fetchone()
    if row is None:
        return
    stored = {"security_id": str(row[0]), "side": str(row[1]),
              "quantity": Decimal(str(row[2])), "symbol": str(row[3]),
              "broker_instrument_id": (
                  str(row[4]) if row[4] is not None else None),
              "deployment_id": str(row[5]), "broker": str(row[6]),
              "broker_account_id": str(row[7]),
              "takeover_epoch": int(row[8])}
    incoming = {"security_id": command.security_id, "side": command.side.value,
                "quantity": command.quantity,
                "symbol": command.instrument.symbol,
                "broker_instrument_id": command.instrument.broker_id,
                **command.identity.deployment.to_dict()}
    differs = {k: (stored[k], incoming[k]) for k in _IMMUTABLE
               if stored[k] != incoming[k]}
    if differs:
        raise CommandEconomicsChanged(
            f"{command.client_key} already exists with different economics: "
            + "; ".join(f"{k} stored={s!r} incoming={i!r}"
                        for k, (s, i) in sorted(differs.items()))
            + ". A client key is a promise about WHAT it does, not only about "
              "which plan and security it belongs to. New intent needs a new "
              "identity — CommandIdentity.superseding() — so the promise the "
              "broker may already have acted on stays intact.")


def save_command(conn, command: Command, *, previous: Optional[CommandState] = None
                 ) -> None:
    """Persist the current state AND append the transition that produced it.

    Both in one transaction: a command row that moved without a matching event,
    or an event with no corresponding row, is a history that cannot be trusted
    to explain itself.

    Refuses outright if the key already exists carrying different economics —
    see `_assert_economics_unchanged`.
    """
    with conn.cursor() as cur:
        _assert_economics_unchanged(cur, command)
        cur.execute(
            "INSERT INTO sentinel_commands (client_key, plan_id, security_id,"
            " revision, deployment_id, broker, broker_account_id,"
            " takeover_epoch, symbol, broker_instrument_id, side, quantity, state,"
            " broker_order_id, filled_quantity, filled_average_price, detail)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (client_key) DO UPDATE SET"
            " state = EXCLUDED.state,"
            " broker_order_id = COALESCE(EXCLUDED.broker_order_id,"
            "                            sentinel_commands.broker_order_id),"
            " filled_quantity = EXCLUDED.filled_quantity,"
            " filled_average_price = COALESCE("
            "     EXCLUDED.filled_average_price,"
            "     sentinel_commands.filled_average_price),"
            " detail = EXCLUDED.detail, updated_at = NOW()",
            (command.client_key, command.identity.plan_id, command.security_id,
             command.identity.revision,
             command.identity.deployment.deployment_id,
             command.identity.deployment.broker,
             command.identity.deployment.broker_account_id,
             command.identity.deployment.takeover_epoch,
             command.instrument.symbol,
             command.instrument.broker_id, command.side.value,
             str(command.quantity), command.state.value,
             command.broker_order_id, str(command.filled_quantity),
             (str(command.filled_average_price)
              if command.filled_average_price is not None else None),
             command.detail))
        cur.execute(
            "INSERT INTO sentinel_command_events (client_key, from_state,"
            " to_state, filled_quantity, detail) VALUES (%s,%s,%s,%s,%s)",
            (command.client_key, previous.value if previous else None,
             command.state.value, str(command.filled_quantity), command.detail))
    conn.commit()


def adopt_recovered_order(conn, order, *, deployment: DeploymentIdentity) -> None:
    """Write a Sentinel-keyed broker order the journal has never heard of.

    Reached after a restore from a backup that predates the order. The key
    proves it is OURS — it carries our prefix — but it cannot be REGENERATED,
    because a hash does not yield back the `plan_id` and `revision` that made
    it. So the row is stored with the broker's own economics, marked
    `recovered`, and exempted from the recompute check that guards rows this
    generation minted.

    **Adoption is what makes recovery converge.** Identifying the order without
    storing it left the position permanently unattributable: `expected_book`
    stayed empty, the holding read as foreign activity forever, and the
    appliance could de-risk but never re-risk. Reporting a recovered order and
    then doing nothing with it is not recovery, it is a description of the
    problem.

    LIMIT, stated because adoption is an act of trust: "ours" is decided by the
    key PREFIX, since a hash cannot be inverted to prove which deployment and
    epoch minted it. That is deliberate — an order from a previous takeover
    epoch is genuinely ours and must be adopted — but it means anything able to
    write a `sntl-` client id on this account would be adopted too. The
    protection against that is the one-appliance-one-account binding, not this
    function.
    """
    # IN A SAVEPOINT. `ON CONFLICT (client_key)` covers a repeat adoption, but
    # not the PARTIAL UNIQUE INDEX on in-flight security_id — and two live
    # Sentinel-keyed orders for one security is precisely a condition worth
    # surfacing rather than crashing on. A raised constraint violation poisons
    # the whole transaction, so the rest of the reconciliation would fail with
    # an error about the wrong thing. Same lesson as Stocker's intent shadow.
    try:
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT adopt_recovered")
            cur.execute(
                "INSERT INTO sentinel_commands (client_key, plan_id, security_id,"
                " revision, deployment_id, broker, broker_account_id,"
                " takeover_epoch, symbol, broker_instrument_id, side, quantity, state,"
                " broker_order_id, filled_quantity, filled_average_price, detail,"
                " recovered, created_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,"
                " COALESCE(%s,NOW()))"
                " ON CONFLICT (client_key) DO NOTHING",
                (order.client_key, RECOVERED_PLAN_ID,
                 order.instrument.security_id, 0,
                 deployment.deployment_id, deployment.broker,
                 deployment.broker_account_id, deployment.takeover_epoch,
                 order.instrument.symbol,
                 order.instrument.broker_id, order.side.value,
                 str(order.quantity), order.state.value, order.broker_order_id,
                 str(order.filled_quantity),
                 (str(order.filled_average_price)
                  if order.filled_average_price is not None else None),
                 "adopted from the broker after a restore",
                 order.submitted_at))
            cur.execute(
                "INSERT INTO sentinel_command_events (client_key, from_state,"
                " to_state, filled_quantity, detail) VALUES (%s,NULL,%s,%s,%s)",
                (order.client_key, order.state.value, str(order.filled_quantity),
                 "recovered: present at the broker, absent from the journal"))
            cur.execute("RELEASE SAVEPOINT adopt_recovered")
        conn.commit()
    except Exception as exc:                                  # noqa: BLE001
        with conn.cursor() as cur:
            cur.execute("ROLLBACK TO SAVEPOINT adopt_recovered")
        conn.commit()
        raise RecoveredOrderConflict(
            f"could not adopt {order.client_key} for "
            f"{order.instrument.security_id}: {exc}. The broker is reporting a "
            f"Sentinel-keyed order this appliance cannot place beside what it "
            f"already holds in flight for that security — two live orders on one "
            f"intent, which needs a human rather than a retry.") from exc


class RecoveredOrderConflict(RuntimeError):
    """A recovered order cannot coexist with what the journal already holds."""


#: Plan id given to adopted rows. A real plan id would be a lie — the plan that
#: produced the order is precisely what a stale restore lost.
RECOVERED_PLAN_ID = "RECOVERED"


def _row_to_command(row, deployment: DeploymentIdentity) -> Command:
    (client_key, plan_id, security_id, revision, deployment_id, broker,
     broker_account_id, takeover_epoch, symbol, broker_instrument_id,
     side, quantity, state, broker_order_id, filled, filled_average_price,
     detail, recovered, created_at) = row
    stored_deployment = DeploymentIdentity(
        deployment_id=str(deployment_id), broker=str(broker),
        broker_account_id=str(broker_account_id),
        takeover_epoch=int(takeover_epoch))
    if (stored_deployment.deployment_id != deployment.deployment_id
            or stored_deployment.broker != deployment.broker
            or stored_deployment.broker_account_id
            != deployment.broker_account_id
            or stored_deployment.takeover_epoch > deployment.takeover_epoch):
        raise StoredKeyMismatch(
            f"stored command {client_key} belongs to "
            f"{stored_deployment.to_dict()}, not current bound namespace "
            f"{deployment.to_dict()}. A restored adoption may reconcile prior "
            "epochs of the same deployment/account, never another account or "
            "a future generation.")
    identity = CommandIdentity(deployment=stored_deployment,
                               plan_id=str(plan_id),
                               security_id=str(security_id),
                               revision=int(revision))
    command = Command(
        identity=identity,
        instrument=BrokerInstrument(security_id=str(security_id),
                                    symbol=str(symbol),
                                    broker_id=broker_instrument_id),
        side=Side(side), quantity=Decimal(str(quantity)),
        state=CommandState(state), broker_order_id=broker_order_id,
        filled_quantity=Decimal(str(filled)),
        filled_average_price=(Decimal(str(filled_average_price))
                              if filled_average_price is not None else None),
        detail=str(detail or ""),
        created_at=created_at)
    if recovered:
        # ADOPTED, so the key is not regenerable by construction and the check
        # below would reject every recovered row. The stored key is carried
        # verbatim so `client_key` still returns something the broker knows.
        return replace(command, recovered_key=str(client_key))
    if command.client_key != str(client_key):
        # THE KEY IS DERIVED, so a stored key that no longer recomputes means
        # the binding changed under us — a different account or a bumped
        # takeover epoch. Loading it silently would attribute a predecessor's
        # order to the current generation.
        raise StoredKeyMismatch(
            f"stored client_key {client_key} does not recompute from its own "
            f"stored minting identity (would be {command.client_key}). The "
            f"row's durable identity metadata cannot explain its key.")
    return command


class StoredKeyMismatch(RuntimeError):
    """A journal row cannot be reconstructed under the current binding."""


_COMMAND_COLUMNS = ("client_key, plan_id, security_id, revision, deployment_id,"
                    " broker, broker_account_id, takeover_epoch, symbol,"
                    " broker_instrument_id, side, quantity, state,"
                    " broker_order_id, filled_quantity, filled_average_price,"
                    " detail, recovered, created_at")


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

def fill_fingerprint(fill: BrokerFill) -> str:
    """A fill's identity, derived from WHAT IT IS rather than where it appeared.

    The previous key was the fill's ordinal position in the list the broker
    happened to return. That is not an identity: a query over a different window
    returns a different list, so the same economic fill lands under a different
    `seq` — and, worse, a DIFFERENT fill can inherit one already used, which
    `ON CONFLICT DO NOTHING` then silently discards. An accounting ledger whose
    primary key depends on how you asked the question will eventually both
    double-count and drop.

    Derived instead from order, quantity, price and timestamp. Two genuinely
    distinct fills that agree on all four are economically indistinguishable, so
    collapsing them is the correct behaviour rather than a lost row.

    NOT the final answer. Brokers expose their own activity ids — and trade
    corrections and busts, which no content hash can model — so before this
    table becomes the accounting ledger it must carry broker-native activity
    identity. Recorded here as the known limit rather than left to be
    discovered.
    """
    blob = "|".join((
        str(fill.broker_order_id), str(fill.quantity), str(fill.price),
        fill.filled_at.isoformat() if fill.filled_at else "",
    ))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def record_fills(conn, fills: Sequence[BrokerFill]) -> int:
    """Idempotent on the fill's CONTENT, not on its position in a response.

    A recovery that re-reads the broker's recent fills must not double-count
    them: the same fill twice inflates the position Sentinel believes it holds
    and generates a spurious sell.
    """
    written = 0
    with conn.cursor() as cur:
        for fill in fills:
            cur.execute(
                "INSERT INTO sentinel_fills (broker_order_id, fill_key,"
                " client_key, quantity, price, filled_at)"
                " VALUES (%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (broker_order_id, fill_key) DO NOTHING",
                (fill.broker_order_id, fill_fingerprint(fill), fill.client_key,
                 str(fill.quantity), str(fill.price), fill.filled_at))
            written += cur.rowcount
    conn.commit()
    return written


def terminal_recovery_checkpoint(conn) -> datetime:
    """Last terminal submission boundary fully processed by reconciliation.

    A raw observation timestamp is deliberately never used here. Observation is
    recorded before recovered commands are adopted; deriving this value from
    that audit row would let a crash in the middle skip the very order recovery
    exists to find. Before the first processed watermark, binding establishment
    is the earliest time an ordinary Sentinel command may legitimately exist.
    """
    broker, account_id, established_at = _terminal_recovery_binding(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT broker, broker_account_id, processed_through"
            " FROM sentinel_terminal_recovery_watermark WHERE id = 1")
        row = cur.fetchone()
    if row is None:
        return established_at
    if str(row[0]) != broker or str(row[1]) != account_id:
        raise RuntimeError(
            "terminal recovery watermark belongs to "
            f"{row[0]}/{row[1]}, not bound account {broker}/{account_id}")
    if row[2] is None:
        raise RuntimeError(
            "terminal recovery watermark has no processed boundary")
    return _aware_utc(row[2], "terminal recovery checkpoint")


def terminal_recovery_floor(conn) -> datetime:
    """Inclusive replay floor, including the fixed clock-skew overlap."""
    return terminal_recovery_checkpoint(conn) - TERMINAL_RECOVERY_OVERLAP


def advance_terminal_recovery_watermark(conn, through: datetime) -> datetime:
    """Commit the monotonic processed boundary after command recovery.

    Callers must invoke this only after every discovered Sentinel-keyed order is
    durable. Replays before this commit are harmless because adoption and
    command synchronization are idempotent; advancing before them creates an
    unrecoverable gap.
    """
    candidate = _aware_utc(through, "terminal recovery upper boundary")
    current = terminal_recovery_checkpoint(conn)
    broker, account_id, _established_at = _terminal_recovery_binding(conn)
    processed = max(current, candidate)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_terminal_recovery_watermark"
            " (id, broker, broker_account_id, processed_through)"
            " VALUES (1,%s,%s,%s)"
            " ON CONFLICT (id) DO UPDATE SET"
            " processed_through = GREATEST("
            "   sentinel_terminal_recovery_watermark.processed_through,"
            "   EXCLUDED.processed_through),"
            " updated_at = NOW()",
            (broker, account_id, processed))
    conn.commit()
    return processed


def _aware_utc(value, where: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{where} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _terminal_recovery_binding(conn) -> tuple[str, str, datetime]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT broker, broker_account_id, established_at"
            " FROM sentinel_account_binding WHERE id = 1")
        row = cur.fetchone()
    if row is None or row[2] is None:
        raise RuntimeError(
            "terminal recovery has no account-binding establishment boundary")
    broker = str(row[0] or "").strip()
    account_id = str(row[1] or "").strip()
    if not broker or not account_id:
        raise RuntimeError("terminal recovery account binding is incomplete")
    return broker, account_id, _aware_utc(
        row[2], "account-binding establishment boundary")


def record_observation(conn, observation: BrokerObservation,
                       runtime_state: str = "") -> int:
    """Retained because a reconciliation dispute is unanswerable without knowing
    what the broker actually said at the time."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_observations (observed_at,"
            " terminal_recovery_through, completeness, positions, orders,"
            " runtime_state) VALUES (%s,%s,%s,%s,%s,%s) RETURNING seq",
            (observation.observed_at, observation.terminal_recovery_through,
             observation.completeness.value,
             json.dumps({k: str(v) for k, v in
                          sorted(observation.positions_by_security().items())}),
             json.dumps([{"id": o.broker_order_id, "key": o.client_key,
                          "security_id": o.instrument.security_id,
                          "broker_instrument_id": o.instrument.broker_id,
                          "side": o.side.value, "state": o.state.value,
                          "qty": str(o.quantity),
                          "filled": str(o.filled_quantity)}
                         for o in observation.orders]),
             runtime_state))
        seq = int(cur.fetchone()[0])
    conn.commit()
    return seq


def finalize_observation_runtime(conn, seq: int, runtime_state: str) -> None:
    """Attach the completed reconciliation verdict to its exact observation.

    The audit row is inserted before recovery because a crash must retain the
    evidence that was read. Its initial ``RECONCILING`` value is therefore not
    the final classification. Updating by the returned sequence only after all
    adoption/synchronisation/classification work completes keeps the durable
    panel truthful without ever rewriting the observed broker payload.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_observations SET runtime_state=%s WHERE seq=%s",
            (str(runtime_state), int(seq)))
        if cur.rowcount != 1:
            raise RuntimeError(
                f"broker observation {seq} vanished before reconciliation "
                "could record its final runtime state")
    conn.commit()
