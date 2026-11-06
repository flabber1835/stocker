"""Attended prospective cash anchor; never repair a legacy plan's baseline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
import hmac
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinel.automation import store
from sentinel.execution import broker_cash, journal
from sentinel.execution.guarded import GuardedExecutionBroker, PaperPreparationGrant
from sentinel.execution.identity import DeploymentIdentity
from sentinel.feed import calendar, publication
from sentinel.feed.rolling_contract import digest
from sentinel.paper.cash import _account_economics, _observation_economics
from sentinel.paper.model import PaperActivationRefused as Refused

PREFIX = 'broker-cash-retirement:v1:'
SCHEMA = 'sentinel.unsent-paper-cash-retirement/1'


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    plan_id: str = Field(min_length=1)
    plan_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    native_activity_id: str = Field(min_length=1)
    observed_cash: str
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    confirm_prospective_retirement: Literal[True]

    @field_validator('confirm_prospective_retirement', mode='before')
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError('prospective retirement requires explicit confirmation')
        return value

    @field_validator('plan_id', 'native_activity_id', 'actor', 'reason')
    @classmethod
    def nonblank(cls, value):
        if value != value.strip() or not value:
            raise ValueError('retirement confirmations must be nonblank and exact')
        return value

    @field_validator('observed_cash')
    @classmethod
    def cash(cls, value):
        try:
            parsed = Decimal(value)
        except ArithmeticError as exc:
            raise ValueError('retirement cash must be Decimal') from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValueError('retirement cash must be finite and unlevered')
        return value


class Receipt(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    schema_id: Literal['sentinel.unsent-paper-cash-retirement/1'] = SCHEMA
    request: Request
    successor_plan_id: str
    successor_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    successor_baseline: dict
    binding: dict
    decision_session: date
    observed_at: datetime
    certificate_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    control_generation: int = Field(ge=1)
    native_flow: dict
    account_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    book_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    activity_state: dict
    historical_cash_interval: Literal['UNVERIFIED'] = 'UNVERIFIED'
    broker_mutations: Literal[0] = 0


def _signature(value):
    return publication._receipt_hmac({'purpose': SCHEMA, 'receipt': value})


def _claim(request, binding):
    return PREFIX + 'native:' + digest({
        'broker': binding['broker'], 'account': binding['broker_account_id'],
        'native_activity_id': request.native_activity_id})


def _state(value):
    return dict(broker=value.broker, account_id=value.account_id,
        processed_through=value.processed_through.isoformat(),
        last_activity_id=value.last_activity_id, last_event_id=value.last_event_id,
        balance_total=str(value.balance_total),
        activity_identity_scheme=value.activity_identity_scheme)


def _baseline(value):
    return dict(plan_id=value.plan_id, broker=value.broker, account_id=value.account_id,
        decision_session=str(value.decision_session),
        processed_through=value.processed_through.isoformat(),
        balance_total=str(value.balance_total), last_activity_id=value.last_activity_id,
        activity_identity_scheme=value.activity_identity_scheme)


def pending_request(conn, request, current_plan, *, decision_session):
    """Authenticate a completed request on restart; ordinary cash checks follow."""
    request = Request.model_validate(request)
    row = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                       (PREFIX + request.plan_id,)).fetchone()
    if row is None:
        if current_plan is None or current_plan.plan_id != request.plan_id:
            raise Refused('cash retirement does not name the current legacy plan')
        if (decision_session <= current_plan.decision_session
                or broker_cash.load_plan_baseline(conn, plan_id=current_plan.plan_id) is not None):
            raise Refused('cash retirement requires a later decision and a missing legacy baseline')
        return request
    receipt = _authenticated(row[0])
    _validate_retained(conn, receipt, row[0])
    if (receipt.request != request or current_plan is None
            or current_plan.plan_id != receipt.successor_plan_id
            or current_plan.fingerprint() != receipt.successor_fingerprint):
        raise Refused('cash retirement request differs from its current retained successor')
    return None


def _authenticated(raw):
    if (not isinstance(raw, dict) or set(raw) != {'receipt', 'hmac_sha256'}
            or not isinstance(raw['receipt'], dict)
            or set(raw['receipt']) != set(Receipt.model_fields)
            or not hmac.compare_digest(str(raw['hmac_sha256']), _signature(raw['receipt']))):
        raise Refused('cash retirement receipt authentication failed')
    try:
        receipt = Receipt.model_validate_json(json.dumps(raw['receipt']))
    except ValueError as exc:
        raise Refused('cash retirement receipt is malformed') from exc
    return receipt


def _validate_retained(conn, receipt, raw):
    request = receipt.request
    old = journal.load_plan(conn, request.plan_id)
    successor = journal.load_plan(conn, receipt.successor_plan_id)
    baseline = broker_cash.load_plan_baseline(conn, plan_id=receipt.successor_plan_id)
    claim = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                        (_claim(request, receipt.binding),)).fetchone()
    if (old is None
            or old.fingerprint() != request.plan_fingerprint
            or old.superseded_by != receipt.successor_plan_id
            or successor is None or successor.fingerprint() != receipt.successor_fingerprint
            or baseline is None or _baseline(baseline) != receipt.successor_baseline
            or claim is None or claim[0] != raw):
        raise Refused('cash retirement receipt differs from its retained plans or native claim')
    deployment = DeploymentIdentity(old.deployment_id, old.broker, old.broker_account_id, old.takeover_epoch)
    native = receipt.native_flow
    flow = conn.execute('SELECT session,amount,detail FROM sentinel_cash_flows WHERE flow_id=%s',
        (broker_cash.broker_flow_id(broker=old.broker, account_id=old.broker_account_id,
            activity_id=request.native_activity_id),)).fetchone()
    if (broker_cash.load_plan_baseline(conn, plan_id=old.plan_id) is not None
            or journal.load_commands(conn, deployment, plan_id=old.plan_id)
            or receipt.binding['broker'] != old.broker
            or receipt.binding['broker_account_id'] != old.broker_account_id
            or successor.broker != old.broker or successor.broker_account_id != old.broker_account_id
            or successor.decision_session <= old.decision_session
            or successor.account_cash != Decimal(request.observed_cash)
            or flow is None or native != dict(
                flow_id=broker_cash.broker_flow_id(broker=old.broker, account_id=old.broker_account_id,
                    activity_id=request.native_activity_id),
                session=str(flow[0]), amount=str(flow[1]), detail=flow[2])
            or Fraction(successor.account_cash) - Fraction(old.account_cash) != Fraction(flow[1])):
        raise Refused('cash retirement retained native cash evidence is incomplete or changed')


def verify_retirements(conn):
    """Restore-time read-only validation, including orphaned native claims."""
    with conn.cursor() as cur:
        cur.execute('SELECT cursor_name,state FROM sentinel_processed_sessions '
            'WHERE cursor_name LIKE %s ORDER BY cursor_name', (PREFIX + '%',))
        rows = cur.fetchall()
    expected = set()
    for name, raw in rows:
        receipt = _authenticated(raw)
        _validate_retained(conn, receipt, raw)
        expected.update((PREFIX + receipt.request.plan_id, _claim(receipt.request, receipt.binding)))
        if name not in (PREFIX + receipt.request.plan_id, _claim(receipt.request, receipt.binding)):
            raise Refused('cash retirement receipt is stored under another identity')
    if {name for name, _ in rows} != expected:
        raise Refused('cash retirement receipt/native claim pair is incomplete')


@dataclass(frozen=True)
class Prepared:
    request: Request
    value: dict


def qualify(conn, *, request, plan, binding, grant, broker, decision_session,
            account, observation, activity_state, observed_at, now,
            certificate_sha256):
    """Caller holds the canonical writer and supplies the canonical settled bracket."""
    request = Request.model_validate(request)
    if (not isinstance(grant, PaperPreparationGrant) or grant.decision_session != decision_session
            or not isinstance(broker, GuardedExecutionBroker) or broker.grant != grant
            or not broker.supports_account_cash_activities or not broker.financial_activity_sse):
        raise Refused('cash retirement requires attended guarded accepted PAPER cash reads')
    control = store.load_control(conn, for_update=True)
    live_lease = conn.execute('SELECT EXISTS(SELECT 1 FROM sentinel_automation_lease '
        'WHERE holder_id IS NOT NULL AND expires_at>clock_timestamp())').fetchone()[0]
    if control.enabled or not control.kill_switch_engaged or live_lease:
        raise Refused('cash retirement requires disabled, killed automation with no live leader')
    if (binding.broker != 'alpaca' or grant.expected_account != binding.broker_account_id
            or (plan.deployment_id, plan.broker, plan.broker_account_id, plan.takeover_epoch)
            != (binding.deployment_id, binding.broker, binding.broker_account_id, binding.takeover_epoch)
            or request.plan_id != plan.plan_id or request.plan_fingerprint != plan.fingerprint()):
        raise Refused('cash retirement plan/account confirmation differs')
    if (now.tzinfo is None or observed_at.tzinfo is None
            or not timedelta(0) <= now - observed_at <= timedelta(seconds=30)
            or decision_session.isoformat() != calendar.latest_closed_session(now)
            or decision_session <= plan.decision_session
            or now >= calendar.session_window(calendar.next_session(str(decision_session)))[0]):
        raise Refused('cash retirement requires a later actual closed decision and future open')
    if (broker_cash.load_plan_baseline(conn, plan_id=plan.plan_id) is not None
            or journal.load_commands(conn, binding.identity, plan_id=plan.plan_id)
            or journal.in_flight_commands(conn, binding.identity)
            or not observation.is_complete or any(o.is_working for o in observation.orders)):
        raise Refused('cash retirement requires a baseline-free plan with no dispatched intent or working order')
    if (activity_state is None or activity_state.broker != binding.broker
            or activity_state.account_id != binding.broker_account_id
            or activity_state.activity_identity_scheme != broker_cash.ACTIVITY_IDENTITY_SCHEME
            or activity_state.processed_through != observed_at
            or broker_cash.load_activity_state(conn, broker=binding.broker,
                account_id=binding.broker_account_id) != activity_state
            or observation.account_identity is None
            or (account.identity.broker, account.identity.account_id)
            != (observation.account_identity.broker, observation.account_identity.account_id)
            or (account.identity.broker, account.identity.account_id)
            != (binding.broker, binding.broker_account_id)
            or Decimal(request.observed_cash) != account.cash):
        raise Refused('cash retirement requires the exact accepted current cash bracket')
    flow_id = broker_cash.broker_flow_id(broker=binding.broker,
        account_id=binding.broker_account_id, activity_id=request.native_activity_id)
    flow = conn.execute('SELECT session,amount,detail FROM sentinel_cash_flows WHERE flow_id=%s',
                        (flow_id,)).fetchone()
    expected_detail = (f'{broker_cash.DETAIL_PREFIX}class=INTERNAL;type=DIV;'
                       f'id={request.native_activity_id}')
    if (flow is None or flow[0] > decision_session or flow[1] <= 0
            or flow[2] != expected_detail
            or Fraction(account.cash) - Fraction(plan.account_cash) != Fraction(flow[1])):
        raise Refused('cash retirement difference is not the confirmed native settled cash dividend')
    bound = binding.to_dict()
    if conn.execute('SELECT 1 FROM sentinel_processed_sessions WHERE cursor_name=%s',
                    (_claim(request, bound),)).fetchone() is not None:
        raise Refused('cash retirement native dividend was already consumed')
    return Prepared(request, dict(request=request.model_dump(), binding=bound,
        decision_session=decision_session, observed_at=observed_at,
        certificate_sha256=certificate_sha256,
        control_generation=control.generation,
        native_flow=dict(flow_id=flow_id, session=str(flow[0]), amount=str(flow[1]), detail=flow[2]),
        account_sha256=digest(_account_economics(account)),
        book_sha256=digest(_observation_economics(observation)), activity_state=_state(activity_state)))


def record(conn, *, prepared, successor):
    """Append with plan adoption/baseline in the caller's single transaction."""
    control = store.load_control(conn, for_update=True)
    live_lease = conn.execute('SELECT EXISTS(SELECT 1 FROM sentinel_automation_lease '
        'WHERE holder_id IS NOT NULL AND expires_at>clock_timestamp())').fetchone()[0]
    if (control.generation != prepared.value['control_generation'] or control.enabled
            or not control.kill_switch_engaged or live_lease):
        raise Refused('cash retirement lost its exact disabled/killed writer fence')
    baseline = broker_cash.load_plan_baseline(conn, plan_id=successor.plan_id)
    activity = prepared.value['activity_state']
    if (baseline is None or not baseline.activity_identity_authoritative
            or successor.plan_id == prepared.request.plan_id
            or successor.decision_session != prepared.value['decision_session']
            or successor.account_cash != Decimal(prepared.request.observed_cash)
            or any(getattr(baseline, key) != activity[key] for key in (
                'broker', 'account_id', 'last_activity_id', 'activity_identity_scheme'))
            or baseline.processed_through.isoformat() != activity['processed_through']
            or baseline.balance_total != Decimal(activity['balance_total'])):
        raise Refused('cash retirement successor lacks its own exact prospective cash anchor')
    receipt = Receipt(**prepared.value, successor_plan_id=successor.plan_id,
        successor_fingerprint=successor.fingerprint(), successor_baseline=_baseline(baseline))
    value = receipt.model_dump(mode='json')
    raw = {'receipt': value, 'hmac_sha256': _signature(value)}
    for cursor in (PREFIX + prepared.request.plan_id, _claim(prepared.request, receipt.binding)):
        inserted = conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) '
            'VALUES(%s,%s,%s::jsonb) ON CONFLICT DO NOTHING',
            (cursor, successor.decision_session, json.dumps(raw, sort_keys=True)))
        if inserted.rowcount != 1:
            raise Refused('cash retirement lost its atomic predecessor/native claim')
    return value
