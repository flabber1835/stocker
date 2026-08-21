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
from decimal import Decimal
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

from sentinel import (
    binding as binding_mod,
    identity as system_identity,
    schema,
    trial,
)
from sentinel.authority import (
    AuthorityRefused,
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
    load_causal_meta_history, load_meta, load_window)
from sentinel.core.production import (
    SessionState,
    advance_and_persist,
    load_published_session,
    warm_session_state,
)
from sentinel.execution import broker_cash, executor, journal
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
from sentinel.feed import calendar, publication, readiness, store as feed_store

DEFENSIVE_SYMBOL = "BIL"
SIMPLIFIED_LDRC_STRATEGY_ID = "sentinel-concordance-simplified-ldrc"
SIMPLIFIED_LDRC_STRATEGY_VERSION = 3


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


def _cash_authority_or_refuse(
        conn, *, plan: ExecutionPlan, deployment,
        account: BrokerAccountSnapshot, observation: BrokerObservation,
        activity_state: broker_cash.CashActivityState | None = None,
        permit_new_activity: bool = False) -> None:
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
    if activity_state is not None:
        if (activity_state.broker != plan.broker
                or activity_state.account_id != plan.broker_account_id):
            raise PaperActivationRefused(
                "broker cash activity state belongs to another account")
        baseline = broker_cash.load_plan_baseline(
            conn, plan_id=plan.plan_id)
        if baseline is None:
            # Upgrade bridge: an old plan can acquire a baseline only when the
            # old cash equation still balances exactly. If cash already moved,
            # we cannot know which retained activity preceded that plan and
            # which followed it, so guessing is forbidden.
            if abs(account.cash - expected_without_activity) > Decimal("1.00"):
                raise PaperActivationRefused(
                    f"plan {plan.plan_id} predates broker cash baselines and "
                    "fresh cash no longer matches its durable fills. The "
                    "activity history cannot be safely partitioned around that "
                    "old plan; resolve the cash explicitly and prepare a fresh "
                    "decision")
            baseline = broker_cash.record_plan_baseline(
                conn, plan_id=plan.plan_id,
                decision_session=plan.decision_session,
                activity_state=activity_state)
        activity_delta = activity_state.balance_total - baseline.balance_total

    expected = expected_without_activity + activity_delta
    if abs(account.cash - expected) > Decimal("1.00"):
        raise PaperActivationRefused(
            f"fresh account cash {account.cash} is not explained by plan "
            f"baseline {plan.account_cash}, durable fills and broker-native "
            f"cash activities (expected {expected}). Cash movement is never "
            "inferred")
    if activity_delta != 0 and not permit_new_activity:
        raise PaperActivationRefused(
            f"broker-native cash activity changed by {activity_delta} after "
            f"plan {plan.plan_id} was prepared. The event is durably explained, "
            "but this immutable plan will not be re-sized in place; prepare the "
            "next closed decision session")


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
        cur.execute(
            "SELECT security_id,close_unadjusted FROM sentinel_bars b"
            " WHERE session=%s AND UPPER(ticker)=%s AND " + visible
            + " ORDER BY security_id", (session, DEFENSIVE_SYMBOL))
        defensive = cur.fetchall()
    if len(defensive) > 1:
        raise PaperActivationRefused(
            f"{DEFENSIVE_SYMBOL} resolves to more than one security on {session}")
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
                        publication_version: int) -> SessionState:
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
    if is_concordance_identity(strategy_identity):
        window.metadata_timeline = load_causal_meta_history(
            conn, sessions=warm)
    starting_cash = float(account.equity)
    if not math.isfinite(starting_cash):
        raise PaperActivationRefused("account equity cannot be represented by Wealth Core")
    state = SessionState.fresh(
        starting_cash=starting_cash, controller=Controller(controller_config),
        strategy_identity=strategy_identity)
    return warm_session_state(
        state, window, publication_version=publication_version)


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
        # sole adoption operation proves that this is a transport-capable old
        # obligation for the same deployment/account/takeover identity and
        # stamps the current live fence without rewriting its historical
        # rollout/certificate identity. Those stale economics are deliberately
        # not compared with current authority and can never execute.
        if (grant.operation_scope != "RECOVER"
                or cycle.control_generation >= grant.control_generation
                or not automation_store.cycle_transport_capable(cycle)
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


def _validate_broker_grant(conn, grant, _operation: BrokerOperation,
                           result, *, now_provider, strategy_provider) -> None:
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
                  automation_config_sha256: str | None = None
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
                strategy_provider=strategy_provider)),
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
                automation_config_sha256=automation_config_sha256)

            existing_raw = catchup.resume_state(conn)
            existing_cursor = catchup.last_processed_session(conn)
            existing_plan = journal.latest_plan(conn)
            if (existing_raw is not None
                    and existing_cursor == through_date
                    and existing_plan is not None):
                # Restart validation may return this plan unchanged. Prove its
                # economics still derive its id before contacting the broker.
                _assert_deterministic_plan_id(existing_plan)

            # Same-session preparation is restart validation, not a second
            # sizing decision. Re-reading a later NAV and replacing the plan
            # under the same market close would make an immutable daily intent
            # depend on how many times the operator retried it.
            if (existing_raw is not None and existing_cursor == through_date):
                state = SessionState.from_dict(existing_raw)
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

            rec = await reconciliation.reconcile(
                broker=broker, conn=conn, binding=None,
                deployment=binding.identity,
                actions=(_action_lookup(
                    conn, SessionState.from_dict(existing_raw), through_date)
                    if existing_raw is not None else None))
            observation = _clean_or_refuse(rec, purpose="paper preparation")
            account = await broker.account_snapshot()
            _account_or_refuse(account, binding, expected_account)
            activity_state = await _broker_cash_state_or_refuse(
                conn, broker=broker, binding=binding,
                through=observation_time)
            if existing_plan is not None:
                _cash_authority_or_refuse(
                    conn, plan=existing_plan, deployment=binding.identity,
                    account=account, observation=observation,
                    activity_state=activity_state,
                    permit_new_activity=True)
                due_cycle_id = (trial.due_succeeded_cycle_id(
                    conn, plan_id=existing_plan.plan_id,
                    effective_session=through_date)
                    if (automation_grant is not None
                        and existing_plan.effective_session == through_date)
                    else None)
                if due_cycle_id is not None and rec.observation_id is not None:
                    # The close for the prior effective session is now
                    # published and ready.  Bind the fresh post-close broker
                    # observation before a new plan supersedes its evidence.
                    trial.record_account_evidence(
                        conn,
                        session=through_date,
                        observation_id=rec.observation_id,
                        observed_at=observation_time,
                        snapshot=account,
                        deployment=binding.identity,
                        reconciliation=rec,
                        activity_state=activity_state,
                        plan_target=existing_plan.target_basket,
                        target_actions=_target_action_multipliers(
                            existing_plan, _target_action_lookup(
                                conn, existing_plan, through_date)),
                    )
                    trial.record_cycle_verification(
                        conn,
                        cycle_id=due_cycle_id,
                        observation_id=rec.observation_id,
                        now=observation_time,
                    )
            if any(order.is_working for order in observation.orders):
                raise PaperActivationRefused(
                    "initial plan adoption requires no working broker order; "
                    "settle or explicitly resolve the prior durable command "
                    "before establishing the account-cash baseline")

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
                    publication_version=pinned.version)
                warmed = warmup_sessions
            else:
                state = SessionState.from_dict(raw)
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
    """Material supported share changes in the exact target-validity window."""
    result = {}
    for security_id in sorted(plan.target_basket):
        multiplier = actions(security_id)
        if multiplier not in (None, Decimal(1)):
            result[security_id] = multiplier
    return result


