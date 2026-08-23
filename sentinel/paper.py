"""Paper-only preparation and the separately authorized execution gateway.

Preparation may read the broker and write durable Sentinel state. It has no
broker mutation call. Execution loads the durable current plan itself, repeats
every authority check, and only then delegates order handling to the certified
executor.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

from sentinel import (
    binding as binding_mod,
    dual_plan_authority,
    identity as system_identity,
    informational_paper_mirror,
    schema,
    trial,
    trial_close,
    trial_fills,
)
from sentinel.authority import (
    AuthorityRefused,
    PAPER_OBSERVATION_ONLY,
    RolloutMode,
    load_rollout_state,
    require_observation_safety_authority,
)
from sentinel.config import DEFAULT_BASE_URL, assert_paper_url
from sentinel.controller.concordance import is_concordance_identity
from sentinel.controller.concordance_parent import load as load_concordance_parent
from sentinel.controller.frozen_rule import ControllerConfig, load as load_controller
from sentinel.controller.ldrc import (
    LDRCConfig, STRATEGY_ID as LDRC_STRATEGY_ID,
    STRATEGY_VERSION as LDRC_STRATEGY_VERSION,
)
from sentinel.controller.machine import Controller
from sentinel.core import catchup
from sentinel.core.decision import (
    DEFENSIVE_SECURITY_ID,
    build_execution_plan,
    publication_fingerprint,
    runtime_strategy_identity,
    shadow_target,
)
from sentinel.core.loader import (
    CausalMetadataUnavailable,
    load_causal_meta_history, load_meta, load_window)
from sentinel.core.production import (
    CONCORDANCE_WITNESS_PROSPECTIVE,
    SessionState,
    advance_and_persist,
    load_published_session,
    warm_session_state,
)
from sentinel.execution import broker_cash, executor, journal
from sentinel.execution import commands as execution_commands
from sentinel.execution import preopen_authority
from sentinel.execution import reconcile as reconciliation
from sentinel.execution.authority_gate import (
    build_fresh_execution_guard,
    require_current_authority,
)
from sentinel.execution.certification import require_certified
from sentinel.execution.commands import committed_quantity
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    ExecutionBroker,
    MalformedBrokerEvidence,
)
from sentinel.execution.guarded import (
    AutomationExecutionGrant,
    BrokerAuthorityRefused,
    BrokerOperation,
    GuardedExecutionBroker,
    ManualExecutionGrant,
    PaperPreparationGrant,
)
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import RuntimeState
from sentinel.execution.states import blocks_overlapping
from sentinel.execution import target_reprojection
from sentinel.feed import calendar, publication, readiness, store as feed_store

DEFENSIVE_SYMBOL = "BIL"
SIMPLIFIED_LDRC_STRATEGY_ID = "sentinel-concordance-simplified-ldrc"
SIMPLIFIED_LDRC_STRATEGY_VERSION = 3
ACCOUNT_ENDPOINT_LAG_GRACE = timedelta(seconds=120)
_ACCOUNT_ENDPOINT_LAG_SCHEMA = "sentinel.broker-account-lag/1"
_ACCOUNT_ENDPOINT_LAG_PREFIX = "broker-account-lag:v1:"


def _assert_concordance_witness_authority(
        state: SessionState, authorization_mode: str) -> None:
    """Prevent a prospective witness from inheriting historical authority."""
    if (is_concordance_identity(state.strategy_identity)
            and state.concordance_witness_origin
            == CONCORDANCE_WITNESS_PROSPECTIVE
            and authorization_mode != PAPER_OBSERVATION_ONLY):
        raise PaperActivationRefused(
            "prospectively formed Concordance witness state is authorized only "
            "for PAPER_OBSERVATION_ONLY; rebuild from a complete causal "
            "metadata timeline before using historically certified authority")


def _default_paper_strategy() -> tuple[ControllerConfig, dict[str, str]]:
    """Return the one paper-trial strategy: hardened parent + simplified LD-RC.

    The assertions are intentionally redundant with source identity. They make
    an accidental rollback to the older five-condition/legacy recovery model a
    startup refusal instead of a plausible but different trading strategy.
    """
    if (LDRC_STRATEGY_ID != SIMPLIFIED_LDRC_STRATEGY_ID
            or LDRC_STRATEGY_VERSION != SIMPLIFIED_LDRC_STRATEGY_VERSION):
        raise PaperActivationRefused(
            "paper runtime requires Simplified Concordance LD-RC v3")
    cfg = LDRCConfig()
    expected = (0.55, -0.10, -0.08, 0.00, 7, 0.11)
    actual = (
        cfg.divergence_ceiling, cfg.wc_drawdown_trigger,
        cfg.recent_r20_trigger, cfg.spy_r20_floor,
        cfg.recovery_sessions, cfg.spy_v_rebound,
    )
    if actual != expected:
        raise PaperActivationRefused(
            "Simplified LD-RC v3 constants differ from the retained strategy")
    controller = load_concordance_parent()
    identity = runtime_strategy_identity(controller, concordance=True)
    if (identity.get("allocation_overlay") != SIMPLIFIED_LDRC_STRATEGY_ID
            or identity.get("allocation_overlay_version")
            != str(SIMPLIFIED_LDRC_STRATEGY_VERSION)):
        raise PaperActivationRefused(
            "paper strategy identity does not name Simplified LD-RC v3")
    return controller, identity


class PaperActivationRefused(BrokerAuthorityRefused):
    """A preparation or execution authority check failed."""


class PaperRetryableRefused(PaperActivationRefused):
    """Temporary readiness or settlement evidence is not yet usable."""


class PreOpenShareUnitAuthorityUnavailable(PaperActivationRefused):
    """The exact next-open units needed for safe transport are unavailable."""


@dataclass(frozen=True)
class PaperAccountInspection:
    """One complete, read-only view of the named inherited paper account."""

    endpoint: str
    expected_account: str
    account: BrokerAccountSnapshot
    observation: BrokerObservation
    binding: Optional[binding_mod.AccountBinding]

    @property
    def approval_blockers(self) -> tuple[str, ...]:
        """Well-formed facts that make migration approval unsafe.

        These remain visible rather than raising: inspection is the place an
        operator needs to learn that the account is blocked or unsettled.
        Malformed evidence and identity uncertainty are refused before this
        object exists.
        """
        account = self.account
        blockers: list[str] = []
        if account.status.upper() != "ACTIVE":
            blockers.append(f"account_status:{account.status}")
        blockers.extend(
            name for name in (
                "trading_blocked", "account_blocked",
                "trade_suspended_by_user")
            if getattr(account, name))
        if account.multiplier != Decimal(1):
            blockers.append(f"cash_only_multiplier:{account.multiplier}")
        if account.equity <= 0:
            blockers.append(f"nonpositive_equity:{account.equity}")
        if account.cash < 0:
            blockers.append(f"negative_cash:{account.cash}")
        if account.buying_power < 0:
            blockers.append(f"negative_buying_power:{account.buying_power}")
        if abs(account.buying_power - account.cash) > Decimal("1.00"):
            relation = ("unsettled_buying_power" if account.buying_power
                        < account.cash else "margin_buying_power")
            blockers.append(
                f"{relation}:{account.buying_power}:cash:{account.cash}")
        if self.binding is not None:
            blockers.append(
                f"account_already_bound:{self.binding.ownership_state}")
        return tuple(blockers)

    def to_dict(self) -> dict:
        account = self.account
        positions = sorted(
            self.observation.positions,
            key=lambda position: (
                position.instrument.security_id,
                position.instrument.symbol,
                position.instrument.broker_id or ""))
        working_orders = sorted(
            (order for order in self.observation.orders if order.is_working),
            key=lambda order: (
                order.broker_order_id,
                order.client_key or ""))
        return {
            "inspection_only": True,
            "broker_mutations_permitted": False,
            "approval_ready": not self.approval_blockers,
            "approval_blockers": list(self.approval_blockers),
            "endpoint": self.endpoint,
            "expected_account": self.expected_account,
            "account": {
                "broker": account.identity.broker,
                "account_id": account.identity.account_id,
                "status": account.status,
                "trading_blocked": account.trading_blocked,
                "account_blocked": account.account_blocked,
                "trade_suspended_by_user": account.trade_suspended_by_user,
                "multiplier": str(account.multiplier),
                "equity": str(account.equity),
                "cash": str(account.cash),
                "buying_power": str(account.buying_power),
            },
            "binding_state": (
                self.binding.ownership_state if self.binding else "UNBOUND"),
            "binding_matches_account": (
                True if self.binding is not None else None),
            "binding": self.binding.to_dict() if self.binding else None,
            "observation_complete": True,
            "observed_at": self.observation.observed_at.isoformat(),
            "positions": [
                {
                    "security_id": position.instrument.security_id,
                    "symbol": position.instrument.symbol,
                    "broker_instrument_id": position.instrument.broker_id,
                    "quantity": str(position.quantity),
                }
                for position in positions
            ],
            "working_open_orders": [
                {
                    "broker_order_id": order.broker_order_id,
                    "client_key": order.client_key,
                    "security_id": order.instrument.security_id,
                    "symbol": order.instrument.symbol,
                    "broker_instrument_id": order.instrument.broker_id,
                    "side": order.side.value,
                    "state": order.state.value,
                    "quantity": str(order.quantity),
                    "filled_quantity": str(order.filled_quantity),
                    "remaining_quantity": str(order.remaining),
                    "submitted_at": (
                        order.submitted_at.isoformat()
                        if order.submitted_at is not None else None),
                }
                for order in working_orders
            ],
        }


@dataclass(frozen=True)
class PreparationResult:
    plan: ExecutionPlan
    sessions_replayed: int
    warmup_sessions: int
    state_fingerprint: str
    publication_version: int
    frontier: str
    reconciliation: object
    superseded_plans: int = 0

    def to_dict(self) -> dict:
        return {
            "dry_run": True,
            "broker_mutations_permitted": False,
            "sessions_replayed": self.sessions_replayed,
            "warmup_sessions": self.warmup_sessions,
            "frontier": self.frontier,
            "publication_version": self.publication_version,
            "state_fingerprint": self.state_fingerprint,
            "superseded_plans": self.superseded_plans,
            "plan": self.plan.to_dict(),
            "reconciliation": self.reconciliation.to_dict(),
        }


@dataclass(frozen=True)
class ExecutionResult:
    plan: ExecutionPlan
    preflight: object
    session: object

    @property
    def needs_attention(self) -> bool:
        terminal_bad = any(
            command.state.name in {"UNKNOWN", "REJECTED", "CANCELLED"}
            for command in self.session.submitted)
        return (self.session.runtime_state is not RuntimeState.RUNNING
                or bool(self.session.refused) or bool(self.session.deferred)
                or terminal_bad)

    def to_dict(self) -> dict:
        return {"paper_submission_authorized": not self.needs_attention,
                "operator_attention_required": self.needs_attention,
                "plan": self.plan.to_dict(),
                "preflight": self.preflight.to_dict(),
                "execution": self.session.to_dict()}


def _require_certified_paper_broker(broker: ExecutionBroker) -> None:
    """Accept only the two concrete adapters whose behavior is certified.

    Production receives :class:`AlpacaExecutionBroker`; tests receive the
    deterministic simulator. Treating every unknown implementation as the
    simulator would let an unlisted transport borrow a certification it never
    earned merely by choosing a different class name.
    """
    from sentinel.execution.alpaca import AlpacaExecutionBroker
    from sentinel.execution.simulator import SimulatedBroker
    from sentinel.guarded_administration import (
        GuardedAdministrativeExecutionBroker)

    if isinstance(broker, GuardedAdministrativeExecutionBroker):
        # This one explicit read-only wrapper validated its concrete adapter at
        # construction and exposes only a certification recheck, never its
        # transport object. Arbitrary duck-typed wrappers remain refused.
        broker.require_certified_adapter()
        return

    if isinstance(broker, AlpacaExecutionBroker):
        require_certified("alpaca")
        return
    if isinstance(broker, SimulatedBroker):
        require_certified("simulator")
        return
    raise PaperActivationRefused(
        f"unsupported execution broker {type(broker).__name__}; the paper "
        "activation path accepts only the certified Alpaca adapter (or the "
        "deterministic simulator in tests)")


def _inspection_account_or_refuse(
        snapshot: BrokerAccountSnapshot, expected_account: str) -> None:
    """Validate the inspection payload without turning status into authority.

    A blocked or inactive account is useful inspection evidence and is printed
    for the operator. Missing, non-typed, or non-finite fields are not evidence
    at all and therefore refuse the checkpoint.
    """
    if not expected_account:
        raise PaperActivationRefused(
            "paper-account inspection requires the exact expected account id")
    identity = snapshot.identity
    if not identity.broker or not identity.account_id:
        raise PaperActivationRefused(
            "paper-account inspection received a malformed account identity")
    if identity.account_id != expected_account:
        raise PaperActivationRefused(
            f"connected to paper account {identity.account_id}, expected "
            f"{expected_account}")
    values = {
        "equity": snapshot.equity,
        "cash": snapshot.cash,
        "buying_power": snapshot.buying_power,
        "multiplier": snapshot.multiplier,
    }
    malformed_values = [
        name for name, value in values.items()
        if not isinstance(value, Decimal) or not value.is_finite()]
    if malformed_values:
        raise PaperActivationRefused(
            "paper-account inspection received malformed Decimal fields: "
            + ", ".join(malformed_values))
    if not isinstance(snapshot.status, str) or not snapshot.status.strip():
        raise PaperActivationRefused(
            "paper-account inspection received a missing account status")
    flags = (
        "trading_blocked", "account_blocked", "trade_suspended_by_user")
    malformed_flags = [
        name for name in flags if type(getattr(snapshot, name)) is not bool]
    if malformed_flags:
        raise PaperActivationRefused(
            "paper-account inspection received non-boolean block flags: "
            + ", ".join(malformed_flags))


async def inspect_paper_account(*, conn, broker: ExecutionBroker,
                                base_url: str,
                                expected_account: str
                                ) -> PaperAccountInspection:
    """Read the exact inherited book without acquiring mutation authority."""
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)

    account = await broker.account_snapshot()
    _inspection_account_or_refuse(account, expected_account)
    observation = await broker.observe()
    observation.require_complete("paper-account inspection")
    if observation.observed_at.tzinfo is None:
        raise PaperActivationRefused(
            "paper-account inspection received a naive observation timestamp")

    # Inspection is deliberately available before the Sentinel behavior schema
    # has ever been installed.  Asking PostgreSQL whether the relation exists
    # is a read; calling ``schema.ensure_schema`` here would turn the mandatory
    # pre-migration checkpoint into a hidden state-changing bootstrap command.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('public.sentinel_account_binding')")
        binding_relation = cur.fetchone()[0]
    binding = (binding_mod.load(conn)
               if binding_relation is not None else None)
    if binding is not None:
        if not binding.is_owned:
            raise PaperActivationRefused(
                f"canonical binding has unsupported ownership state "
                f"{binding.ownership_state!r}")
        if not binding.identity.matches_account(account.identity):
            raise PaperActivationRefused(
                f"canonical binding names {binding.broker}/"
                f"{binding.broker_account_id}, but the broker reports "
                f"{account.identity.broker}/{account.identity.account_id}")

    return PaperAccountInspection(
        endpoint=base_url, expected_account=expected_account,
        account=account, observation=observation, binding=binding)


def _hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _readiness_or_refuse(conn, *, now_et=None):
    """Recompute readiness for the named operational session.

    The exchange-local clock, not ``--through``, decides what data is owed.
    Supplying a future decision date must not make a future-dated corpus look
    current. ``now_et`` exists only as a deterministic test seam.
    """
    if now_et is None:
        now_et = datetime.now(ZoneInfo(calendar.EXCHANGE_TZ))
    report = readiness.check_readiness(conn, today=now_et.isoformat())
    if report.ready:
        return report
    detail = "; ".join(f"{c.name}: {c.detail}" for c in report.failures)
    raise PaperRetryableRefused(f"corpus readiness failed: {detail}")


def _execution_observation_time(value: date | datetime | None) -> datetime:
    """Resolve the real clock, while preserving the date-only test seam.

    Production never supplies ``value`` and therefore always uses the actual ET
    instant. Existing deterministic tests pass a date; resolve that date to its
    certified XNYS open rather than treating midnight as executable. A datetime
    is the exact-time seam used by open/close and half-day falsifiers.
    """
    tz = ZoneInfo(calendar.EXCHANGE_TZ)
    if value is None:
        return datetime.now(tz)
    if isinstance(value, datetime):
        return (value.replace(tzinfo=tz) if value.tzinfo is None
                else value.astimezone(tz))
    opened, _closed = calendar.session_window(value)
    return opened


def _execution_window_or_refuse(session: date, now_et: datetime) -> None:
    """Require the actual instant to lie inside the named XNYS session."""
    opened, closed = calendar.session_window(session)
    if not (opened <= now_et < closed):
        raise PaperRetryableRefused(
            f"paper execution time {now_et.isoformat()} is outside the "
            f"certified XNYS execution window for {session}: "
            f"[{opened.isoformat()}, {closed.isoformat()}). The gateway will "
            "not queue a DAY order before the open or after the close.")


def _clean_or_refuse(result, *, purpose: str) -> BrokerObservation:
    observation = result.observation
    if (result.runtime_state is not RuntimeState.RUNNING or not result.clean
            or observation is None or not observation.is_complete):
        error = (PaperRetryableRefused
                 if (result.runtime_state in {
                     RuntimeState.BROKER_DEGRADED, RuntimeState.RECONCILING}
                     or (observation is not None
                         and not observation.is_complete))
                 else PaperActivationRefused)
        raise error(
            f"{purpose} requires COMPLETE, RUNNING, clean reconciliation; "
            f"got {result.runtime_state.value}: {result.detail}")
    return observation


def _dual_mutation_observation_or_refuse(result) -> BrokerObservation:
    """Dual PAPER never mutates an unexplained or externally replaced book."""
    observation = result.observation
    # Replacement is a permanent authority divergence even when generic
    # reconciliation quite reasonably labels changed quantity/id as an amber
    # in-flight book.  Classify it before the clean/retry branch so the durable
    # automation cycle becomes BLOCKED instead of retrying forever.
    replaced = sorted(
        order.broker_order_id
        for order in (() if observation is None else observation.orders)
        if getattr(order, "external_replacement", False))
    if replaced:
        raise PaperActivationRefused(
            "informational dual PAPER observed an externally replaced or "
            "pending-replace order; all broker mutations are blocked")
    return _clean_or_refuse(
        result, purpose="informational dual PAPER mutation")


def _account_evidence_is_quiescent(
        conn, *, deployment, observation: BrokerObservation) -> bool:
    """Only a settled book can bind a later account snapshot to this read."""
    if observation is None or not observation.is_complete:
        return False
    if any(order.is_working for order in observation.orders):
        return False
    return not journal.in_flight_commands(conn, deployment)


def _observation_economics(observation: BrokerObservation) -> dict:
    """Canonical broker book facts, excluding transport timestamps."""
    positions = [{
        "security_id": item.instrument.security_id,
        "broker_id": item.instrument.broker_id,
        "quantity": str(item.quantity),
    } for item in observation.positions]
    positions.sort(key=lambda item: (
        item["security_id"], item["broker_id"] or "", item["quantity"]))
    orders = [{
        "broker_order_id": item.broker_order_id,
        "client_key": item.client_key,
        "security_id": item.instrument.security_id,
        "broker_id": item.instrument.broker_id,
        "side": item.side.value,
        "state": item.state.value,
        "quantity": str(item.quantity),
        "filled_quantity": str(item.filled_quantity),
        "filled_average_price": (
            None if item.filled_average_price is None
            else str(item.filled_average_price)),
        "external_replacement": bool(item.external_replacement),
    } for item in observation.orders if item.is_working]
    orders.sort(key=lambda item: (
        item["broker_order_id"], item["client_key"] or ""))
    return {
        "completeness": observation.completeness.value,
        "account": (
            None if observation.account_identity is None else {
                "broker": observation.account_identity.broker,
                "account_id": observation.account_identity.account_id,
            }),
        "positions": positions,
        "orders": orders,
    }


def _account_economics(snapshot: BrokerAccountSnapshot) -> dict:
    """Facts that must remain stable around a settled cash observation.

    Equity is mark-to-market and can tick with no broker activity. Buying power
    can be recomputed from those marks as well; each endpoint payload is still
    validated as cash-only by ``_account_or_refuse``, but neither value is a
    stable cross-request identity. Cash and the account's permission/status
    fields are the relevant evidence for cash certification.
    """
    return {
        "broker": snapshot.identity.broker,
        "account_id": snapshot.identity.account_id,
        "cash": str(snapshot.cash),
        "multiplier": (None if snapshot.multiplier is None
                       else str(snapshot.multiplier)),
        "status": snapshot.status,
        "trading_blocked": snapshot.trading_blocked,
        "account_blocked": snapshot.account_blocked,
        "trade_suspended_by_user": snapshot.trade_suspended_by_user,
    }


def _account_endpoint_lag_is_live(
        conn, *, plan: ExecutionPlan, deployment,
        account: BrokerAccountSnapshot, expected_cash: Decimal,
        observation: BrokerObservation, observed_at: datetime) -> bool:
    """Create/read one non-renewable grace for a stable cash mismatch."""
    if observed_at.tzinfo is None:
        raise PaperActivationRefused(
            "account endpoint evidence time must be timezone-aware")
    durable_commands = [{
        "client_key": command.client_key,
        "security_id": command.security_id,
        "broker_order_id": command.broker_order_id,
        "side": command.side.value,
        "state": command.state.value,
        "quantity": str(command.quantity),
        "filled_quantity": str(command.filled_quantity),
        "filled_average_price": (
            None if command.filled_average_price is None
            else str(command.filled_average_price)),
    } for command in journal.load_commands(
        conn, deployment, plan_id=plan.plan_id)]
    durable_commands.sort(key=lambda item: item["client_key"])
    observation_value = _observation_economics(observation)
    settled_book_identity = {
        # Terminal order rows may age out of the next recovery window after the
        # first retry. The durable command journal is their stable authority;
        # working orders cannot reach this quiescent evidence path at all.
        "durable_commands": durable_commands,
        "positions": observation_value["positions"],
        "account": observation_value["account"],
    }
    identity = {
        "schema": _ACCOUNT_ENDPOINT_LAG_SCHEMA,
        "deployment": deployment.to_dict(),
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.fingerprint(),
        "expected_cash": str(expected_cash),
        "settled_book_sha256": _hash(settled_book_identity),
    }
    cursor = _ACCOUNT_ENDPOINT_LAG_PREFIX + _hash(identity)
    candidate = dict(
        identity, first_observed_cash=str(account.cash),
        first_observed_at=observed_at.isoformat())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO NOTHING",
            (cursor, observed_at.date(), json.dumps(
                candidate, sort_keys=True, separators=(",", ":"))))
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (cursor,))
        row = cur.fetchone()
    if row is None:
        raise PaperActivationRefused(
            "account endpoint-lag evidence was not retained")
    stored = row[0] if isinstance(row[0], Mapping) else json.loads(str(row[0]))
    if (set(stored) != set(identity) | {
            "first_observed_cash", "first_observed_at"}
            or any(stored.get(key) != value
                   for key, value in identity.items())):
        raise PaperActivationRefused(
            "account endpoint-lag evidence identity changed")
    try:
        first = datetime.fromisoformat(str(stored["first_observed_at"]))
        first_cash = Decimal(str(stored["first_observed_cash"]))
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise PaperActivationRefused(
            "account endpoint-lag evidence time is malformed") from exc
    if first.tzinfo is None or not first_cash.is_finite():
        raise PaperActivationRefused(
            "account endpoint-lag evidence value is invalid")
    # The surrounding writer lock rolls back on the retryable refusal this
    # function intentionally triggers.  Commit the immutable first-seen clock
    # now so a restart/retry cannot manufacture a fresh 120-second grace
    # forever.  Reconciliation writes preceding this point are also positive
    # broker evidence and are safe (and necessary) to retain.
    conn.commit()
    age = observed_at - first
    return timedelta(0) <= age <= ACCOUNT_ENDPOINT_LAG_GRACE


async def _settled_account_evidence_bracket(
        *, conn, broker: ExecutionBroker, binding, expected_account: str,
        deployment, initial_result, actions, dual_mode: bool, clock):
    """Bracket a second complete book read with stable account snapshots."""
    initial_observation = initial_result.observation
    if not _account_evidence_is_quiescent(
            conn, deployment=deployment, observation=initial_observation):
        raise PaperRetryableRefused(
            "account evidence remains pending while broker work is in flight")
    started_at = clock()
    before = await broker.account_snapshot()
    _account_or_refuse(before, binding, expected_account)
    confirmation = await reconciliation.reconcile(
        broker=broker, conn=conn, binding=None,
        deployment=deployment, actions=actions)
    confirmed_observation = (
        _dual_mutation_observation_or_refuse(confirmation)
        if dual_mode else
        _clean_or_refuse(
            confirmation, purpose="settled account evidence bracket"))
    if not _account_evidence_is_quiescent(
            conn, deployment=deployment,
            observation=confirmed_observation):
        raise PaperRetryableRefused(
            "account evidence bracket observed broker work in flight")
    after = await broker.account_snapshot()
    observed_at = clock()
    _account_or_refuse(after, binding, expected_account)
    if (_observation_economics(initial_observation)
            != _observation_economics(confirmed_observation)):
        raise PaperRetryableRefused(
            "order/position endpoints changed inside the account evidence "
            "bracket; re-observation is required")
    if _account_economics(before) != _account_economics(after):
        raise PaperRetryableRefused(
            "account endpoint changed inside the order/position evidence "
            "bracket; re-observation is required")
    activity = await _broker_cash_state_or_refuse(
        conn, broker=broker, binding=binding, through=observed_at)
    return confirmation, after, activity, started_at, observed_at


def _account_or_refuse(snapshot: BrokerAccountSnapshot, binding,
                       expected_account: Optional[str]) -> None:
    if not binding.identity.matches_account(snapshot.identity):
        raise PaperActivationRefused(
            f"broker identity {snapshot.identity.broker}/"
            f"{snapshot.identity.account_id} does not match binding "
            f"{binding.broker}/{binding.broker_account_id}")
    if expected_account and snapshot.identity.account_id != expected_account:
        raise PaperActivationRefused(
            f"connected to paper account {snapshot.identity.account_id}, "
            f"expected {expected_account}")
    if (not snapshot.equity.is_finite() or snapshot.equity <= 0
            or not snapshot.cash.is_finite() or snapshot.cash < 0
            or snapshot.buying_power is None
            or not snapshot.buying_power.is_finite()
            or snapshot.buying_power < 0
            or snapshot.multiplier is None
            or not snapshot.multiplier.is_finite()):
        raise PaperActivationRefused(
            f"account sizing facts are unusable: equity={snapshot.equity}, "
            f"cash={snapshot.cash}, buying_power={snapshot.buying_power}, "
            f"multiplier={snapshot.multiplier}")
    if snapshot.multiplier != Decimal(1):
        raise PaperActivationRefused(
            f"paper account multiplier is {snapshot.multiplier}, not 1. "
            "Sentinel requires a cash-only paper account and will not rely on "
            "margin to make a DAY market order affordable")
    if snapshot.status.upper() != "ACTIVE":
        raise PaperRetryableRefused(
            f"paper account status is {snapshot.status!r}, not ACTIVE")
    blocked = [
        name for name in (
            "trading_blocked", "account_blocked", "trade_suspended_by_user")
        if getattr(snapshot, name)
    ]
    if blocked:
        raise PaperRetryableRefused(
            "paper account is not available for submission: "
            + ", ".join(blocked))
    if abs(snapshot.buying_power - snapshot.cash) > Decimal("1.00"):
        error = (PaperRetryableRefused
                 if snapshot.buying_power < snapshot.cash
                 else PaperActivationRefused)
        raise error(
            f"paper account buying power {snapshot.buying_power} does not "
            f"match cash {snapshot.cash}. Lower buying power is unsettled; "
            "higher buying power exposes margin. Increases wait for cash-only "
            "settlement")


def _recovery_account_identity_or_refuse(
        snapshot: BrokerAccountSnapshot, binding,
        expected_account: str) -> None:
    """Prove identity without applying submission-time account economics."""
    if not binding.identity.matches_account(snapshot.identity):
        raise PaperActivationRefused(
            f"broker identity {snapshot.identity.broker}/"
            f"{snapshot.identity.account_id} does not match binding "
            f"{binding.broker}/{binding.broker_account_id}")
    if snapshot.identity.account_id != expected_account:
        raise PaperActivationRefused(
            f"connected to paper account {snapshot.identity.account_id}, "
            f"expected {expected_account}")


async def _broker_cash_state_or_refuse(
        conn, *, broker: ExecutionBroker, binding,
        through: datetime) -> broker_cash.CashActivityState | None:
    """Ingest one complete broker-cash interval under the caller's writer lock."""
    if not getattr(broker, "supports_account_cash_activities", False):
        return None
    try:
        return await broker_cash.ingest_account_cash(
            conn, broker_adapter=broker, broker=binding.broker,
            account_id=binding.broker_account_id, through=through)
    except BrokerAuthorityRefused:
        raise
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise PaperActivationRefused(
            f"broker cash authority is inconsistent: {exc}") from exc
    except Exception as exc:                                  # noqa: BLE001
        raise PaperRetryableRefused(
            "broker cash activity evidence is temporarily unavailable: "
            f"{type(exc).__name__}: {exc}") from exc


