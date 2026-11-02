"""Writer-locked original LIVE commands and complete fresh native evidence."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import os

from sentinel import binding as binding_module
from sentinel.authority.live_runtime import TRUST_ROOTS_PATH_ENV, _enrollment, _path, _public_bytes
from sentinel.authority.canonical import _parse_canonical_json
from sentinel.authority.model import AuthorityRefused
from sentinel.execution import journal, protected_limits, reconcile, target_reprojection
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerAccountSnapshot, BrokerObservation, NativeFundingFacts, Side
from sentinel.execution.live_order_policy import LiveOrderDeferred, LiveOrderRefused
from sentinel.execution.live_settlement import (
    LiveFundingAdmission, account_snapshot_sha256, positions_sha256,
)
from sentinel.execution.live_transport import LiveOrderContext
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import IN_FLIGHT, CommandState


FUNDING_CERTIFICATE_PATH_ENV = "SENTINEL_LIVE_FUNDING_CERTIFICATE_PATH"
MAX_CONTEXT_COMMANDS = 10000


def load_live_funding_admission(*, env: Mapping[str, str] | None = None) -> LiveFundingAdmission | None:
    """Read explicit public evidence; no defaults qualify a settlement issuer."""
    e = os.environ if env is None else env
    if FUNDING_CERTIFICATE_PATH_ENV not in e or e[FUNDING_CERTIFICATE_PATH_ENV] == "":
        return None
    certificate_path = _path(e, FUNDING_CERTIFICATE_PATH_ENV)
    roots_path = _path(e, TRUST_ROOTS_PATH_ENV)
    payload = _public_bytes(certificate_path)
    raw = _parse_canonical_json(payload, label="LIVE public funding")
    from sentinel.execution.live_settlement import FUNDING_SCHEMA
    from sentinel.execution.live_native_funding import NATIVE_FUNDING_SCHEMA, NativeFundingContractAdmission
    if raw.get("schema") == FUNDING_SCHEMA:
        admission_type = LiveFundingAdmission
    elif raw.get("schema") == NATIVE_FUNDING_SCHEMA:
        admission_type = NativeFundingContractAdmission
    else:
        raise AuthorityRefused("LIVE public funding has an unsupported signed schema")
    return admission_type(certificate=payload,
        certificate_provider=lambda: _public_bytes(certificate_path),
        enrollment_provider=lambda: _enrollment(roots_path))


def _require_writer(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid()"
            " AND locktype='advisory' AND classid=0 AND objid=%s"
            " AND objsubid=1 AND mode='ExclusiveLock' AND granted)", (journal.WRITER_LOCK_KEY,))
        owned = cur.fetchone()[0]
    if owned is not True:
        raise LiveOrderRefused("LIVE_CONTEXT_WRITER_LOCK_REQUIRED")


def _binding(conn, expected):
    actual = binding_module.require(conn)
    if actual != expected or actual.broker != "alpaca-live":
        raise LiveOrderRefused("LIVE_CONTEXT_BINDING_CHANGED")
    return actual


def _commands(conn, bound) -> tuple[Command, ...]:
    with conn.cursor() as cur:
        cur.execute("SELECT client_key FROM sentinel_commands ORDER BY client_key LIMIT %s",
                    (MAX_CONTEXT_COMMANDS + 1,))
        keys = tuple(row[0] for row in cur.fetchall())
    if len(keys) > MAX_CONTEXT_COMMANDS:
        raise LiveOrderRefused("LIVE_CONTEXT_JOURNAL_BOUND_EXCEEDED")
    commands = journal.load_commands(conn, bound.identity, client_keys=keys)
    if len(commands) != len(keys):
        raise LiveOrderRefused("LIVE_CONTEXT_JOURNAL_CHANGED")
    return commands


def _clock(now):
    value = now() if callable(now) else now
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise LiveOrderRefused("LIVE_CONTEXT_AWARE_CLOCK_REQUIRED")
    return value


def _native_funding_shape(facts):
    if facts is None:
        return None
    if type(facts) is not NativeFundingFacts:
        raise LiveOrderRefused("LIVE_CONTEXT_NATIVE_FUNDING_FACTS_INVALID")
    return (facts.source_profile, facts.base_url, facts.account_id, facts.currency,
            facts.account_snapshot_sha256, facts.amounts)


def _check_observation(observation, *, commands, request, bound, actions):
    if type(observation) is not BrokerObservation or not observation.is_complete:
        raise LiveOrderDeferred("LIVE_CONTEXT_OBSERVATION_INCOMPLETE")
    if not bound.identity.matches_account(observation.account_identity):
        raise LiveOrderRefused("LIVE_CONTEXT_ACCOUNT_CHANGED")
    positions_sha256(observation.positions)
    known = {command.client_key: command for command in commands}
    for order in observation.orders:
        command = known.get(order.client_key)
        if command is None or reconcile._order_command_conflict(order, command) is not None:
            raise LiveOrderRefused("LIVE_CONTEXT_FOREIGN_OR_CHANGED_ORDER")
        if order.client_key == request.client_key:
            raise LiveOrderDeferred("LIVE_CONTEXT_REQUEST_ALREADY_OBSERVED_RECOVER_FIRST")
        if (order.state is not command.state or order.filled_quantity != command.filled_quantity
                or order.filled_average_price != command.filled_average_price):
            raise LiveOrderDeferred("LIVE_CONTEXT_JOURNAL_RECONCILIATION_REQUIRED")
    expected = reconcile.expected_book_from_commands(commands, actions=actions)
    actual = {position.instrument.security_id: position.quantity
              for position in observation.positions if position.quantity != 0}
    if actual != expected:
        raise LiveOrderDeferred("LIVE_CONTEXT_HELD_BOOK_RECONCILIATION_REQUIRED")


async def load_live_order_context(
        conn, *, broker, plan: ExecutionPlan, binding, client_key: str, actions,
        now=None) -> LiveOrderContext:
    """Read without reconciling the currently unsent SEND_PENDING command.

    The caller holds the journal writer lock through this function, subsequent
    policy checks and dispatch. ``now`` is the actual original read-start clock;
    a callable is sampled again after collection to refuse backward movement.
    """
    _require_writer(conn)
    bound = _binding(conn, binding)
    if (type(plan) is not ExecutionPlan or plan.superseded_by is not None
            or journal.load_plan(conn, plan.plan_id) != plan):
        raise LiveOrderRefused("LIVE_CONTEXT_CURRENT_PLAN_CHANGED")
    identity = bound.identity
    if (plan.deployment_id, plan.broker, plan.broker_account_id, plan.takeover_epoch) != (
            identity.deployment_id, identity.broker, identity.broker_account_id, identity.takeover_epoch):
        raise LiveOrderRefused("LIVE_CONTEXT_PLAN_SUBJECT_CHANGED")
    commands = _commands(conn, bound)
    wanted = tuple(command for command in commands if command.client_key == client_key)
    if (len(wanted) != 1 or wanted[0].state is not CommandState.SEND_PENDING
            or wanted[0].identity.plan_id != plan.plan_id):
        raise LiveOrderRefused("LIVE_CONTEXT_ORIGINAL_PENDING_COMMAND_REQUIRED")
    request = wanted[0]
    clock = now or (lambda: datetime.now(timezone.utc))
    started = _clock(clock)
    before = await broker.account_snapshot()
    observation = await broker.observe()
    after = await broker.account_snapshot()
    completed = _clock(clock)
    if (completed < started or type(before) is not BrokerAccountSnapshot
            or type(after) is not BrokerAccountSnapshot):
        raise LiveOrderRefused("LIVE_CONTEXT_CLOCK_OR_ACCOUNT_INVALID")
    if (not identity.matches_account(before.identity) or not identity.matches_account(after.identity)):
        raise LiveOrderRefused("LIVE_CONTEXT_ACCOUNT_CHANGED")
    if account_snapshot_sha256(before) != account_snapshot_sha256(after):
        raise LiveOrderDeferred("LIVE_CONTEXT_ACCOUNT_CHANGED_DURING_OBSERVATION")
    if _native_funding_shape(before.native_funding) != _native_funding_shape(after.native_funding):
        raise LiveOrderDeferred("LIVE_CONTEXT_FUNDING_CHANGED_DURING_OBSERVATION")
    _check_observation(observation, commands=commands, request=request, bound=bound, actions=actions)
    if (observation.started_at is None or observation.started_at < started
            or observation.observed_at > completed):
        raise LiveOrderDeferred("LIVE_CONTEXT_OBSERVATION_CLOCK_CHANGED")
    _require_writer(conn)
    _binding(conn, bound)
    close, reference_session, factor = None, None, "1"
    if request.side is Side.BUY:
        projection = target_reprojection.load_projection(conn, plan_id=plan.plan_id)
        if projection is None:
            raise LiveOrderRefused("LIVE_CONTEXT_PROTECTED_PROJECTION_REQUIRED")
        target_reprojection.assert_projection(conn, plan=plan, projection=projection,
                                             through_session=plan.effective_session)
        references, terms = protected_limits.submission_protection(conn, plan=plan, projection=projection)
        if terms.for_security(request.security_id) != request.order_terms:
            raise LiveOrderRefused("LIVE_CONTEXT_ORIGINAL_PROTECTED_TERMS_CHANGED")
        close = references.prices.get(request.security_id)
        if close is None:
            raise LiveOrderDeferred("LIVE_CONTEXT_PRIOR_CLOSE_UNAVAILABLE")
        reference_session = references.decision_session
        factor = references.unit_factors[request.security_id]
    return LiveOrderContext(effective_session=plan.effective_session, request=request,
        account=after, account_observed_at=started, positions=observation.positions,
        commitments=commands, reference_close=close, reference_session=reference_session,
        reference_unit_factor=factor,
        funding=load_live_funding_admission() if request.side is Side.BUY else None)


def load_owned_cancel_command(conn, *, binding, broker_order_id: str) -> Command:
    _require_writer(conn)
    bound = _binding(conn, binding)
    if type(broker_order_id) is not str or not broker_order_id:
        raise LiveOrderRefused("LIVE_CONTEXT_EXACT_CANCEL_ID_REQUIRED")
    with conn.cursor() as cur:
        cur.execute("SELECT client_key FROM sentinel_commands WHERE broker_order_id=%s LIMIT 2",
                    (broker_order_id,))
        keys = tuple(row[0] for row in cur.fetchall())
    if len(keys) != 1:
        raise LiveOrderRefused("LIVE_CONTEXT_EXACT_OWNED_CANCEL_REQUIRED")
    commands = journal.load_commands(conn, bound.identity, client_keys=keys)
    if (len(commands) != 1 or commands[0].broker_order_id != broker_order_id
            or commands[0].state not in IN_FLIGHT):
        raise LiveOrderRefused("LIVE_CONTEXT_CANCEL_COMMAND_CHANGED")
    return commands[0]