def _refuse_target_changing_actions(state: SessionState, plan: ExecutionPlan,
                                    actions) -> None:
    """Corporate actions may explain holdings; they may not rewrite intent.

    A share-count multiplier between decision close and execution makes the
    durable share basket stale. Reconciliation correctly ages its expected
    holdings, but driving those post-split holdings back to the pre-split target
    would manufacture a trade. The current activation gateway has no immutable
    corporate-action reprojection record, so it refuses instead.
    """
    affected = {
        security_id: actions(security_id)
        for security_id in sorted(
            set(plan.target_basket) | set(shadow_target(state).shares))
        if actions(security_id) not in (None, Decimal(1))
    }
    if affected:
        raise PaperActivationRefused(
            "corporate action(s) changed target share counts after the durable "
            f"decision: {affected}. Re-prepare a current decision; the gateway "
            "will not trade a pre-action share basket against post-action "
            "holdings")


async def _instrument_map(conn, broker: ExecutionBroker, state: SessionState,
                          plan: ExecutionPlan,
                          observation: BrokerObservation
                          ) -> dict[str, BrokerInstrument]:
    target = shadow_target(state)
    symbols = dict(target.tickers)
    symbols[DEFENSIVE_SECURITY_ID] = DEFENSIVE_SYMBOL
    meta = load_meta(conn)
    for security_id in plan.target_basket:
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
    all_security_ids = set(plan.target_basket) | set(held)
    effective_current = {
        security_id: held.get(security_id, Decimal(0)) + committed_quantity(
            observation.working_orders_for(security_id))
        for security_id in all_security_ids
    }
    needed = {
        security_id for security_id in all_security_ids
        if plan.target_basket.get(security_id, Decimal(0))
        != effective_current[security_id]
    }
    unresolved = []
    for security_id in sorted(needed):
        current = instruments.get(security_id)
        increasing = (plan.target_basket.get(security_id, Decimal(0))
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
        automation_config_sha256: str | None = None) -> ExecutionResult:
    """One durable-plan gateway shared by manual and automation grants."""
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)
    if (isinstance(grant, AutomationExecutionGrant)
            and grant.operation_scope != "EXECUTE"):
        raise PaperActivationRefused(
            "automation execution requires an EXECUTE-scoped grant")
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
                automation_config_sha256=automation_config_sha256)

            account = await broker.account_snapshot()
            _account_or_refuse(account, binding, confirmed_account)
            activity_state = await _broker_cash_state_or_refuse(
                conn, broker=broker, binding=binding, through=clock())
            actions = _action_lookup(conn, state, today)
            target_actions = _target_action_lookup(conn, plan, today)
            _refuse_target_changing_actions(state, plan, target_actions)
            preflight = await reconciliation.reconcile(
                broker=broker, conn=conn, binding=None,
                deployment=binding.identity, actions=actions)
            observation = _clean_or_refuse(
                preflight, purpose="paper execution")
            _cash_authority_or_refuse(
                conn, plan=plan, deployment=binding.identity,
                account=account, observation=observation,
                activity_state=activity_state)
            instruments = await _instrument_map(
                conn, broker, state, plan, observation)

            async def authorize_increases(fresh_observation):
                fresh_account = await broker.account_snapshot()
                _account_or_refuse(
                    fresh_account, binding, confirmed_account)
                fresh_activity_state = await _broker_cash_state_or_refuse(
                    conn, broker=broker, binding=binding, through=clock())
                _cash_authority_or_refuse(
                    conn, plan=plan, deployment=binding.identity,
                    account=fresh_account, observation=fresh_observation,
                    activity_state=fresh_activity_state)

            session = await executor.execute_session(
                broker=broker, conn=conn, deployment=binding.identity,
                plan=plan, instruments=instruments, today=today,
                actions=actions, increase_authority=authorize_increases)
            final_reconciliation = session.reconciliation
            if (final_reconciliation is not None
                    and final_reconciliation.runtime_state is RuntimeState.RUNNING
                    and final_reconciliation.clean
                    and final_reconciliation.observation is not None
                    and final_reconciliation.observation.is_complete
                    and final_reconciliation.observation_id is not None):
                evidence_at = clock()
                evidence_account = await broker.account_snapshot()
                _account_or_refuse(
                    evidence_account, binding, confirmed_account)
                evidence_activity = await _broker_cash_state_or_refuse(
                    conn, broker=broker, binding=binding,
                    through=evidence_at)
                _cash_authority_or_refuse(
                    conn, plan=plan, deployment=binding.identity,
                    account=evidence_account,
                    observation=final_reconciliation.observation,
                    activity_state=evidence_activity)
                trial.record_account_evidence(
                    conn, session=plan.effective_session,
                    observation_id=final_reconciliation.observation_id,
                    observed_at=evidence_at, snapshot=evidence_account,
                    deployment=binding.identity,
                    reconciliation=final_reconciliation,
                    activity_state=evidence_activity,
                    plan_target=plan.target_basket,
                    target_actions=_target_action_multipliers(
                        plan, target_actions))
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
        today: date | datetime | None = None) -> ExecutionResult:
    """Execute the same current plan through a fenced automation grant."""
    return await _execute_current_paper_plan(
        conn=conn, broker=broker, base_url=base_url, grant=grant,
        today=today, automation_config_sha256=automation_config_sha256)