async def _record_due_close_nav_or_refuse(
        conn, *, broker: ExecutionBroker, deployment,
        session: date) -> dict:
    """Fetch and retain one certified historical close before supersession."""
    if not getattr(broker, "supports_account_close_valuation", False):
        raise PaperRetryableRefused(
            "broker historical close valuation is not a certified capability; "
            "the succeeded cycle remains pending and no successor plan will "
            "be adopted")
    try:
        valuation = await broker.account_close_valuation(session=session)
    except BrokerAuthorityRefused:
        raise
    except MalformedBrokerEvidence as exc:
        raise PaperActivationRefused(
            "broker historical close valuation returned malformed or "
            f"contradictory evidence: {exc}") from exc
    except Exception as exc:                                  # noqa: BLE001
        raise PaperRetryableRefused(
            "broker historical close valuation is temporarily unavailable: "
            f"{type(exc).__name__}: {exc}") from exc
    try:
        return trial_close.record_close_nav_evidence(
            conn, deployment=deployment, valuation=valuation)
    except trial_close.TrialCloseNavRefused as exc:
        raise PaperActivationRefused(
            "broker historical close valuation failed its immutable "
            f"acceptance contract: {exc}") from exc


async def _record_due_fill_interval_or_refuse(
        conn, *, broker: ExecutionBroker, deployment, plan: ExecutionPlan,
        session: date, required_through: datetime) -> dict:
    """Retain the complete plan-baseline-to-paper-time account fill ledger."""
    if not getattr(broker, "supports_account_fill_interval_evidence", False):
        raise PaperRetryableRefused(
            "broker account-wide fill interval is not a certified capability; "
            "the succeeded cycle remains pending and no successor plan will "
            "be adopted")

    try:
        baseline = broker_cash.load_plan_baseline(conn, plan_id=plan.plan_id)
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise PaperActivationRefused(
            f"authoritative plan cash baseline is invalid: {exc}") from exc
    if baseline is None:
        raise PaperActivationRefused(
            "the due cycle has no authoritative plan cash baseline from which "
            "to begin account-wide fill evidence")
    if (baseline.plan_id != plan.plan_id
            or baseline.broker != plan.broker
            or baseline.account_id != plan.broker_account_id
            or baseline.broker != deployment.broker
            or baseline.account_id != deployment.broker_account_id
            or baseline.decision_session != plan.decision_session
            or not baseline.activity_identity_authoritative):
        raise PaperActivationRefused(
            "the due cycle plan cash baseline is not authoritative for this "
            "plan, decision session, deployment, and broker account")
    interval_start = baseline.processed_through
    if (not isinstance(interval_start, datetime)
            or interval_start.tzinfo is None
            or interval_start.utcoffset() is None
            or not isinstance(required_through, datetime)
            or required_through.tzinfo is None
            or required_through.utcoffset() is None):
        raise PaperActivationRefused(
            "the plan cash baseline and required fill boundary must be "
            "timezone-aware timestamps")

    try:
        interval = await broker.account_fill_interval_evidence(
            session=session, interval_start=interval_start)
    except BrokerAuthorityRefused:
        raise
    except MalformedBrokerEvidence as exc:
        raise PaperActivationRefused(
            "broker account-wide fill interval returned malformed or "
            f"contradictory evidence: {exc}") from exc
    except Exception as exc:                                  # noqa: BLE001
        raise PaperRetryableRefused(
            "broker account-wide fill interval is temporarily unavailable: "
            f"{type(exc).__name__}: {exc}") from exc

    # Build before writing so a provider that ignored the requested lower bound,
    # returned an incomplete ledger, or stopped before the paper-time account /
    # reconciliation observations cannot poison the immutable session cursor.
    try:
        candidate = trial_fills.build_fill_interval_evidence(
            deployment=deployment, plan_id=plan.plan_id, interval=interval)
        accepted_start = datetime.fromisoformat(candidate["interval_start"])
        accepted_through = datetime.fromisoformat(
            candidate["processed_through"])
        if accepted_start != interval_start:
            raise trial_fills.TrialFillIntervalRefused(
                "account fill interval does not begin at the authoritative "
                "plan cash baseline")
        if accepted_through < required_through:
            raise trial_fills.TrialFillIntervalRefused(
                "account fill interval does not cover the paper-time account "
                "and reconciliation observations")
    except Exception as exc:                                  # noqa: BLE001
        raise PaperActivationRefused(
            "broker account-wide fill interval failed its accepted evidence "
            f"contract: {exc}") from exc

    try:
        return trial_fills.record_fill_interval_evidence(
            conn, deployment=deployment, plan_id=plan.plan_id,
            interval=interval)
    except trial_fills.TrialFillIntervalRefused as exc:
        raise PaperActivationRefused(
            "broker account-wide fill interval failed its immutable "
            f"acceptance contract: {exc}") from exc


