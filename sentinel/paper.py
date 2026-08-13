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

from sentinel import binding as binding_mod, schema
from sentinel.config import assert_paper_url
from sentinel.controller.frozen_rule import ControllerConfig, load as load_controller
from sentinel.controller.machine import Controller
from sentinel.core import catchup
from sentinel.core.decision import (
    DEFENSIVE_SECURITY_ID,
    build_execution_plan,
    publication_fingerprint,
    runtime_strategy_identity,
    shadow_target,
)
from sentinel.core.loader import load_meta, load_window
from sentinel.core.production import (
    SessionState,
    advance_and_persist,
    load_published_session,
    warm_session_state,
)
from sentinel.execution import executor, journal
from sentinel.execution import reconcile as reconciliation
from sentinel.execution.certification import require_certified
from sentinel.execution.commands import committed_quantity
from sentinel.execution.contract import (
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    ExecutionBroker,
)
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import RuntimeState
from sentinel.feed import calendar, publication, readiness, store as feed_store

DEFENSIVE_SYMBOL = "BIL"


class PaperActivationRefused(RuntimeError):
    """A preparation or execution authority check failed."""


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
    raise PaperActivationRefused(f"corpus readiness failed: {detail}")


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
        raise PaperActivationRefused(
            f"paper execution time {now_et.isoformat()} is outside the "
            f"certified XNYS execution window for {session}: "
            f"[{opened.isoformat()}, {closed.isoformat()}). The gateway will "
            "not queue a DAY order before the open or after the close.")