async def recover_automated_paper_cycle(
        *, conn, broker: ExecutionBroker, base_url: str,
        grant: AutomationExecutionGrant,
        automation_config_sha256: str):
    """Read-only reconciliation for restart/pre-publication automation recovery."""
    if grant.operation_scope != "RECOVER":
        raise PaperActivationRefused(
            "automation recovery requires a RECOVER-scoped grant")
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
            automation_config_sha256=automation_config_sha256)
        account = await broker.account_snapshot()
        _recovery_account_identity_or_refuse(
            account, binding, grant.broker_account_id)
        activity_state = await _broker_cash_state_or_refuse(
            conn, broker=broker, binding=binding, through=clock())
        raw = catchup.resume_state(conn)
        state = SessionState.from_dict(raw) if raw is not None else None
        actions = (_action_lookup(conn, state, clock().date())
                   if state is not None else None)
        result = await reconciliation.reconcile(
            broker=broker, conn=conn, binding=None,
            deployment=binding.identity, actions=actions)
        if (cycle.control_generation == grant.control_generation
                and cycle.plan_id is not None
                and result.runtime_state is RuntimeState.RUNNING
                and result.clean
                and result.observation is not None
                and result.observation.is_complete
                and result.observation_id is not None):
            plan = journal.load_plan(conn, cycle.plan_id)
            if plan is not None and plan.fingerprint() == cycle.plan_fingerprint:
                evidence_at = clock()
                account = await broker.account_snapshot()
                _account_or_refuse(account, binding, grant.broker_account_id)
                activity_state = await _broker_cash_state_or_refuse(
                    conn, broker=broker, binding=binding,
                    through=evidence_at)
                _cash_authority_or_refuse(
                    conn, plan=plan, deployment=binding.identity,
                    account=account, observation=result.observation,
                    activity_state=activity_state,
                    # Recovery submits nothing. A recognized post-plan
                    # dividend/interest/fee is legitimate realized economics;
                    # it may be certified after the book is clean even though
                    # it would refuse a stale plan's new BUY authorization.
                    permit_new_activity=True)
                trial.record_account_evidence(
                    conn, session=cycle.effective_session,
                    observation_id=result.observation_id,
                    observed_at=evidence_at, snapshot=account,
                    deployment=binding.identity, reconciliation=result,
                    activity_state=activity_state,
                    plan_target=plan.target_basket,
                    target_actions=_target_action_multipliers(
                        plan, _target_action_lookup(
                            conn, plan, cycle.effective_session)))
        return result


def current_paper_plan(conn, *, base_url: str = DEFAULT_BASE_URL) -> dict:
    """Inspect current durable authorities without contacting the broker."""
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
            state.data_version == plan.data_version == current.version
            and plan.publication_fingerprint
            == publication_fingerprint(current)),
        "account_matches_plan": (
            plan.deployment_id == binding.deployment_id
            and plan.broker == binding.broker
            and plan.broker_account_id == binding.broker_account_id
            and plan.takeover_epoch == binding.takeover_epoch),
        "strategy_matches_runtime": (
            state.strategy_identity == runtime_identity
            and _hash(state.strategy_identity)
            == plan.strategy_fingerprint),
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
    "PaperActivationRefused", "PaperRetryableRefused", "PreparationResult",
    "build_security_resolver",
    "current_paper_plan", "execute_automated_paper_plan",
    "execute_paper_plan", "inspect_paper_account", "prepare_paper_plan",
    "recover_automated_paper_cycle",
]