async def _finalize_due_succeeded_cycle_or_refuse(
        conn, *, broker: ExecutionBroker, deployment, plan: ExecutionPlan,
        reconciliation, account: BrokerAccountSnapshot,
        activity_state: broker_cash.CashActivityState | None,
        observation_started_at: datetime, observed_at: datetime,
        target_actions, observation_target_actions, clock) -> dict | None:
    """Finalize any succeeded cycle before its plan can be superseded.

    This gate deliberately has no automation-grant input.  The durable cycle,
    rather than the identity of today's caller, creates the verification debt.
    Every historical coordinate is the old plan's effective session; a delayed
    preparation may observe the account later, but cannot relabel that evidence
    as belonging to the newer requested decision session.
    """
    session = plan.effective_session
    cycle_id = trial.due_succeeded_cycle_id(
        conn, plan_id=plan.plan_id, effective_session=session)
    if cycle_id is None:
        return None
    if reconciliation.observation_id is None:
        raise PaperActivationRefused(
            "a succeeded cycle is due for finalization, but the clean "
            "reconciliation has no durable observation identity")

    try:
        cash_baseline = broker_cash.load_plan_baseline(
            conn, plan_id=plan.plan_id)
    except broker_cash.BrokerCashAuthorityRefused as exc:
        raise PaperActivationRefused(
            f"the due cycle cash baseline is invalid: {exc}") from exc
    if (cash_baseline is None
            or cash_baseline.plan_id != plan.plan_id
            or cash_baseline.broker != plan.broker
            or cash_baseline.account_id != plan.broker_account_id
            or cash_baseline.broker != deployment.broker
            or cash_baseline.account_id != deployment.broker_account_id
            or cash_baseline.decision_session != plan.decision_session
            or not cash_baseline.activity_identity_authoritative):
        raise PaperActivationRefused(
            "the due cycle has no authoritative plan-bound cash baseline")
    if not cash_baseline.close_cash_finality_authoritative:
        # Source availability is not an economic red verdict. Keep the prior
        # success due until a reviewed fixed interval/finality contract exists;
        # otherwise this transient capability gap would be frozen forever and
        # the successor plan would poison the cumulative chain.
        raise PaperRetryableRefused(
            "the due cycle cash source has no accepted close-interval "
            "finality or publication watermark; the succeeded cycle remains "
            "pending and no successor plan will be adopted")

    try:
        target_projection = target_reprojection.load_projection(
            conn, plan_id=plan.plan_id)
        if target_projection is None:
            raise target_reprojection.TargetProjectionRefused(
                "the succeeded plan has no durable target projection")
        target_reprojection.assert_projection(
            conn, plan=plan, projection=target_projection,
            through_session=plan.effective_session)
        current_target_actions = _target_action_multipliers(
            plan, target_actions)
        if current_target_actions != dict(
                target_projection.action_multipliers):
            raise target_reprojection.TargetProjectionRefused(
                "current close action authority differs from the target "
                "projection used by execution")
        post_projection_actions = _post_projection_action_multipliers(
            target_projection, observation_target_actions)
    except target_reprojection.TargetProjectionRefused as exc:
        raise PaperActivationRefused(
            f"the due cycle target projection is invalid: {exc}") from exc

    # A later live account snapshot cannot stand in for the official close.
    # Retain both account-wide historical sources before account evidence or a
    # verdict is frozen, and before the caller may adopt a successor plan.
    await _record_due_close_nav_or_refuse(
        conn, broker=broker, deployment=deployment, session=session)
    await _record_due_fill_interval_or_refuse(
        conn, broker=broker, deployment=deployment, plan=plan,
        session=session,
        required_through=max(
            observed_at, reconciliation.observation.observed_at))
    trial.record_account_evidence(
        conn,
        session=session,
        observation_id=reconciliation.observation_id,
        observation_started_at=observation_started_at,
        observed_at=observed_at,
        snapshot=account,
        deployment=deployment,
        reconciliation=reconciliation,
        activity_state=activity_state,
        plan=plan,
        target_projection=target_projection,
        observation_post_projection_actions=post_projection_actions,
    )
    return trial.record_cycle_verification(
        conn,
        cycle_id=cycle_id,
        observation_id=reconciliation.observation_id,
        # Verification must be causally later than the awaited historical
        # source reads.  Earlier broker response brackets remain evidence only.
        now=clock(),
    )


def _cash_authority_or_refuse(
        conn, *, plan: ExecutionPlan, deployment,
        account: BrokerAccountSnapshot, observation: BrokerObservation,
        activity_state: broker_cash.CashActivityState | None = None,
        permit_new_activity: bool = False,
        endpoint_lag_observed_at: datetime | None = None) -> None:
    """Reconcile immutable plan cash to fills plus durable broker activities.

    The account balance is never its own explanation.  Native Account Activity
    rows explain cash movement; the immutable plan records which cumulative
    activity total already existed when it was sized.  A later recognized cash
    event may authorize the *next* decision to use the fresh balance, but never
    rewrites a same-session plan or an execution already in flight.
    """
    expected_without_activity = plan.account_cash
    for command in journal.load_commands(
            conn, deployment, plan_id=plan.plan_id):
        if command.filled_quantity == 0:
            continue
        if command.filled_average_price is None:
            raise PaperActivationRefused(
                f"cannot reconcile account cash for filled command "
                f"{command.client_key}: its durable broker fill has no "
                "average price")
        notional = command.filled_quantity * command.filled_average_price
        expected_without_activity += (
            notional if command.side.value == "SELL" else -notional)

    activity_delta = Decimal(0)
    activity_identity_changed = False
    if activity_state is not None:
        if (activity_state.broker != plan.broker
                or activity_state.account_id != plan.broker_account_id):
            raise PaperActivationRefused(
                "broker cash activity state belongs to another account")
        baseline = broker_cash.load_plan_baseline(
            conn, plan_id=plan.plan_id)
        if baseline is None:
            # Never stamp current activity history retroactively onto an old
            # immutable plan. Offsetting post-plan events can leave cash
            # numerically unchanged while changing the native event set, so a
            # current equality cannot reconstruct the plan-time boundary.
            raise PaperActivationRefused(
                f"plan {plan.plan_id} has no immutable broker cash baseline. "
                "It cannot be backfilled from current cash or activity state; "
                "resolve the legacy plan explicitly and prepare a fresh plan")
        if (baseline.activity_identity_authoritative
                and activity_state.activity_identity_scheme
                != baseline.activity_identity_scheme):
            raise PaperActivationRefused(
                "broker cash activity state does not carry the same accepted "
                "activity identity scheme as the authoritative plan baseline")
        activity_delta = activity_state.balance_total - baseline.balance_total
        if not baseline.activity_identity_authoritative:
            if not permit_new_activity:
                raise PaperActivationRefused(
                    f"plan {plan.plan_id} has a legacy cash baseline without "
                    "native activity-set identity; execution is refused until "
                    "preparation adopts a fresh plan")
            activity_identity_changed = True
        else:
            activity_identity_changed = (
                activity_state.last_activity_id != baseline.last_activity_id)

    expected = expected_without_activity + activity_delta
    if abs(account.cash - expected) > Decimal("1.00"):
        if (endpoint_lag_observed_at is not None
                and _account_endpoint_lag_is_live(
                    conn, plan=plan, deployment=deployment,
                    account=account, expected_cash=expected,
                    observation=observation,
                    observed_at=endpoint_lag_observed_at)):
            raise PaperRetryableRefused(
                "account cash endpoint is not yet coherent with the stable "
                "order/position bracket; no mutation is permitted during the "
                f"bounded {int(ACCOUNT_ENDPOINT_LAG_GRACE.total_seconds())}s "
                "re-observation window")
        raise PaperActivationRefused(
            f"fresh account cash {account.cash} is not explained by plan "
            f"baseline {plan.account_cash}, durable fills and broker-native "
            f"cash activities (expected {expected}). Cash movement is never "
            "inferred")
    if (activity_delta != 0 or activity_identity_changed) \
            and not permit_new_activity:
        raise PaperActivationRefused(
            "broker-native cash activity changed after plan "
            f"{plan.plan_id} was prepared (net={activity_delta}, "
            f"last_activity_id={activity_state.last_activity_id!r}). The "
            "event set is durably explained, but this immutable plan will not "
            "be re-sized or netted in place; prepare the next closed decision "
            "session")


def _load_marks_and_tickers(conn, state: SessionState, session: str
                            ) -> tuple[dict, dict]:
    target = shadow_target(state)
    security_ids = sorted(target.shares)
    tickers = dict(target.tickers)
    marks: dict[str, Decimal] = {}
    visible = publication.visible_predicate("b")
    with conn.cursor() as cur:
        if security_ids:
            cur.execute(
                "SELECT security_id,ticker,close_unadjusted FROM sentinel_bars b"
                " WHERE session=%s AND security_id=ANY(%s) AND " + visible,
                (session, security_ids))
            for security_id, ticker, close in cur.fetchall():
                sid = str(security_id)
                tickers[sid] = str(ticker)
                if close is not None:
                    marks[sid] = Decimal(str(close))
        defensive_visible = publication.visible_predicate("d")
        cur.execute(
            "SELECT security_id,close_unadjusted FROM sentinel_defensive_bars d"
            " WHERE session=%s AND security_id=%s AND ticker=%s AND "
            + defensive_visible,
            (session, DEFENSIVE_SECURITY_ID, DEFENSIVE_SYMBOL))
        defensive = cur.fetchall()
    if defensive and defensive[0][1] is not None:
        marks[DEFENSIVE_SECURITY_ID] = Decimal(str(defensive[0][1]))
    tickers[DEFENSIVE_SECURITY_ID] = DEFENSIVE_SYMBOL
    return marks, tickers


def _missed_sessions(cursor: Optional[date], through: date) -> list[str]:
    if cursor is None:
        return [through.isoformat()]
    if cursor > through:
        raise PaperActivationRefused(
            f"durable cursor {cursor} is ahead of requested session {through}")
    start = cursor + timedelta(days=1)
    return calendar.sessions_in_range(start, through) if start <= through else []


def _fresh_warmed_state(conn, *, through: str, count: int,
                        account: BrokerAccountSnapshot,
                        controller_config: ControllerConfig,
                        strategy_identity: Mapping,
                        publication_version: int,
                        authorization_mode: str = "HISTORICALLY_CERTIFIED",
                        ) -> SessionState:
    sessions = calendar.previous_sessions(through, count + 1)
    if len(sessions) != count + 1 or sessions[-1] != through:
        raise PaperActivationRefused(
            f"fresh start needs {count} XNYS sessions strictly before {through}; "
            f"the calendar supplied {max(0, len(sessions) - 1)}")
    warm = sessions[:-1]
    window = load_window(conn, start=warm[0], end=warm[-1])
    if window.sessions != warm:
        missing = sorted(set(warm) - set(window.sessions))
        raise PaperActivationRefused(
            f"the pinned warm-up window is incomplete: {missing[:8]}")
    prospective_witness = False
    if is_concordance_identity(strategy_identity):
        try:
            window.metadata_timeline = load_causal_meta_history(
                conn, sessions=warm)
        except CausalMetadataUnavailable as exc:
            if authorization_mode != PAPER_OBSERVATION_ONLY:
                raise PaperActivationRefused(
                    "fresh Concordance activation requires session-effective "
                    "TICKERS metadata for every historical witness close") from exc
            # The signed observation mode makes no historical causality claim.
            # Prime price features only and begin the zero-capital witness on
            # the first current decision close; never backdate today's TICKERS
            # snapshot to manufacture r20/r40 readiness.
            prospective_witness = True
    starting_cash = float(account.equity)
    if not math.isfinite(starting_cash):
        raise PaperActivationRefused("account equity cannot be represented by Wealth Core")
    state = SessionState.fresh(
        starting_cash=starting_cash, controller=Controller(controller_config),
        strategy_identity=strategy_identity)
    return warm_session_state(
        state, window, publication_version=publication_version,
        prospective_concordance_witness=prospective_witness)


def _assert_deterministic_plan_id(plan: ExecutionPlan) -> None:
    """Prove the durable handle still names the economics stored beside it."""
    expected = f"sentinel-{plan.fingerprint()}"
    if plan.plan_id != expected:
        raise PaperActivationRefused(
            f"durable plan id {plan.plan_id!r} does not match its deterministic "
            f"economic identity {expected!r}; the stored plan is corrupt")


def _fresh_connection_factory(conn):
    """Reuse the credential-preserving, target-pinned fresh DB connection path."""
    from sentinel.guarded_administration import fresh_connection_factory

    try:
        return fresh_connection_factory(conn)
    except AuthorityRefused as exc:
        raise PaperActivationRefused(
            "paper broker authority could not construct a fresh PostgreSQL "
            "connection from the active target") from exc