def _clean_or_refuse(result, *, purpose: str) -> BrokerObservation:
    observation = result.observation
    if (result.runtime_state is not RuntimeState.RUNNING or not result.clean
            or observation is None or not observation.is_complete):
        raise PaperActivationRefused(
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
        raise PaperActivationRefused(
            f"paper account status is {snapshot.status!r}, not ACTIVE")
    blocked = [
        name for name in (
            "trading_blocked", "account_blocked", "trade_suspended_by_user")
        if getattr(snapshot, name)
    ]
    if blocked:
        raise PaperActivationRefused(
            "paper account is not available for submission: "
            + ", ".join(blocked))
    if abs(snapshot.buying_power - snapshot.cash) > Decimal("1.00"):
        raise PaperActivationRefused(
            f"paper account buying power {snapshot.buying_power} does not "
            f"match cash {snapshot.cash}. Lower buying power is unsettled; "
            "higher buying power exposes margin. Increases wait for cash-only "
            "settlement")


def _cash_authority_or_refuse(conn, *, plan: ExecutionPlan, deployment,
                              account: BrokerAccountSnapshot,
                              observation: BrokerObservation) -> None:
    """Reconcile the immutable cash baseline to this plan's durable fills.

    Equity moves when holdings are marked and is therefore not an overnight
    cash-flow witness. Cash moves only when money or a fill crosses the account.
    Initial plan adoption forbids pre-existing working orders, so every later
    fill under the plan has a complete durable command and a persisted
    broker-observed average price with which to explain that movement.
    """
    expected = plan.account_cash
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
        expected += notional if command.side.value == "SELL" else -notional
    if abs(account.cash - expected) > Decimal("1.00"):
        raise PaperActivationRefused(
            f"fresh account cash {account.cash} is not explained by plan "
            f"baseline {plan.account_cash} and durable fills (expected "
            f"{expected}). This activation gateway cannot re-project an "
            "adopted plan for a same-session cash flow: leave the plan "
            "unexecuted, resolve and record the flow separately, and prepare "
            "from the next closed decision session. Cash movement is never "
            "inferred")


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


async def prepare_paper_plan(*, conn, broker: ExecutionBroker, base_url: str,
                             through: date | str,
                             expected_account: Optional[str] = None,
                             warmup_sessions: int = 252,
                             controller_config: ControllerConfig | None = None,
                             strategy_identity: Mapping | None = None,
                             now_et: datetime | None = None,
                             ) -> PreparationResult:
    """Advance and adopt one current plan without any broker mutation."""
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)
    schema.ensure_schema(conn)
    through_date = (through if isinstance(through, date)
                    else date.fromisoformat(str(through)))
    through_text = through_date.isoformat()
    config = controller_config or load_controller()
    identity = dict(strategy_identity or runtime_strategy_identity(config))

    with journal.writer_lock(conn):
        # Ownership is checked under the same lock as plan adoption and before
        # the first broker read. An unbound inherited book is migration input,
        # never something daily preparation may adopt.
        from sentinel.handover import assert_no_legacy_path
        binding = assert_no_legacy_path(conn)
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
                    runtime_identity=identity, require_effective_today=False)
                rec = await reconciliation.reconcile(
                    broker=broker, conn=conn, binding=None,
                    deployment=binding.identity,
                    actions=_action_lookup(conn, state, through_date))
                observation = _clean_or_refuse(
                    rec, purpose="paper preparation restart")
                account = await broker.account_snapshot()
                _account_or_refuse(account, binding, expected_account)
                _cash_authority_or_refuse(
                    conn, plan=existing_plan, deployment=binding.identity,
                    account=account, observation=observation)
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
                        calendar.next_session(session)))
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
                             runtime_identity: Mapping,
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
        except Exception as exc:                              # noqa: BLE001
            raise PaperActivationRefused(
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


async def execute_paper_plan(*, conn, broker: ExecutionBroker, base_url: str,
                             confirm_account: str, confirm_plan_id: str,
                             confirm_effective_session: date | str,
                             confirm_submit: bool,
                             today: date | datetime | None = None
                             ) -> ExecutionResult:
    """Execute only the durable current paper plan after explicit confirmation."""
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)
    if not confirm_submit:
        raise PaperActivationRefused(
            "--confirm-submit-paper-orders is required")
    effective = (confirm_effective_session
                 if isinstance(confirm_effective_session, date)
                 else date.fromisoformat(str(confirm_effective_session)))
    now_et = _execution_observation_time(today)
    today = now_et.date()
    schema.ensure_schema(conn)

    with journal.writer_lock(conn):
        from sentinel.handover import assert_no_legacy_path
        binding = assert_no_legacy_path(conn)
        with publication.pinned(conn, commit=False) as pinned:
            _readiness_or_refuse(conn, now_et=now_et)
            frontier = feed_store.latest_visible_session(conn)
            state, plan, _cursor = _state_and_plan_or_refuse(conn)
            if confirm_account != binding.broker_account_id:
                raise PaperActivationRefused("paper-account confirmation mismatch")
            if confirm_plan_id != plan.plan_id:
                raise PaperActivationRefused("plan-id confirmation mismatch")
            if effective != plan.effective_session:
                raise PaperActivationRefused("effective-session confirmation mismatch")
            _assert_plan_authorities(
                conn, state=state, plan=plan, binding=binding, pinned=pinned,
                frontier=str(frontier), today=today,
                runtime_identity=runtime_strategy_identity(load_controller()))
            # Strict activation executes only during the named exchange
            # session. This is before the first broker read and consults the
            # actual XNYS schedule, so a 13:00 half-day close is a hard stop.
            _execution_window_or_refuse(plan.effective_session, now_et)

            account = await broker.account_snapshot()
            _account_or_refuse(account, binding, confirm_account)
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
                account=account, observation=observation)
            instruments = await _instrument_map(
                conn, broker, state, plan, observation)

            async def authorize_increases(fresh_observation):
                fresh_account = await broker.account_snapshot()
                _account_or_refuse(
                    fresh_account, binding, confirm_account)
                _cash_authority_or_refuse(
                    conn, plan=plan, deployment=binding.identity,
                    account=fresh_account,
                    observation=fresh_observation)

            session = await executor.execute_session(
                broker=broker, conn=conn, deployment=binding.identity,
                plan=plan, instruments=instruments, today=today,
                actions=actions, increase_authority=authorize_increases)
            return ExecutionResult(plan=plan, preflight=preflight,
                                   session=session)


def current_paper_plan(conn) -> dict:
    """Inspect current durable authorities without contacting the broker."""
    state, plan, cursor = _state_and_plan_or_refuse(conn)
    from sentinel.handover import assert_no_legacy_path
    binding = assert_no_legacy_path(conn)
    current = publication.require_current(conn)
    frontier = feed_store.latest_visible_session(conn)
    runtime_identity = runtime_strategy_identity(load_controller())
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
    }
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
    "PaperActivationRefused", "PreparationResult", "build_security_resolver",
    "current_paper_plan", "execute_paper_plan", "inspect_paper_account",
    "prepare_paper_plan",
]