def _validate_automation_grant(conn, grant: AutomationExecutionGrant):
    from sentinel.automation import store as automation_store
    from sentinel.automation.model import CycleState, LeaderPermit

    control = automation_store.load_control(conn)
    if not control.enabled or control.kill_switch_engaged:
        raise PaperActivationRefused(
            "automation is disabled or its kill switch is engaged")
    bound = control.binding
    if bound is None:
        raise PaperActivationRefused("automation control has no durable binding")
    expected = (
        grant.broker_account_id, grant.takeover_epoch,
        grant.rollout_mode, grant.rollout_version,
        grant.certificate_sha256, grant.control_generation,
    )
    actual = (
        bound.broker_account_id, bound.takeover_epoch,
        bound.rollout_mode, bound.rollout_version,
        bound.certificate_sha256, control.generation,
    )
    if actual != expected:
        raise PaperActivationRefused(
            "automation grant does not match durable control authority")
    placeholder = datetime.now(ZoneInfo("UTC"))
    permit = LeaderPermit(
        holder_id=grant.holder_id, fence_token=grant.fence_token,
        control_generation=grant.control_generation,
        acquired_at=placeholder, expires_at=placeholder)
    automation_store.require_leader(conn, permit)
    cycle = automation_store.load_cycle(conn, grant.cycle_id)
    current_generation = cycle.control_generation == grant.control_generation
    if current_generation:
        cycle_expected = (
            grant.control_generation, grant.broker_account_id,
            grant.takeover_epoch, grant.rollout_mode, grant.rollout_version,
            grant.certificate_sha256,
        )
        cycle_actual = (
            cycle.control_generation, cycle.broker_account_id,
            cycle.takeover_epoch, cycle.rollout_mode, cycle.rollout_version,
            cycle.certificate_sha256,
        )
        if cycle_actual != cycle_expected:
            raise PaperActivationRefused(
                "automation cycle does not match its live fencing grant")
    else:
        # Only read-only recovery may cross a generation boundary. The core's
        # sole adoption operation proves that this old obligation needs
        # read-only recovery for the same deployment/account/takeover identity
        # and stamps the current live fence without rewriting its historical
        # rollout/certificate identity. A planless preflight has not crossed a
        # transport boundary; stale plan economics are never compared with
        # current authority and can never execute.
        if (grant.operation_scope != "RECOVER"
                or cycle.control_generation >= grant.control_generation
                or not automation_store.cycle_recovery_capable(cycle)
                or not automation_store.adoption_identity_matches(
                    cycle, control)
                or cycle.last_fence_token != grant.fence_token):
            raise PaperActivationRefused(
                "old-generation automation cycle lacks current fenced "
                "read-only recovery adoption")
    if grant.operation_scope == "PREPARE":
        allowed = {CycleState.PREPARING}
    elif grant.operation_scope == "RECOVER":
        allowed = {
            CycleState.DISCOVERED, CycleState.REFRESHING_DATA,
            CycleState.EXECUTING, CycleState.RECONCILING,
            CycleState.RETRY_WAIT,
        }
    else:
        allowed = {CycleState.EXECUTING, CycleState.RECONCILING,
                   CycleState.RETRY_WAIT}
    if cycle.state not in allowed:
        raise PaperActivationRefused(
            f"automation cycle state {cycle.state.value} does not permit "
            f"{grant.operation_scope.lower()} broker access")
    return control, cycle


def _validate_broker_grant(
        conn, grant, _operation: BrokerOperation, result, *, now_provider,
        strategy_provider, dual_shadow_observation_id: str | None = None,
        dual_shadow_starting_cash: Decimal | str | None = None) -> None:
    """Fresh database-only grant proof run before and after every broker read."""
    from sentinel.handover import assert_no_legacy_path

    binding = assert_no_legacy_path(conn)
    reported = (result.identity if isinstance(result, BrokerAccountSnapshot)
                else result if isinstance(result, BrokerAccountIdentity)
                else None)
    if reported is not None and not binding.identity.matches_account(reported):
        raise PaperActivationRefused(
            "broker result identity does not match the durable binding")
    rollout = load_rollout_state(conn)
    now_et = now_provider()
    if now_et.tzinfo is None:
        raise PaperActivationRefused("broker authority clock is timezone-naive")
    current = publication.require_current(conn)
    frontier = feed_store.latest_visible_session(conn)
    runtime_strategy = dict(strategy_provider())

    if isinstance(grant, AutomationExecutionGrant):
        _control, cycle = _validate_automation_grant(conn, grant)
        if (binding.broker_account_id != grant.broker_account_id
                or binding.takeover_epoch != grant.takeover_epoch):
            raise PaperActivationRefused(
                "automation grant account/takeover identity is stale")
        decision_session = cycle.decision_session
        if grant.operation_scope == "EXECUTE":
            dual_mode = (
                dual_shadow_observation_id is not None
                and dual_shadow_starting_cash is not None)
            if dual_mode:
                plan = journal.latest_plan(conn)
                if plan is None:
                    raise PaperActivationRefused(
                        "dual broker guard has no current PAPER plan")
                from sentinel import dual_reconciliation
                try:
                    shadow = dual_reconciliation.verified_shadow_intent(
                        conn, decision_session=plan.decision_session,
                        observation_id=str(dual_shadow_observation_id),
                        starting_cash=dual_shadow_starting_cash)
                except (
                        dual_reconciliation.DualReconciliationPending,
                        dual_reconciliation.DualReconciliationRefused) as exc:
                    raise PaperActivationRefused(
                        f"dual broker guard shadow authority refused: {exc}") from exc
                state = SessionState.from_dict(shadow.state.to_dict())
                try:
                    dual_plan_authority.rederive_plan(
                        conn, plan=plan, binding=binding,
                        rollout_state=rollout,
                        expected_shadow_result=shadow)
                except dual_plan_authority.DualPlanAuthorityRefused as exc:
                    raise PaperActivationRefused(
                        f"dual broker guard sizing authority refused: {exc}") from exc
            else:
                state, plan, _cursor = _state_and_plan_or_refuse(conn)
            if (cycle.plan_id != plan.plan_id
                    or cycle.plan_fingerprint != plan.fingerprint()):
                raise PaperActivationRefused(
                    "automation cycle does not name the durable current plan")
            _readiness_or_refuse(conn, now_et=now_et)
            _execution_window_or_refuse(plan.effective_session, now_et)
            _assert_plan_authorities(
                conn, state=state, plan=plan, binding=binding,
                pinned=current, frontier=str(frontier), today=now_et.date(),
                runtime_identity=runtime_strategy, rollout=rollout)
            return
        if grant.operation_scope == "RECOVER":
            return
    elif isinstance(grant, PaperPreparationGrant):
        if binding.broker_account_id != grant.expected_account:
            raise PaperActivationRefused(
                "paper preparation grant account is stale")
        decision_session = grant.decision_session
    elif isinstance(grant, ManualExecutionGrant):
        state, plan, _cursor = _state_and_plan_or_refuse(conn)
        if (grant.confirm_paper_account != binding.broker_account_id
                or grant.confirm_plan_id != plan.plan_id
                or grant.confirm_effective_session != plan.effective_session):
            raise PaperActivationRefused(
                "manual execution grant no longer names current authority")
        _readiness_or_refuse(conn, now_et=now_et)
        _execution_window_or_refuse(plan.effective_session, now_et)
        _assert_plan_authorities(
            conn, state=state, plan=plan, binding=binding, pinned=current,
            frontier=str(frontier), today=now_et.date(),
            runtime_identity=runtime_strategy, rollout=rollout)
        return
    else:                                                       # pragma: no cover
        raise PaperActivationRefused("unknown guarded broker grant")

    # Full readiness was computed once by prepare_paper_plan while the
    # originating connection holds publication.pinned()'s session-level shared
    # advisory lock.  That lock excludes ingest/publication writers for the
    # whole preparation. Fresh guard connections still recheck the cheap
    # publication/frontier/calendar identity before every broker read, but must
    # not rescan the corpus just to prove a fact the retained pin cannot change.
    latest_closed = calendar.latest_closed_session(now_et)
    if (decision_session.isoformat() != latest_closed
            or str(frontier) != decision_session.isoformat()):
        raise PaperActivationRefused(
            "preparation grant no longer names the latest closed published "
            "XNYS session")


def _guard_broker(*, conn, broker: ExecutionBroker, grant, base_url: str,
                  now_provider, strategy_provider,
                  automation_config_sha256: str | None = None,
                  dual_shadow_observation_id: str | None = None,
                  dual_shadow_starting_cash: Decimal | str | None = None
                  ) -> GuardedExecutionBroker:
    guard = build_fresh_execution_guard(
        connection_factory=_fresh_connection_factory(conn),
        paper_base_url=base_url,
        runtime_identity=system_identity.rehearsal_identity,
        strategy_identity=strategy_provider,
        validate_grant=lambda fresh, current_grant, operation, result: (
            _validate_broker_grant(
                fresh, current_grant, operation, result,
                now_provider=now_provider,
                strategy_provider=strategy_provider,
                dual_shadow_observation_id=dual_shadow_observation_id,
                dual_shadow_starting_cash=dual_shadow_starting_cash)),
        automation_config_sha256=automation_config_sha256,
        authority_check=require_current_authority)
    return GuardedExecutionBroker(inner=broker, grant=grant, guard=guard)


async def prepare_paper_plan(*, conn, broker: ExecutionBroker, base_url: str,
                             through: date | str,
                             expected_account: Optional[str] = None,
                             warmup_sessions: int = 252,
                             controller_config: ControllerConfig | None = None,
                             strategy_identity: Mapping | None = None,
                             now_et: datetime | None = None,
                             automation_grant: AutomationExecutionGrant | None = None,
                             automation_config_sha256: str | None = None,
                             dual_shadow_observation_id: str | None = None,
                             dual_shadow_starting_cash: Decimal | str | None = None,
                             ) -> PreparationResult:
    """Advance and adopt one current plan without any broker mutation."""
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)
    schema.require_runtime_schema(conn)
    through_date = (through if isinstance(through, date)
                    else date.fromisoformat(str(through)))
    through_text = through_date.isoformat()
    if expected_account is None or not str(expected_account).strip():
        raise PaperActivationRefused(
            "paper preparation requires the exact expected account id")
    if (automation_grant is not None
            and automation_grant.operation_scope != "PREPARE"):
        raise PaperActivationRefused(
            "automation preparation requires a PREPARE-scoped grant")
    dual_values = (
        dual_shadow_observation_id, dual_shadow_starting_cash)
    if any(value is not None for value in dual_values) \
            and not all(value is not None for value in dual_values):
        raise PaperActivationRefused(
            "dual PAPER preparation requires both reviewed shadow identity "
            "and starting-capital configuration")
    dual_mode = all(value is not None for value in dual_values)
    # A reviewed deploy may perform this preparation through the read-only
    # PaperPreparationGrant while automation remains killed. That grant cannot
    # cross any broker mutation method. Actual informational transport remains
    # automation-only in `_execute_current_paper_plan`.
    if controller_config is None and strategy_identity is None:
        config, identity = _default_paper_strategy()
    else:
        # Preserve the explicit injection seam used by deterministic tests and
        # administrative tooling. Production supplies neither override.
        config = controller_config or load_controller()
        identity = dict(strategy_identity or runtime_strategy_identity(config))

    with journal.writer_lock(conn):
        # Ownership is checked under the same lock as plan adoption and before
        # the first broker read. An unbound inherited book is migration input,
        # never something daily preparation may adopt.
        from sentinel.handover import assert_no_legacy_path
        binding = assert_no_legacy_path(conn)
        rollout = load_rollout_state(conn)
        with publication.pinned(conn, commit=False) as pinned:
            observation_time = (now_et if now_et is not None else
                                datetime.now(ZoneInfo(calendar.EXCHANGE_TZ)))
            _readiness_or_refuse(conn, now_et=observation_time)
            latest_closed = calendar.latest_closed_session(observation_time)
            if through_text != latest_closed:
                raise PaperActivationRefused(
                    f"requested decision session {through_text} is not the "
                    f"latest closed XNYS session {latest_closed}. An early "
                    "current-session publication is not close evidence and "
                    "cannot become an immutable next-session plan.")
            frontier = feed_store.latest_visible_session(conn)
            if frontier != through_text:
                raise PaperActivationRefused(
                    f"requested decision session {through_text} is not the "
                    f"published frontier {frontier}")

            authority_kwargs = dict(
                runtime_identity=system_identity.rehearsal_identity(),
                strategy_identity=identity, required_mode=rollout.mode,
                paper_base_url=base_url,
                current_publication_version=pinned.version,
                automation_config_sha256=automation_config_sha256)
            if automation_grant is not None:
                automation_certificate = require_current_authority(
                    conn, required_operation="AUTOMATION", **authority_kwargs)
                certificate = require_current_authority(
                    conn, required_operation="PREPARE_READ", **authority_kwargs)
                if (automation_certificate.certificate_sha256
                        != certificate.certificate_sha256
                        or automation_grant.certificate_sha256
                        != certificate.certificate_sha256):
                    raise PaperActivationRefused(
                        "automation preparation grant and signed authority "
                        "do not match")
                grant = automation_grant
            else:
                certificate = require_current_authority(
                    conn, required_operation="PREPARE_READ", **authority_kwargs)
                grant = PaperPreparationGrant(
                    expected_account=str(expected_account),
                    decision_session=through_date)
            if (rollout.mode is RolloutMode.CONTROLLER
                    and rollout.certificate_sha256
                    != certificate.certificate_sha256):
                raise PaperActivationRefused(
                    "controller rollout and signed execution authority differ")
            if now_et is None:
                clock = lambda: datetime.now(ZoneInfo(calendar.EXCHANGE_TZ))
            else:
                clock = lambda: observation_time
            strategy_provider = (
                (lambda: _default_paper_strategy()[1])
                if controller_config is None and strategy_identity is None
                else lambda: dict(identity))
            broker = _guard_broker(
                conn=conn, broker=broker, grant=grant, base_url=base_url,
                now_provider=clock, strategy_provider=strategy_provider,
                automation_config_sha256=automation_config_sha256,
                dual_shadow_observation_id=dual_shadow_observation_id,
                dual_shadow_starting_cash=dual_shadow_starting_cash)

            existing_plan = journal.latest_plan(conn)
            dual_result = None
            dual_state = None
            if dual_mode:
                # Dual mode has one strategy lineage: the independently
                # attested shadow ledger.  Never even read the legacy PAPER
                # catch-up cursor, because a second path-dependent state could
                # drift while still producing plausible exposure numbers.
                from sentinel import dual_reconciliation
                try:
                    dual_result = dual_reconciliation.verified_shadow_intent(
                        conn, decision_session=through_date,
                        observation_id=str(dual_shadow_observation_id),
                        starting_cash=dual_shadow_starting_cash)
                except dual_reconciliation.DualReconciliationPending as exc:
                    raise PaperRetryableRefused(str(exc)) from exc
                except dual_reconciliation.DualReconciliationRefused as exc:
                    raise PaperActivationRefused(str(exc)) from exc
                dual_state = SessionState.from_dict(
                    dual_result.state.to_dict())
                if dual_state.strategy_identity != identity:
                    raise PaperActivationRefused(
                        "verified shadow strategy/config/source identity "
                        "differs from the PAPER adapter")
                if dual_state.data_version != pinned.version:
                    raise PaperRetryableRefused(
                        "verified shadow state does not name the exact pinned "
                        "publication used for PAPER account sizing")
                from sentinel import shadow_runtime
                not_before = shadow_runtime.publication_not_before(through_text)
                if observation_time < not_before:
                    raise PaperRetryableRefused(
                        "informational PAPER unit revalidation waits for the "
                        "reviewed source-final 23:45 New York boundary")
                try:
                    informational_paper_mirror.revalidate_all(
                        conn, checked_through=through_date,
                        publication_version=pinned.version, commit=True)
                    informational_paper_mirror.require_transport_permitted(
                        conn, current_frontier=through_date,
                        current_publication_version=pinned.version)
                except informational_paper_mirror.InformationalPaperMirrorMismatch as exc:
                    raise PaperActivationRefused(
                        f"informational PAPER mirror is blocked: {exc}") from exc
                except informational_paper_mirror.InformationalPaperMirrorPending as exc:
                    raise PaperRetryableRefused(
                        f"informational PAPER mirror is pending: {exc}") from exc
                except informational_paper_mirror.InformationalPaperMirrorRefused as exc:
                    raise PaperActivationRefused(
                        f"informational PAPER mirror is not current: {exc}") from exc
                existing_raw = None
                existing_cursor = None
            else:
                existing_raw = catchup.resume_state(conn)
                existing_cursor = catchup.last_processed_session(conn)
            if (existing_plan is not None
                    and existing_plan.decision_session == through_date):
                # Restart validation may return this plan unchanged. Prove its
                # economics still derive its id before contacting the broker.
                _assert_deterministic_plan_id(existing_plan)

            if (dual_mode and existing_plan is not None
                    and existing_plan.decision_session == through_date):
                state = dual_state
                _assert_concordance_witness_authority(
                    state, certificate.authorization_mode)
                _assert_plan_authorities(
                    conn, state=state, plan=existing_plan, binding=binding,
                    pinned=pinned, frontier=through_text,
                    today=date.fromisoformat(
                        calendar.next_session(through_text)),
                    runtime_identity=identity, rollout=rollout,
                    require_effective_today=False)
                try:
                    dual_plan_authority.rederive_plan(
                        conn, plan=existing_plan, binding=binding,
                        rollout_state=rollout,
                        expected_shadow_result=dual_result)
                except dual_plan_authority.DualPlanAuthorityRefused as exc:
                    raise PaperActivationRefused(
                        f"dual sizing authority refused restart: {exc}") from exc
                rec = await reconciliation.reconcile(
                    broker=broker, conn=conn, binding=None,
                    deployment=binding.identity,
                    actions=_action_lookup(conn, state, through_date))
                observation = _clean_or_refuse(
                    rec, purpose="dual PAPER preparation restart")
                account = await broker.account_snapshot()
                _account_or_refuse(account, binding, expected_account)
                activity_state = await _broker_cash_state_or_refuse(
                    conn, broker=broker, binding=binding,
                    through=observation_time)
                _cash_authority_or_refuse(
                    conn, plan=existing_plan, deployment=binding.identity,
                    account=account, observation=observation,
                    activity_state=activity_state)
                journal.adopt_current_plan(conn, existing_plan)
                return PreparationResult(
                    plan=existing_plan, sessions_replayed=0,
                    warmup_sessions=0, state_fingerprint=state.state_hash,
                    publication_version=pinned.version, frontier=through_text,
                    reconciliation=rec, superseded_plans=0)

            # Same-session preparation is restart validation, not a second
            # sizing decision. Re-reading a later NAV and replacing the plan
            # under the same market close would make an immutable daily intent
            # depend on how many times the operator retried it.
            if (existing_raw is not None and existing_cursor == through_date):
                state = SessionState.from_dict(existing_raw)
                _assert_concordance_witness_authority(
                    state, certificate.authorization_mode)
                if state.last_processed_session != existing_cursor.isoformat():
                    raise PaperActivationRefused(
                        "canonical state and processed-session cursor disagree")
                if state.strategy_identity != identity:
                    raise PaperActivationRefused(
                        "persisted strategy/config/source identity differs "
                        "from runtime")
                if existing_plan is None:
                    raise PaperActivationRefused(
                        "current state already names this session but has no "
                        "durable current plan")
                _assert_plan_authorities(
                    conn, state=state, plan=existing_plan, binding=binding,
                    pinned=pinned, frontier=through_text, today=date.fromisoformat(
                        calendar.next_session(through_text)),
                    runtime_identity=identity, rollout=rollout,
                    require_effective_today=False)
                rec = await reconciliation.reconcile(
                    broker=broker, conn=conn, binding=None,
                    deployment=binding.identity,
                    actions=_action_lookup(conn, state, through_date))
                observation = _clean_or_refuse(
                    rec, purpose="paper preparation restart")
                account = await broker.account_snapshot()
                _account_or_refuse(account, binding, expected_account)
                activity_state = await _broker_cash_state_or_refuse(
                    conn, broker=broker, binding=binding,
                    through=observation_time)
                _cash_authority_or_refuse(
                    conn, plan=existing_plan, deployment=binding.identity,
                    account=account, observation=observation,
                    activity_state=activity_state)
                # Repairs any legacy save/supersede crash shape without
                # changing plan economics; identical adoption is idempotent.
                journal.adopt_current_plan(conn, existing_plan)
                return PreparationResult(
                    plan=existing_plan, sessions_replayed=0,
                    warmup_sessions=0, state_fingerprint=state.state_hash,
                    publication_version=pinned.version, frontier=through_text,
                    reconciliation=rec, superseded_plans=0)

            actions = (
                _action_lookup(conn, dual_state, through_date)
                if dual_mode else
                _action_lookup(
                    conn, SessionState.from_dict(existing_raw), through_date)
                if existing_raw is not None else None)
            due_existing_cycle = (
                existing_plan is not None
                and trial.due_succeeded_cycle_id(
                    conn, plan_id=existing_plan.plan_id,
                    effective_session=existing_plan.effective_session)
                is not None)
            due_authority = None
            due_target_actions = None
            due_observation_target_actions = None
            if due_existing_cycle:
                _assert_deterministic_plan_id(existing_plan)
                due_target_actions = _target_action_lookup(
                    conn, existing_plan, existing_plan.effective_session)
                due_observation_target_actions = _target_action_lookup(
                    conn, existing_plan, through_date)
                commands = journal.load_commands(conn, binding.identity)
                active_security_ids = _preopen_active_security_ids(
                    plan=existing_plan, commands=commands, actions=actions)
                if active_security_ids and not dual_mode:
                    official_open = _official_preopen_cutoff(existing_plan)
                    due_authority, actions, due_target_actions = (
                        _preopen_views_or_none(
                            conn, plan=existing_plan,
                            active_security_ids=active_security_ids,
                            required_cutoff_at=official_open,
                            evaluated_at=clock(), actions=actions,
                            target_actions=due_target_actions))
                    if due_authority is None:
                        raise PreOpenShareUnitAuthorityUnavailable(
                            "pre-open share-unit authority is absent for a "
                            "nonempty succeeded-cycle finalization book; "
                            "Sentinel will not interpret prior-plan, command, "
                            "or broker-position units across its open")
                    due_observation_target_actions = (
                        preopen_authority.overlay_actions(
                            due_observation_target_actions, due_authority))

            rec = await reconciliation.reconcile(
                broker=broker, conn=conn, binding=None,
                deployment=binding.identity,
                actions=actions)
            if due_existing_cycle:
                current_commands = journal.load_commands(
                    conn, binding.identity)
                current_security_ids = _preopen_active_security_ids(
                    plan=existing_plan, commands=current_commands,
                    actions=actions)
                if (not dual_mode and due_authority is None
                        and current_security_ids):
                    raise PreOpenShareUnitAuthorityUnavailable(
                        "pre-open share-unit authority is absent after "
                        "succeeded-cycle reconciliation adopted a nonempty "
                        "share-unit identity")
                if due_authority is not None:
                    _revalidate_preopen_authority_or_refuse(
                        authority=due_authority, plan=existing_plan,
                        commands=current_commands, actions=actions,
                        required_cutoff_at=_official_preopen_cutoff(
                            existing_plan), evaluated_at=clock())
            observation = _clean_or_refuse(rec, purpose="paper preparation")
            account_observation_started_at = clock()
            account = await broker.account_snapshot()
            account_observed_at = clock()
            _account_or_refuse(account, binding, expected_account)
            activity_state = await _broker_cash_state_or_refuse(
                conn, broker=broker, binding=binding,
                through=account_observed_at)
            if existing_plan is not None:
                _cash_authority_or_refuse(
                    conn, plan=existing_plan, deployment=binding.identity,
                    account=account, observation=observation,
                    activity_state=activity_state,
                    permit_new_activity=True)
                if due_existing_cycle and not dual_mode:
                    await _finalize_due_succeeded_cycle_or_refuse(
                        conn, broker=broker, deployment=binding.identity,
                        plan=existing_plan, reconciliation=rec,
                        account=account, activity_state=activity_state,
                        observation_started_at=(
                            account_observation_started_at),
                        observed_at=account_observed_at,
                        target_actions=due_target_actions,
                        observation_target_actions=(
                            due_observation_target_actions),
                        clock=clock)
                # Informational dual PAPER deliberately has no PAPER trial-P/L
                # authority.  Its prior succeeded cycle therefore creates no
                # official-close/fill-finality debt before the next account-
                # sized plan.  The complete live account/reconciliation and
                # cash explanation above still gate sizing; certified return
                # remains solely in the independently verified shadow chain.
            if any(order.is_working for order in observation.orders):
                raise PaperActivationRefused(
                    "initial plan adoption requires no working broker order; "
                    "settle or explicitly resolve the prior durable command "
                    "before establishing the account-cash baseline")

            if dual_mode:
                # The shadow record has already advanced the only strategy
                # state.  This branch performs account sizing and plan adoption
                # only; it never reads or writes the PAPER catch-up cursor.
                state = dual_state
                _assert_concordance_witness_authority(
                    state, certificate.authorization_mode)
                marks, tickers = _load_marks_and_tickers(
                    conn, state, through_text)
                decision = build_execution_plan(
                    state=state, binding=binding, publication=pinned,
                    account_snapshot=account, observation=observation,
                    marks=marks, tickers=tickers,
                    decision_session=through_date,
                    effective_session=date.fromisoformat(
                        calendar.next_session(through_text)),
                    rollout_state=rollout)
                authority = dual_plan_authority.build_authority(
                    plan=decision.plan, shadow_result=dual_result,
                    publication=pinned, account_snapshot=account,
                    observation=observation, marks=marks, tickers=tickers)
                superseded = int(
                    existing_plan is not None
                    and existing_plan.plan_id != decision.plan.plan_id)
                latest = journal.adopt_current_plan(
                    conn, decision.plan, commit=False)
                dual_plan_authority.record_authority(
                    conn, authority, commit=False)
                dual_plan_authority.rederive_plan(
                    conn, plan=latest, binding=binding,
                    rollout_state=rollout,
                    expected_shadow_result=dual_result)
                if activity_state is not None:
                    try:
                        broker_cash.record_plan_baseline(
                            conn, plan_id=latest.plan_id,
                            decision_session=latest.decision_session,
                            activity_state=activity_state)
                    except broker_cash.BrokerCashAuthorityRefused as exc:
                        raise PaperActivationRefused(
                            "cannot establish immutable dual plan cash "
                            f"baseline: {exc}") from exc
                conn.commit()
                return PreparationResult(
                    plan=latest, sessions_replayed=0, warmup_sessions=0,
                    state_fingerprint=state.state_hash,
                    publication_version=pinned.version, frontier=through_text,
                    reconciliation=rec, superseded_plans=superseded)

            raw = existing_raw
            cursor = existing_cursor
            warmed = 0
            if raw is None:
                if cursor is not None:
                    raise PaperActivationRefused(
                        "processed-session cursor exists without canonical state")
                if (observation.positions
                        or any(order.is_working for order in observation.orders)):
                    raise PaperActivationRefused(
                        "canonical state is absent but the paper account is not "
                        "completely flat. Feature warm-up cannot reconstruct "
                        "path-dependent portfolio history; restore the state or "
                        "resolve the account explicitly")
                state = _fresh_warmed_state(
                    conn, through=through_text, count=warmup_sessions,
                    account=account, controller_config=config,
                    strategy_identity=identity,
                    publication_version=pinned.version,
                    authorization_mode=certificate.authorization_mode)
                _assert_concordance_witness_authority(
                    state, certificate.authorization_mode)
                warmed = warmup_sessions
            else:
                state = SessionState.from_dict(raw)
                _assert_concordance_witness_authority(
                    state, certificate.authorization_mode)
                if cursor is None or state.last_processed_session != cursor.isoformat():
                    raise PaperActivationRefused(
                        "canonical state and processed-session cursor disagree")
                if state.strategy_identity != identity:
                    raise PaperActivationRefused(
                        "persisted strategy/config/source identity differs from runtime")

            missed = _missed_sessions(cursor, through_date)
            if not missed and state.data_version != pinned.version:
                raise PaperActivationRefused(
                    "the corpus publication changed without a new decision "
                    "session; replaying path-dependent state in place is unsafe")

            def advance(c, session, prior):
                return advance_and_persist(
                    c, session, prior, load_published=load_published_session,
                    controller_config=config, strategy_identity=identity,
                    commit_pin=False)

            def decide(session, final_state):
                canonical = SessionState.from_dict(final_state)
                marks, tickers = _load_marks_and_tickers(
                    conn, canonical, session)
                result = build_execution_plan(
                    state=canonical, binding=binding,
                    publication=pinned, account_snapshot=account,
                    observation=observation, marks=marks, tickers=tickers,
                    decision_session=date.fromisoformat(session),
                    effective_session=date.fromisoformat(
                        calendar.next_session(session)),
                    rollout_state=rollout)
                return result.plan

            caught = catchup.catch_up_locked(
                conn, through=through_date, missed=missed,
                advance_state=advance, decide=decide, state=state.to_dict())
            final_state = SessionState.from_dict(caught.state)
            latest = journal.latest_plan(conn)
            if latest is None or latest.plan_id != caught.plan.plan_id:
                raise PaperActivationRefused(
                    "preparation did not leave exactly its plan current")
            _assert_deterministic_plan_id(latest)
            if activity_state is not None:
                try:
                    broker_cash.record_plan_baseline(
                        conn, plan_id=latest.plan_id,
                        decision_session=latest.decision_session,
                        activity_state=activity_state)
                except broker_cash.BrokerCashAuthorityRefused as exc:
                    raise PaperActivationRefused(
                        f"cannot establish immutable plan cash baseline: {exc}") from exc
            return PreparationResult(
                plan=latest, sessions_replayed=caught.sessions_replayed,
                warmup_sessions=warmed, state_fingerprint=final_state.state_hash,
                publication_version=pinned.version, frontier=through_text,
                reconciliation=rec, superseded_plans=caught.superseded)


def _state_and_plan_or_refuse(conn) -> tuple[SessionState, ExecutionPlan, object]:
    plan = journal.latest_plan(conn)
    if plan is None:
        raise PaperActivationRefused("there is no durable current execution plan")
    _assert_deterministic_plan_id(plan)
    raw = catchup.resume_state(conn)
    cursor = catchup.last_processed_session(conn)
    if raw is None or cursor is None:
        raise PaperActivationRefused("the current plan has no canonical state/cursor")
    state = SessionState.from_dict(raw)
    if state.last_processed_session != cursor.isoformat():
        raise PaperActivationRefused("canonical state and cursor disagree")
    return state, plan, cursor


def _assert_plan_authorities(conn, *, state: SessionState, plan: ExecutionPlan,
                             binding, pinned, frontier: str, today: date,
                             runtime_identity: Mapping, rollout,
                             require_effective_today: bool = True) -> None:
    _assert_deterministic_plan_id(plan)
    if plan.decision_session.isoformat() != frontier:
        raise PaperActivationRefused("plan decision session is not the current frontier")
    if require_effective_today and plan.effective_session != today:
        raise PaperActivationRefused(
            f"plan is effective {plan.effective_session}, not today {today}")
    if plan.effective_session.isoformat() != calendar.next_session(
            plan.decision_session):
        raise PaperActivationRefused("plan effective session is not next XNYS session")
    if state.last_processed_session != plan.decision_session.isoformat():
        raise PaperActivationRefused("plan session is not the canonical state cursor")
    if state.state_hash != plan.shadow_snapshot_hash:
        raise PaperActivationRefused("plan state fingerprint is stale")
    if _hash(state.last_decision) != plan.sentinel_transition_hash:
        raise PaperActivationRefused("plan controller-transition fingerprint is stale")
    if _hash(state.strategy_identity) != plan.strategy_fingerprint:
        raise PaperActivationRefused("plan strategy fingerprint is stale")
    if state.strategy_identity != dict(runtime_identity):
        raise PaperActivationRefused(
            "durable strategy/config/source identity differs from runtime")
    if (plan.data_version != pinned.version
            or state.data_version != pinned.version
            or plan.publication_fingerprint != publication_fingerprint(pinned)):
        raise PaperActivationRefused("plan publication identity is stale")
    expected = binding.identity
    actual = (plan.deployment_id, plan.broker, plan.broker_account_id,
              plan.takeover_epoch)
    wanted = (expected.deployment_id, expected.broker,
              expected.broker_account_id, expected.takeover_epoch)
    if actual != wanted:
        raise PaperActivationRefused("plan account/deployment identity is stale")
    plan_rollout = (
        plan.rollout_mode, plan.rollout_version,
        plan.rollout_certificate_sha256)
    current_rollout = (
        rollout.mode.value, rollout.version, rollout.certificate_sha256)
    if plan_rollout != current_rollout:
        raise PaperActivationRefused(
            "plan rollout mode/version authority is stale")
    if (rollout.mode is RolloutMode.PINNED_1_00
            and plan.target_exposure != Decimal(1)):
        raise PaperActivationRefused(
            "pinned rollout plan target exposure is not exactly 1")


def _action_lookup(conn, state: SessionState, through: date):
    """Corporate-action quantity changes since the last durable decision.

    The plan/current state session is the earliest trustworthy boundary this
    activation gateway owns. Reconciliation's point-in-time resolver keeps
    ticker reuse out of the lookup; unsupported merger/spinoff shapes remain
    foreign activity and therefore block increases.
    """
    from sentinel.execution.reconcile import corpus_action_lookup

    start = date.fromisoformat(
        state.last_processed_session or through.isoformat())
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(created_at)::date FROM sentinel_commands")
        row = cur.fetchone()
    if row and row[0] is not None:
        start = min(start, row[0])
    return corpus_action_lookup(conn, start=start, end=through)


def _target_action_lookup(conn, plan: ExecutionPlan, through: date):
    """Share-count changes strictly after this immutable decision.

    Reconciliation needs enough history to age old filled commands into the
    observed book, so ``_action_lookup`` may begin before the current decision.
    That wider history is not evidence that the current target is stale: only
    an action in ``(decision_session, execution_session]`` can change shares
    after this plan fixed its basket.
    """
    from sentinel.execution.reconcile import corpus_action_lookup

    return corpus_action_lookup(
        conn, start=plan.decision_session, end=through)


def _target_action_multipliers(plan: ExecutionPlan, actions) -> dict[str, Decimal]:
    """Supported share changes in the exact target-validity window.

    Preserve an evidenced action sequence even when its aggregate multiplier is
    one.  Pending Wealth Core entries are action-aged once per effective
    session, so an intermediate fractional result may already have cancelled
    the entry and cannot be treated as an uneventful x1 target later.
    """
    target_ids = tuple(
        security_id for security_id, target
        in sorted(plan.target_basket.items()) if target != 0)
    evidence_reader = getattr(actions, "scalar_evidence_for", None)
    evidenced_ids = (
        {str(event.security_id) for event in evidence_reader(target_ids)}
        if callable(evidence_reader) else set())
    result = {}
    for security_id in target_ids:
        multiplier = actions(security_id)
        if (multiplier is not None
                and (multiplier != Decimal(1)
                     or security_id in evidenced_ids)):
            result[security_id] = multiplier
    return result


def _post_projection_action_multipliers(
        projection: target_reprojection.TargetProjection,
        actions) -> dict[str, Decimal]:
    """Age only shares that survived the immutable execution projection."""
    result = {}
    for security_id, target in sorted(projection.target_basket.items()):
        if target == 0:
            continue
        multiplier = actions(
            security_id, since=projection.through_session)
        if multiplier not in (None, Decimal(1)):
            result[security_id] = multiplier
    return result


def _preopen_active_security_ids(
        *, plan: ExecutionPlan, commands, actions) -> tuple[str, ...]:
    """Return every identity that can affect this execution boundary.

    A recovered command identity remains authority-relevant even when terminal
    with zero fill and therefore absent from the expected book.  Reconciliation
    can adopt such a row after the initial provider coverage was checked;
    omitting it would let projection/transport proceed under a publication that
    never answered for the newly trusted broker identity.  Ordinary terminal,
    zero-book commands do not expand the executable security set.
    """
    expected = reconciliation.expected_book_from_commands(
        commands, actions=actions)
    identities = {
        str(security_id)
        for security_id, quantity in plan.target_basket.items()
        if quantity != 0}
    identities.update(
        str(security_id) for security_id, quantity in expected.items()
        if quantity != 0)
    identities.update(
        str(command.security_id) for command in commands
        if blocks_overlapping(command.state) or command.is_recovered)
    return tuple(sorted(identities))


def _informational_active_symbols(
        *, active_security_ids, commands, observation: BrokerObservation,
        sizing_proof: Mapping) -> dict[str, str]:
    """Bind every active permanent id to one canonical transport symbol."""
    symbols: dict[str, str] = {}

    def add(security_id, symbol) -> None:
        sid = str(security_id)
        value = str(symbol or "").strip().upper()
        if not value or sid not in active_security_ids:
            return
        prior = symbols.get(sid)
        if prior is not None and prior != value:
            raise PaperActivationRefused(
                f"active security {sid} has conflicting canonical symbols")
        symbols[sid] = value

    canonical = sizing_proof.get("canonical_symbols") or {}
    if not isinstance(canonical, Mapping):
        raise PaperActivationRefused(
            "dual sizing authority has no canonical symbol mapping")
    for security_id, symbol in canonical.items():
        add(security_id, symbol)
    for command in commands:
        add(command.security_id, command.instrument.symbol)
    for position in observation.positions:
        add(position.instrument.security_id, position.instrument.symbol)
    for order in observation.orders:
        add(order.instrument.security_id, order.instrument.symbol)
    missing = sorted(set(active_security_ids) - set(symbols))
    if missing:
        raise PaperActivationRefused(
            "informational mirror lacks a canonical symbol for active "
            "security identities: " + ", ".join(missing))
    return dict(sorted(symbols.items()))


def _plan_deltas(
        *, target_basket: Mapping[str, Decimal],
        observation: BrokerObservation,
        minimum_quantity_increment: Decimal):
    identities = set(target_basket)
    identities.update(observation.positions_by_security())
    identities.update(
        order.instrument.security_id for order in observation.orders)
    return tuple(
        execution_commands.compute_delta(
            security_id=security_id,
            desired=target_basket.get(security_id, Decimal(0)),
            observation=observation,
            min_increment=minimum_quantity_increment)
        for security_id in sorted(identities))


def _provably_clean_empty_noop(
        *, deltas, commands, observation: BrokerObservation) -> bool:
    """Bypass authority only when no active share-unit domain exists.

    Equality between a nonzero raw plan target and a nonzero broker holding is
    not a no-event attestation: an unobserved split can make those incomparable
    units numerically equal.  Only the all-zero book has no share units whose
    open-boundary meaning needs affirmative authority.
    """
    return (
        all(delta.classification is execution_commands.DeltaClass.NONE
            for delta in deltas)
        and all(delta.desired == 0 and delta.held == 0
                and delta.committed == 0 for delta in deltas)
        and not any(blocks_overlapping(command.state) for command in commands)
        and not any(order.is_working for order in observation.orders))


def _preopen_views_or_none(
        conn, *, plan: ExecutionPlan, active_security_ids,
        required_cutoff_at: datetime, evaluated_at: datetime,
        actions, target_actions):
    """Load, validate, and overlay an immutable authority if one exists."""
    try:
        authority = preopen_authority.load_authority(
            conn, plan_id=plan.plan_id)
        if authority is None:
            return None, actions, target_actions
        preopen_authority.validate_for_plan(
            authority, plan=plan,
            required_security_ids=active_security_ids,
            required_cutoff_at=required_cutoff_at,
            evaluated_at=evaluated_at)
        return (
            authority,
            preopen_authority.overlay_actions(actions, authority),
            preopen_authority.overlay_actions(target_actions, authority))
    except preopen_authority.PreOpenAuthorityRefused as exc:
        raise PreOpenShareUnitAuthorityUnavailable(str(exc)) from exc


def _revalidate_preopen_authority_or_refuse(
        *, authority, plan: ExecutionPlan, commands, actions,
        required_cutoff_at: datetime, evaluated_at: datetime) -> None:
    """Recheck exact coverage after reconciliation may have adopted commands."""
    if authority is None:
        return
    active_security_ids = _preopen_active_security_ids(
        plan=plan, commands=commands, actions=actions)
    try:
        preopen_authority.validate_for_plan(
            authority, plan=plan,
            required_security_ids=active_security_ids,
            required_cutoff_at=required_cutoff_at,
            evaluated_at=evaluated_at)
    except preopen_authority.PreOpenAuthorityRefused as exc:
        raise PreOpenShareUnitAuthorityUnavailable(str(exc)) from exc


def _official_preopen_cutoff(plan: ExecutionPlan) -> datetime:
    """The evidence boundary is the exact certified XNYS session open."""
    opened, _closed = calendar.session_window(plan.effective_session)
    return opened


def _target_projection_or_refuse(
        conn, *, state: SessionState, plan: ExecutionPlan, binding,
        broker: ExecutionBroker, through: date, actions, target_actions,
        require_existing: bool = False,
        persist_projection: bool = True,
        expected_projection: Optional[
            target_reprojection.TargetProjection] = None):
    """Derive the exact unit projection and bind it to durable plan state."""
    if state.state_hash != plan.shadow_snapshot_hash:
        raise PaperActivationRefused(
            "target projection canonical state differs from the immutable "
            "plan snapshot")
    target = shadow_target(state)
    commands = journal.load_commands(conn, binding.identity)
    expected_book = reconciliation.expected_book_from_commands(
        commands, actions=actions)
    security_ids = (
        {security_id for security_id, quantity in plan.target_basket.items()
         if quantity != 0}
        | {security_id for security_id, quantity in target.shares.items()
           if quantity != 0}
        | set(expected_book))
    symbols = (
        {target.tickers[security_id] for security_id in security_ids
         if target.tickers.get(security_id)}
        | {command.instrument.symbol for command in commands
           if (command.security_id in security_ids
               and command.instrument.symbol)})
    if DEFENSIVE_SECURITY_ID in security_ids:
        # BIL is a fixed execution identity outside the Wealth Core shadow, so
        # ``target.tickers`` cannot supply it.  Unmapped corporate-action rows
        # are ticker-bound; omitting this symbol would let an unresolved BIL
        # action miss a fresh defensive target with no prior command/position.
        symbols.add(DEFENSIVE_SYMBOL)
    material = []
    for lookup in (actions, target_actions):
        finder = getattr(lookup, "material_events_for", None)
        if callable(finder):
            material.extend(finder(
                security_ids=security_ids, symbols=symbols))
    unique = {
        (event.source_row_id, event.reason): event for event in material}
    if unique:
        detail = [event.to_dict() for event in unique.values()]
        raise PaperActivationRefused(
            "corporate action intersects the executable book but has no "
            f"certified scalar projection: {detail}. Sentinel will not invent "
            "cash, positions, fills, or corrective orders for an Alpaca paper "
            "limitation")

    target_security_ids = tuple(
        security_id for security_id, quantity
        in sorted(plan.target_basket.items()) if quantity != 0)
    multipliers = {
        security_id: target_actions(security_id)
        for security_id in target_security_ids
        if target_actions(security_id) not in (None, Decimal(1))}
    evidence_reader = getattr(target_actions, "scalar_evidence_for", None)
    action_evidence = (
        tuple(event.to_dict() for event in evidence_reader(target_security_ids))
        if callable(evidence_reader) else ())
    try:
        projected = target_reprojection.project_target(
            plan, through_session=through,
            action_multipliers=multipliers,
            action_evidence=action_evidence,
            canonical_target_shares=target.shares,
            pending_open_shares=target.pending_open_shares,
            held_shares=target.held_shares,
            pending_close_shares=target.pending_close_shares,
            minimum_quantity_increment=(
                broker.capabilities.minimum_quantity_increment))
        if (expected_projection is not None
                and projected != expected_projection):
            raise target_reprojection.TargetProjectionRefused(
                "post-reconciliation authority-derived target projection "
                "differs from the pre-read projection")
        if require_existing:
            stored = target_reprojection.load_projection(
                conn, plan_id=plan.plan_id)
            if stored is None or stored != projected:
                raise target_reprojection.TargetProjectionRefused(
                    "recovery's authority-derived target projection is absent "
                    "or differs from the immutable projection used by execution")
            target_reprojection.assert_projection(
                conn, plan=plan, projection=stored,
                through_session=through)
            return stored
        if not persist_projection:
            return projected
        return target_reprojection.record_projection(conn, projected)
    except target_reprojection.TargetProjectionRefused as exc:
        raise PaperActivationRefused(str(exc)) from exc


async def _instrument_map(conn, broker: ExecutionBroker, state: SessionState,
                          plan: ExecutionPlan,
                          observation: BrokerObservation,
                          target_basket: Mapping[str, Decimal] | None = None,
                          ) -> dict[str, BrokerInstrument]:
    desired = plan.target_basket if target_basket is None else target_basket
    target = shadow_target(state)
    symbols = dict(target.tickers)
    symbols[DEFENSIVE_SECURITY_ID] = DEFENSIVE_SYMBOL
    meta = load_meta(conn)
    for security_id in desired:
        if security_id in meta:
            symbols.setdefault(security_id, meta[security_id].ticker)
    instruments: dict[str, BrokerInstrument] = {}
    for position in observation.positions:
        instruments[position.instrument.security_id] = position.instrument
    for order in observation.orders:
        instruments[order.instrument.security_id] = order.instrument
    # Resolve only securities that can produce an actionable command. The
    # desired basket always names the defensive sleeve, including BIL:0; an
    # irrelevant zero leg must not block a pure Core reduction on a needless
    # asset lookup.
    held = observation.positions_by_security()
    all_security_ids = set(desired) | set(held)
    effective_current = {
        security_id: held.get(security_id, Decimal(0)) + committed_quantity(
            observation.working_orders_for(security_id))
        for security_id in all_security_ids
    }
    needed = {
        security_id for security_id in all_security_ids
        if desired.get(security_id, Decimal(0))
        != effective_current[security_id]
    }
    unresolved = []
    for security_id in sorted(needed):
        current = instruments.get(security_id)
        increasing = (desired.get(security_id, Decimal(0))
                      > effective_current[security_id])
        # An observed broker asset id is already the strongest mapping the
        # adapter can provide for a REDUCTION. An increase revalidates active /
        # tradable status even when the asset is already held; yesterday's
        # stable id is identity evidence, not today's permission to buy.
        if current is not None and current.broker_id and not increasing:
            continue
        symbol = symbols.get(security_id) or (
            current.symbol if current is not None else None)
        if not symbol:
            unresolved.append(security_id)
            continue
        try:
            resolved = await broker.resolve_instrument(
                security_id=security_id, symbol=str(symbol))
        except BrokerAuthorityRefused:
            raise
        except Exception as exc:                              # noqa: BLE001
            raise PaperRetryableRefused(
                f"cannot resolve broker instrument {security_id}/{symbol}: "
                f"{type(exc).__name__}: {exc}") from exc
        if (resolved.security_id != security_id
                or not resolved.broker_id or not resolved.symbol):
            raise PaperActivationRefused(
                f"broker instrument resolution for {security_id}/{symbol} "
                "did not return the requested permanent identity, symbol and "
                "stable broker asset id")
        instruments[security_id] = resolved
    if unresolved:
        raise PaperActivationRefused(
            "no certified broker instrument mapping for: "
            + ", ".join(unresolved))
    return instruments


async def _execute_current_paper_plan(
        *, conn, broker: ExecutionBroker, base_url: str,
        grant: ManualExecutionGrant | AutomationExecutionGrant,
        today: date | datetime | None = None,
        automation_config_sha256: str | None = None,
        dual_shadow_observation_id: str | None = None,
        dual_shadow_starting_cash: Decimal | str | None = None
        ) -> ExecutionResult:
    """One durable-plan gateway shared by manual and automation grants."""
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)
    if (isinstance(grant, AutomationExecutionGrant)
            and grant.operation_scope != "EXECUTE"):
        raise PaperActivationRefused(
            "automation execution requires an EXECUTE-scoped grant")
    dual_values = (
        dual_shadow_observation_id, dual_shadow_starting_cash)
    if any(value is not None for value in dual_values) \
            and not all(value is not None for value in dual_values):
        raise PaperActivationRefused(
            "dual PAPER execution requires both reviewed shadow identity and "
            "starting-capital configuration")
    dual_mode = all(value is not None for value in dual_values)
    if dual_mode and not isinstance(grant, AutomationExecutionGrant):
        raise PaperActivationRefused(
            "informational dual transport is automation-only")
    real_clock = today is None
    now_et = _execution_observation_time(today)
    today = now_et.date()
    schema.require_runtime_schema(conn)

    with journal.writer_lock(conn):
        from sentinel.handover import assert_no_legacy_path
        binding = assert_no_legacy_path(conn)
        rollout = load_rollout_state(conn)
        _controller_config, strategy_identity = _default_paper_strategy()
        with publication.pinned(conn, commit=False) as pinned:
            _readiness_or_refuse(conn, now_et=now_et)
            frontier = feed_store.latest_visible_session(conn)
            dual_result = None
            if dual_mode:
                plan = journal.latest_plan(conn)
                if plan is None:
                    raise PaperActivationRefused(
                        "there is no durable current dual PAPER plan")
                _assert_deterministic_plan_id(plan)
                from sentinel import dual_reconciliation
                try:
                    dual_result = dual_reconciliation.verified_shadow_intent(
                        conn, decision_session=plan.decision_session,
                        observation_id=str(dual_shadow_observation_id),
                        starting_cash=dual_shadow_starting_cash)
                except dual_reconciliation.DualReconciliationPending as exc:
                    raise PaperRetryableRefused(str(exc)) from exc
                except dual_reconciliation.DualReconciliationRefused as exc:
                    raise PaperActivationRefused(str(exc)) from exc
                state = SessionState.from_dict(
                    dual_result.state.to_dict())
                _cursor = plan.decision_session
            else:
                state, plan, _cursor = _state_and_plan_or_refuse(conn)
            if isinstance(grant, ManualExecutionGrant):
                if grant.confirm_paper_account != binding.broker_account_id:
                    raise PaperActivationRefused(
                        "paper-account confirmation mismatch")
                if grant.confirm_plan_id != plan.plan_id:
                    raise PaperActivationRefused("plan-id confirmation mismatch")
                if grant.confirm_effective_session != plan.effective_session:
                    raise PaperActivationRefused(
                        "effective-session confirmation mismatch")
                confirmed_account = grant.confirm_paper_account
            else:
                _control, cycle = _validate_automation_grant(conn, grant)
                if (cycle.plan_id != plan.plan_id
                        or cycle.plan_fingerprint != plan.fingerprint()):
                    raise PaperActivationRefused(
                        "automation cycle does not name the current plan")
                confirmed_account = grant.broker_account_id
            _assert_plan_authorities(
                conn, state=state, plan=plan, binding=binding, pinned=pinned,
                frontier=str(frontier), today=today,
                runtime_identity=strategy_identity, rollout=rollout)
            dual_sizing_proof = None
            if dual_mode:
                try:
                    dual_sizing_proof = dual_plan_authority.rederive_plan(
                        conn, plan=plan, binding=binding,
                        rollout_state=rollout,
                        expected_shadow_result=dual_result)
                except dual_plan_authority.DualPlanAuthorityRefused as exc:
                    raise PaperActivationRefused(
                        f"dual sizing authority refused execution: {exc}") from exc
                try:
                    informational_paper_mirror.require_transport_permitted(
                        conn, current_frontier=str(frontier),
                        current_publication_version=pinned.version)
                except informational_paper_mirror.InformationalPaperMirrorPending as exc:
                    raise PaperRetryableRefused(
                        f"informational PAPER transport is pending: {exc}") from exc
                except informational_paper_mirror.InformationalPaperMirrorRefused as exc:
                    raise PaperActivationRefused(
                        f"informational PAPER transport is blocked: {exc}") from exc
            authority_kwargs = dict(
                runtime_identity=system_identity.rehearsal_identity(),
                strategy_identity=strategy_identity,
                required_mode=rollout.mode,
                paper_base_url=base_url,
                current_publication_version=pinned.version,
                automation_config_sha256=automation_config_sha256)
            if isinstance(grant, AutomationExecutionGrant):
                automation_certificate = require_current_authority(
                    conn, required_operation="AUTOMATION", **authority_kwargs)
            certificate = require_current_authority(
                conn, required_operation="EXECUTE_READ", **authority_kwargs)
            if (isinstance(grant, AutomationExecutionGrant)
                    and (automation_certificate.certificate_sha256
                         != certificate.certificate_sha256
                         or grant.certificate_sha256
                         != certificate.certificate_sha256)):
                raise PaperActivationRefused(
                    "automation grant and signed execution authority differ")
            if (rollout.mode is RolloutMode.CONTROLLER
                    and rollout.certificate_sha256
                    != certificate.certificate_sha256):
                raise PaperActivationRefused(
                    "controller rollout was authorized by a different system "
                    "certificate")
            maximum_exposure = getattr(
                certificate, "maximum_exposure", Decimal(1))
            if plan.target_exposure > maximum_exposure:
                raise PaperActivationRefused(
                    f"current plan exposure {plan.target_exposure} exceeds "
                    "signed maximum exposure "
                    f"{maximum_exposure}")
            # Strict activation executes only during the named exchange
            # session. This is before the first broker read and consults the
            # actual XNYS schedule, so a 13:00 half-day close is a hard stop.
            _execution_window_or_refuse(plan.effective_session, now_et)

            if real_clock:
                clock = lambda: datetime.now(ZoneInfo(calendar.EXCHANGE_TZ))
            else:
                clock = lambda: now_et
            broker = _guard_broker(
                conn=conn, broker=broker, grant=grant, base_url=base_url,
                now_provider=clock,
                strategy_provider=lambda: _default_paper_strategy()[1],
                automation_config_sha256=automation_config_sha256,
                dual_shadow_observation_id=dual_shadow_observation_id,
                dual_shadow_starting_cash=dual_shadow_starting_cash)

            account = await broker.account_snapshot()
            _account_or_refuse(account, binding, confirmed_account)
            activity_state = await _broker_cash_state_or_refuse(
                conn, broker=broker, binding=binding, through=clock())
            try:
                actions = _action_lookup(conn, state, today)
                target_actions = _target_action_lookup(conn, plan, today)
            except ValueError as exc:
                raise PaperActivationRefused(
                    f"corporate-action authority is ambiguous or invalid: {exc}") from exc
            commands = journal.load_commands(conn, binding.identity)
            active_security_ids = _preopen_active_security_ids(
                plan=plan, commands=commands, actions=actions)
            official_open = _official_preopen_cutoff(plan)
            authority, actions, target_actions = _preopen_views_or_none(
                conn, plan=plan,
                active_security_ids=active_security_ids,
                required_cutoff_at=official_open,
                evaluated_at=clock(), actions=actions,
                target_actions=target_actions)
            target_projection = None
            if authority is not None:
                # Refuse unsupported/non-scalar corporate actions before the
                # broker book can be consulted.  Reconciliation may still
                # adopt a previously unknown command identity, so the exact
                # projection is re-derived and matched below after that read.
                target_projection = _target_projection_or_refuse(
                    conn, state=state, plan=plan, binding=binding,
                    broker=broker, through=today, actions=actions,
                    target_actions=target_actions,
                    persist_projection=False)
            preflight = await reconciliation.reconcile(
                broker=broker, conn=conn, binding=None,
                deployment=binding.identity, actions=actions)
            observation = (
                _dual_mutation_observation_or_refuse(preflight)
                if dual_mode else
                _clean_or_refuse(preflight, purpose="paper execution"))
            if _account_evidence_is_quiescent(
                    conn, deployment=binding.identity,
                    observation=observation):
                # The earlier account read established identity/availability,
                # but cannot be paired with a later reconciliation: a fill may
                # have landed between them. Re-read only after the observation
                # proves there is no working or durable in-flight command.
                account = await broker.account_snapshot()
                cash_evidence_at = clock()
                _account_or_refuse(account, binding, confirmed_account)
                activity_state = await _broker_cash_state_or_refuse(
                    conn, broker=broker, binding=binding,
                    through=cash_evidence_at)
                _cash_authority_or_refuse(
                    conn, plan=plan, deployment=binding.identity,
                    account=account, observation=observation,
                    activity_state=activity_state,
                    endpoint_lag_observed_at=cash_evidence_at)
            current_commands = journal.load_commands(conn, binding.identity)
            _revalidate_preopen_authority_or_refuse(
                authority=authority, plan=plan, commands=current_commands,
                actions=actions, required_cutoff_at=official_open,
                evaluated_at=clock())
            minimum_increment = (
                broker.capabilities.minimum_quantity_increment)
            preopen_deltas = _plan_deltas(
                target_basket=plan.target_basket,
                observation=observation,
                minimum_quantity_increment=minimum_increment)
            if authority is None and dual_mode:
                # This is explicitly informational transport, not affirmative
                # pre-open unit authority. The exact close-unit basket remains
                # immutable and a post-close source-final check can only block
                # later mutations; it never rewrites these quantities.
                target_projection = None
                projected_deltas = preopen_deltas
                pending_ids = _preopen_active_security_ids(
                    plan=plan, commands=current_commands, actions=actions)
                pending_symbols = _informational_active_symbols(
                    active_security_ids=pending_ids,
                    commands=current_commands, observation=observation,
                    sizing_proof=dual_sizing_proof)
                informational_paper_mirror.record_pending(
                    conn, plan=plan, active_security_ids=pending_ids,
                    active_symbols=pending_symbols,
                    sizing_authority_sha256=(
                        dual_sizing_proof["authority_sha256"]),
                    shadow_record_sha256=(
                        dual_sizing_proof["shadow_record_sha256"]),
                    publication_version=pinned.version,
                    # Commit the PENDING stamp before the first possible
                    # broker call. A later outer rollback must not erase the
                    # fact that a crashed submit may have landed.
                    commit=True)
            elif authority is None:
                if not _provably_clean_empty_noop(
                        deltas=preopen_deltas, commands=current_commands,
                        observation=observation):
                    raise PreOpenShareUnitAuthorityUnavailable(
                        "pre-open share-unit authority is absent and the "
                        "complete, clean broker book is not an empty no-op; "
                        "numerical equality of nonzero raw shares cannot prove "
                        "that no effective-session split occurred; "
                        "Sentinel will not project a target or create, cancel, "
                        "or submit a command")
                target_projection = None
                projected_deltas = preopen_deltas
            else:
                # Reconciliation can durably adopt a broker order that was not
                # present at the first projection boundary.  Re-run all
                # material-action checks over that expanded command set and
                # require the result to equal the immutable pre-read target.
                target_projection = _target_projection_or_refuse(
                    conn, state=state, plan=plan, binding=binding,
                    broker=broker, through=today, actions=actions,
                    target_actions=target_actions,
                    expected_projection=target_projection)
                projected_deltas = _plan_deltas(
                    target_basket=target_projection.target_basket,
                    observation=observation,
                    minimum_quantity_increment=minimum_increment)

            if all(delta.classification is execution_commands.DeltaClass.NONE
                   for delta in projected_deltas):
                session = executor.SessionResult(
                    runtime_state=RuntimeState.RUNNING,
                    reconciliation=preflight,
                    detail="complete clean empty no-op; no command transport")
            else:
                # The branch is unreachable without a validated authority:
                # dust is not a true no-op, even when no broker can fill it.
                if target_projection is None and not dual_mode:  # pragma: no cover
                    raise PreOpenShareUnitAuthorityUnavailable(
                        "pre-open authority is required before command sizing")
                instruments = await _instrument_map(
                    conn, broker, state, plan, observation,
                    target_basket=(
                        plan.target_basket if target_projection is None
                        else target_projection.target_basket))

                async def authorize_increases(fresh_observation):
                    if not _account_evidence_is_quiescent(
                            conn, deployment=binding.identity,
                            observation=fresh_observation):
                        raise PaperRetryableRefused(
                            "account cash remains PENDING while an order or "
                            "durable command is in flight")
                    fresh_account = await broker.account_snapshot()
                    fresh_cash_at = clock()
                    _account_or_refuse(
                        fresh_account, binding, confirmed_account)
                    fresh_activity_state = await _broker_cash_state_or_refuse(
                        conn, broker=broker, binding=binding,
                        through=fresh_cash_at)
                    _cash_authority_or_refuse(
                        conn, plan=plan, deployment=binding.identity,
                        account=fresh_account,
                        observation=fresh_observation,
                        activity_state=fresh_activity_state,
                        endpoint_lag_observed_at=fresh_cash_at)

                async def authorize_dual_mutations(fresh_reconciliation):
                    _dual_mutation_observation_or_refuse(
                        fresh_reconciliation)

                session = await executor.execute_session(
                    broker=broker, conn=conn, deployment=binding.identity,
                    plan=plan, instruments=instruments, today=today,
                    actions=actions, target_projection=target_projection,
                    min_increment=minimum_increment,
                    increase_authority=authorize_increases,
                    mutation_authority=(
                        authorize_dual_mutations
                        if dual_mode else None))
            final_reconciliation = session.reconciliation
            if (final_reconciliation is not None
                    and final_reconciliation.runtime_state is RuntimeState.RUNNING
                    and final_reconciliation.clean
                    and final_reconciliation.observation is not None
                    and final_reconciliation.observation.is_complete
                    and final_reconciliation.observation_id is not None
                    and target_projection is not None
                    and _account_evidence_is_quiescent(
                        conn, deployment=binding.identity,
                        observation=final_reconciliation.observation)):
                (confirmed_reconciliation, evidence_account,
                 evidence_activity, evidence_started_at, evidence_at) = (
                    await _settled_account_evidence_bracket(
                        conn=conn, broker=broker, binding=binding,
                        expected_account=confirmed_account,
                        deployment=binding.identity,
                        initial_result=final_reconciliation,
                        actions=actions, dual_mode=dual_mode, clock=clock))
                _cash_authority_or_refuse(
                    conn, plan=plan, deployment=binding.identity,
                    account=evidence_account,
                    observation=confirmed_reconciliation.observation,
                    activity_state=evidence_activity,
                    endpoint_lag_observed_at=evidence_at)
                trial.record_account_evidence(
                    conn, session=plan.effective_session,
                    observation_id=confirmed_reconciliation.observation_id,
                    observation_started_at=evidence_started_at,
                    observed_at=evidence_at, snapshot=evidence_account,
                    deployment=binding.identity,
                    reconciliation=confirmed_reconciliation,
                    activity_state=evidence_activity,
                    plan=plan,
                    target_projection=target_projection,
                    observation_post_projection_actions=(
                        _post_projection_action_multipliers(
                            target_projection, target_actions)))
            return ExecutionResult(plan=plan, preflight=preflight,
                                   session=session)


async def execute_paper_plan(*, conn, broker: ExecutionBroker, base_url: str,
                             confirm_account: str, confirm_plan_id: str,
                             confirm_effective_session: date | str,
                             confirm_submit: bool,
                             today: date | datetime | None = None
                             ) -> ExecutionResult:
    """Execute the current plan only with the exact manual confirmations."""
    if not confirm_submit:
        raise PaperActivationRefused("--confirm-submit-paper-orders is required")
    effective = (confirm_effective_session
                 if isinstance(confirm_effective_session, date)
                 else date.fromisoformat(str(confirm_effective_session)))
    grant = ManualExecutionGrant(
        confirm_paper_account=confirm_account,
        confirm_plan_id=confirm_plan_id,
        confirm_effective_session=effective,
        confirm_submit_paper_orders=True)
    return await _execute_current_paper_plan(
        conn=conn, broker=broker, base_url=base_url,
        grant=grant, today=today)


async def execute_automated_paper_plan(
        *, conn, broker: ExecutionBroker, base_url: str,
        grant: AutomationExecutionGrant,
        automation_config_sha256: str,
        today: date | datetime | None = None,
        dual_shadow_observation_id: str | None = None,
        dual_shadow_starting_cash: Decimal | str | None = None
        ) -> ExecutionResult:
    """Execute the same current plan through a fenced automation grant."""
    return await _execute_current_paper_plan(
        conn=conn, broker=broker, base_url=base_url, grant=grant,
        today=today, automation_config_sha256=automation_config_sha256,
        dual_shadow_observation_id=dual_shadow_observation_id,
        dual_shadow_starting_cash=dual_shadow_starting_cash)


async def recover_automated_paper_cycle(
        *, conn, broker: ExecutionBroker, base_url: str,
        grant: AutomationExecutionGrant,
        automation_config_sha256: str,
        dual_shadow_observation_id: str | None = None,
        dual_shadow_starting_cash: Decimal | str | None = None):
    """Read-only reconciliation for restart/pre-publication automation recovery."""
    if grant.operation_scope != "RECOVER":
        raise PaperActivationRefused(
            "automation recovery requires a RECOVER-scoped grant")
    dual_values = (
        dual_shadow_observation_id, dual_shadow_starting_cash)
    if any(value is not None for value in dual_values) \
            and not all(value is not None for value in dual_values):
        raise PaperActivationRefused(
            "dual PAPER recovery requires both reviewed shadow identity and "
            "starting-capital configuration")
    dual_mode = all(value is not None for value in dual_values)
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)
    schema.require_runtime_schema(conn)
    with journal.writer_lock(conn):
        from sentinel.handover import assert_no_legacy_path
        binding = assert_no_legacy_path(conn)
        rollout = load_rollout_state(conn)
        _controller_config, strategy = _default_paper_strategy()
        current = publication.require_current(conn)
        authority_kwargs = dict(
            runtime_identity=system_identity.rehearsal_identity(),
            strategy_identity=strategy, required_mode=rollout.mode,
            paper_base_url=base_url,
            current_publication_version=current.version,
            automation_config_sha256=automation_config_sha256)
        try:
            automated = require_current_authority(
                conn, required_operation="AUTOMATION", **authority_kwargs)
            readable = require_current_authority(
                conn, required_operation="EXECUTE_READ", **authority_kwargs)
            if automated.certificate_sha256 != readable.certificate_sha256:
                raise AuthorityRefused(
                    "automation and recovery authority differ")
        except AuthorityRefused:
            readable = require_observation_safety_authority(
                conn, required_operation="SAFETY_READ",
                required_mode=rollout.mode, paper_base_url=base_url)
        if grant.certificate_sha256 != readable.certificate_sha256:
            raise PaperActivationRefused(
                "automation recovery grant and signed safety authority differ")
        _control, cycle = _validate_automation_grant(conn, grant)
        clock = lambda: datetime.now(ZoneInfo(calendar.EXCHANGE_TZ))
        broker = _guard_broker(
            conn=conn, broker=broker, grant=grant, base_url=base_url,
            now_provider=clock,
            strategy_provider=lambda: _default_paper_strategy()[1],
            automation_config_sha256=automation_config_sha256,
            dual_shadow_observation_id=dual_shadow_observation_id,
            dual_shadow_starting_cash=dual_shadow_starting_cash)
        account = await broker.account_snapshot()
        _recovery_account_identity_or_refuse(
            account, binding, grant.broker_account_id)
        activity_state = await _broker_cash_state_or_refuse(
            conn, broker=broker, binding=binding, through=clock())
        # A dual recovery never consults the separate PAPER catch-up lineage.
        # Its exact shadow state is loaded after the current-generation plan is
        # identified below.
        raw = None if dual_mode else catchup.resume_state(conn)
        state = SessionState.from_dict(raw) if raw is not None else None

        # An adopted old-generation obligation may be reconciled under the
        # current safety fence, but its stale plan economics must never be
        # loaded or interpreted under current authority.  Only the exact plan
        # already bound to this live generation can supply a target or a
        # plan-bound pre-open share-unit publication.
        plan = None
        if (cycle.control_generation == grant.control_generation
                and cycle.plan_id is not None):
            candidate = journal.load_plan(conn, cycle.plan_id)
            if (candidate is not None
                    and candidate.fingerprint() == cycle.plan_fingerprint
                    and candidate.decision_session == cycle.decision_session
                    and candidate.effective_session
                    == cycle.effective_session):
                _assert_deterministic_plan_id(candidate)
                plan = candidate

        dual_result = None
        if dual_mode and plan is not None:
            from sentinel import dual_reconciliation
            try:
                dual_result = dual_reconciliation.verified_shadow_intent(
                    conn, decision_session=plan.decision_session,
                    observation_id=str(dual_shadow_observation_id),
                    starting_cash=dual_shadow_starting_cash)
            except dual_reconciliation.DualReconciliationPending as exc:
                raise PaperRetryableRefused(str(exc)) from exc
            except dual_reconciliation.DualReconciliationRefused as exc:
                raise PaperActivationRefused(str(exc)) from exc
            state = SessionState.from_dict(dual_result.state.to_dict())
            try:
                dual_plan_authority.rederive_plan(
                    conn, plan=plan, binding=binding,
                    rollout_state=rollout,
                    expected_shadow_result=dual_result)
            except dual_plan_authority.DualPlanAuthorityRefused as exc:
                    raise PaperActivationRefused(
                        f"dual sizing authority refused recovery: {exc}") from exc
            try:
                # A cycle can remain RECONCILING across the next close.  Its
                # due post-close unit check must be earned here before the
                # transport fence is consulted; otherwise require_transport
                # reports PENDING forever and successor preparation (the other
                # caller of revalidate_all) is unreachable.
                with publication.pinned(conn, commit=False) as mirror_pin:
                    if mirror_pin.version != current.version:
                        raise PaperRetryableRefused(
                            "corpus publication advanced while dual recovery "
                            "authority was being established")
                    current_frontier = feed_store.latest_visible_session(conn)
                    from sentinel import shadow_runtime
                    if clock() < shadow_runtime.publication_not_before(
                            str(current_frontier)):
                        raise informational_paper_mirror.InformationalPaperMirrorPending(
                            "current publication has not reached the reviewed "
                            "23:45 New York source-final boundary")
                    informational_paper_mirror.revalidate_all(
                        conn, checked_through=current_frontier,
                        publication_version=mirror_pin.version, commit=True)
                    informational_paper_mirror.require_transport_permitted(
                        conn, current_frontier=current_frontier,
                        current_publication_version=mirror_pin.version)
            except informational_paper_mirror.InformationalPaperMirrorPending as exc:
                raise PaperRetryableRefused(
                    f"informational PAPER recovery is pending: {exc}") from exc
            except informational_paper_mirror.InformationalPaperMirrorRefused as exc:
                raise PaperActivationRefused(
                    f"informational PAPER recovery is blocked: {exc}") from exc

        actions = (_action_lookup(conn, state, clock().date())
                   if state is not None else None)
        authority = None
        target_projection = None
        target_actions = None
        observation_target_actions = None
        if plan is not None:
            target_actions = _target_action_lookup(
                conn, plan, plan.effective_session)
            observation_target_actions = _target_action_lookup(
                conn, plan, clock().date())
            commands = journal.load_commands(conn, binding.identity)
            active_security_ids = _preopen_active_security_ids(
                plan=plan, commands=commands, actions=actions)
            if active_security_ids and not dual_mode:
                official_open = _official_preopen_cutoff(plan)
                authority, actions, target_actions = _preopen_views_or_none(
                    conn, plan=plan,
                    active_security_ids=active_security_ids,
                    required_cutoff_at=official_open,
                    evaluated_at=clock(), actions=actions,
                    target_actions=target_actions)
                if authority is None:
                    raise PreOpenShareUnitAuthorityUnavailable(
                        "pre-open share-unit authority is absent for the "
                        "nonempty recovery book; Sentinel will not interpret "
                        "plan, command, or broker-position share units across "
                        "the effective-session open")
                observation_target_actions = (
                    preopen_authority.overlay_actions(
                        observation_target_actions, authority))
        result = await reconciliation.reconcile(
            broker=broker, conn=conn, binding=None,
            deployment=binding.identity, actions=actions)

        if plan is not None:
            current_commands = journal.load_commands(conn, binding.identity)
            current_security_ids = _preopen_active_security_ids(
                plan=plan, commands=current_commands, actions=actions)
            if (not dual_mode and authority is None
                    and current_security_ids):
                raise PreOpenShareUnitAuthorityUnavailable(
                    "pre-open share-unit authority is absent after recovery "
                    "adopted a nonempty share-unit identity; Sentinel will "
                    "not treat that command or broker position as current "
                    "plan economics")
            if authority is not None:
                _revalidate_preopen_authority_or_refuse(
                    authority=authority, plan=plan,
                    commands=current_commands, actions=actions,
                    required_cutoff_at=_official_preopen_cutoff(plan),
                    evaluated_at=clock())
                if state is None:
                    raise PaperActivationRefused(
                        "current-generation recovery cannot revalidate its "
                        "target projection without canonical strategy state")
                target_projection = _target_projection_or_refuse(
                    conn, state=state, plan=plan, binding=binding,
                    broker=broker, through=plan.effective_session,
                    actions=actions, target_actions=target_actions,
                    require_existing=True)

        if dual_mode:
            _dual_mutation_observation_or_refuse(result)

        if (plan is not None
                and result.runtime_state is RuntimeState.RUNNING
                and result.clean
                and result.observation is not None
                and result.observation.is_complete
                and result.observation_id is not None
                and target_projection is not None
                and _account_evidence_is_quiescent(
                    conn, deployment=binding.identity,
                    observation=result.observation)):
            (confirmed_result, account, activity_state,
             evidence_started_at, evidence_at) = (
                await _settled_account_evidence_bracket(
                    conn=conn, broker=broker, binding=binding,
                    expected_account=grant.broker_account_id,
                    deployment=binding.identity,
                    initial_result=result, actions=actions,
                    dual_mode=dual_mode, clock=clock))
            _cash_authority_or_refuse(
                conn, plan=plan, deployment=binding.identity,
                account=account,
                observation=confirmed_result.observation,
                activity_state=activity_state,
                # Recovery submits nothing. A recognized post-plan
                # dividend/interest/fee is legitimate realized economics;
                # it may be certified after the book is clean even though
                # it would refuse a stale plan's new BUY authorization.
                permit_new_activity=True,
                endpoint_lag_observed_at=evidence_at)
            trial.record_account_evidence(
                conn, session=plan.effective_session,
                observation_id=confirmed_result.observation_id,
                observation_started_at=evidence_started_at,
                observed_at=evidence_at, snapshot=account,
                deployment=binding.identity,
                reconciliation=confirmed_result,
                activity_state=activity_state,
                plan=plan,
                target_projection=target_projection,
                observation_post_projection_actions=(
                    _post_projection_action_multipliers(
                        target_projection, observation_target_actions)))
        return result


def current_paper_plan(
        conn, *, base_url: str = DEFAULT_BASE_URL,
        dual_shadow_observation_id: str | None = None,
        dual_shadow_starting_cash: Decimal | str | None = None) -> dict:
    """Inspect current durable authorities without contacting the broker.

    Informational dual plans deliberately have no PAPER catch-up cursor: their
    only strategy state is the independently attested shadow record.  The dual
    inspection path therefore re-earns that record against the current corpus
    and re-derives the immutable account-sizing authority.  Ordinary PAPER
    keeps the historical strict catch-up-state inspection unchanged.
    """
    dual_values = (
        dual_shadow_observation_id, dual_shadow_starting_cash)
    if any(value is not None for value in dual_values) \
            and not all(value is not None for value in dual_values):
        raise PaperActivationRefused(
            "dual PAPER inspection requires both reviewed shadow identity "
            "and starting-capital configuration")
    dual_mode = all(value is not None for value in dual_values)
    dual_match = None
    if dual_mode:
        plan = journal.latest_plan(conn)
        if plan is None:
            raise PaperActivationRefused(
                "there is no durable current dual PAPER plan")
        _assert_deterministic_plan_id(plan)
        from sentinel import dual_reconciliation
        try:
            dual_match = dual_reconciliation.require_plan_matches_verified_shadow(
                conn, plan=plan,
                observation_id=str(dual_shadow_observation_id),
                starting_cash=dual_shadow_starting_cash)
            result = dual_reconciliation.verified_shadow_intent(
                conn, decision_session=plan.decision_session,
                observation_id=str(dual_shadow_observation_id),
                starting_cash=dual_shadow_starting_cash)
        except dual_reconciliation.DualReconciliationPending as exc:
            raise PaperRetryableRefused(str(exc)) from exc
        except dual_reconciliation.DualReconciliationRefused as exc:
            raise PaperActivationRefused(str(exc)) from exc
        state = SessionState.from_dict(result.state.to_dict())
        cursor = plan.decision_session
    else:
        state, plan, cursor = _state_and_plan_or_refuse(conn)
    from sentinel.handover import assert_no_legacy_path
    binding = assert_no_legacy_path(conn)
    current = publication.require_current(conn)
    frontier = feed_store.latest_visible_session(conn)
    _controller_config, runtime_identity = _default_paper_strategy()
    rollout = load_rollout_state(conn)
    checks = {
        "owned_binding": binding.is_owned,
        "state_matches_plan": state.state_hash == plan.shadow_snapshot_hash,
        "controller_transition_matches_plan": (
            _hash(state.last_decision) == plan.sentinel_transition_hash),
        "publication_matches_plan": (
            (dual_mode and dual_match is not None
             and state.data_version == plan.data_version)
            or (not dual_mode
                and state.data_version == plan.data_version == current.version
                and plan.publication_fingerprint
                == publication_fingerprint(current))),
        "account_matches_plan": (
            plan.deployment_id == binding.deployment_id
            and plan.broker == binding.broker
            and plan.broker_account_id == binding.broker_account_id
            and plan.takeover_epoch == binding.takeover_epoch),
        "strategy_matches_runtime": (
            (dual_mode and dual_match is not None
             and dual_match["state_sha256"] == state.state_hash)
            or (not dual_mode
                and state.strategy_identity == runtime_identity
                and _hash(state.strategy_identity)
                == plan.strategy_fingerprint)),
        "decision_matches_frontier": (
            state.last_processed_session
            == plan.decision_session.isoformat()
            == str(frontier)),
        "effective_is_next_session": (
            plan.effective_session.isoformat()
            == calendar.next_session(plan.decision_session)),
        "rollout_matches_plan": (
            plan.rollout_mode == rollout.mode.value
            and plan.rollout_version == rollout.version
            and plan.rollout_certificate_sha256
            == rollout.certificate_sha256
            and (rollout.mode is not RolloutMode.PINNED_1_00
                 or plan.target_exposure == Decimal(1))),
    }
    if dual_mode:
        checks.update({
            "current_corpus_shadow_revalidated": dual_match is not None,
            "dual_sizing_authority_matches": (
                dual_match is not None
                and dual_match.get("verdict") == "MATCH"),
            "dual_plan_fingerprint_matches": (
                dual_match is not None
                and dual_match.get("plan_fingerprint")
                == plan.fingerprint()),
        })
    try:
        certificate = require_current_authority(
            conn, runtime_identity=system_identity.rehearsal_identity(),
            strategy_identity=runtime_identity, required_mode=rollout.mode,
            required_operation="EXECUTE_READ", paper_base_url=base_url,
            current_publication_version=current.version)
        checks["system_certificate_valid"] = (
            rollout.mode is not RolloutMode.CONTROLLER
            or rollout.certificate_sha256 == certificate.certificate_sha256)
    except AuthorityRefused:
        checks["system_certificate_valid"] = False
    return {
        "broker_contacted": False,
        "broker_mutations_permitted": False,
        # Broker account, current NAV, readiness, reconciliation, actual date,
        # and asset tradability are intentionally rechecked only by execution.
        "execution_authorized": False,
        "database_authorities_match": all(checks.values()),
        "mode": "INFORMATIONAL_PAPER_MIRROR" if dual_mode else "PAPER",
        "performance_authority": (
            "CERTIFIED_SHADOW" if dual_mode else "PAPER_TRIAL"),
        "dual_reconciliation": dual_match,
        "cursor": cursor.isoformat(),
        "frontier": frontier,
        "binding": binding.to_dict(),
        "publication": current.to_dict(),
        "rollout": rollout.to_dict(),
        "state_fingerprint": state.state_hash,
        "plan": plan.to_dict(),
        "checks": checks,
    }


def build_security_resolver(conn, session: str):
    """Point-in-time broker symbol -> permanent execution identity."""
    from sentinel.feed.universe import load_resolver
    resolver = load_resolver(conn)

    def resolve(symbol: str, as_of: str | None = None):
        if str(symbol).upper() == DEFENSIVE_SYMBOL:
            return DEFENSIVE_SECURITY_ID
        return resolver.resolve(str(symbol), as_of or session)

    return resolve


__all__ = [
    "DEFENSIVE_SYMBOL", "ExecutionResult", "PaperAccountInspection",
    "PaperActivationRefused", "PaperRetryableRefused",
    "PreOpenShareUnitAuthorityUnavailable", "PreparationResult",
    "build_security_resolver",
    "current_paper_plan", "execute_automated_paper_plan",
    "execute_paper_plan", "inspect_paper_account", "prepare_paper_plan",
    "recover_automated_paper_cycle",
]
