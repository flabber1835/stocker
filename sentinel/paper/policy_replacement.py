"""Attended, pre-open replacement of wholly unsent PAPER intent."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hmac
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinel import dual_plan_authority, local_paper
from sentinel.automation import store
from sentinel.execution import journal
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.states import CommandState, IN_FLIGHT
from sentinel.feed import calendar, publication
from sentinel.paper.model import PaperActivationRefused as Refused

PREFIX = 'unsent-paper-policy-replacement:v1:'
SCHEMA = 'sentinel.unsent-paper-policy-replacement/1'


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    plan_id: str = Field(pattern=r'^sentinel-[0-9a-f]{64}$')
    plan_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    confirm_unsent_policy_replacement: Literal[True]

    @field_validator('actor', 'reason')
    @classmethod
    def exact_text(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError('replacement actor and reason must be nonblank and exact')
        return value

    @field_validator('confirm_unsent_policy_replacement', mode='before')
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError('unsent policy replacement requires explicit confirmation')
        return value


class Receipt(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    schema_id: Literal['sentinel.unsent-paper-policy-replacement/1'] = SCHEMA
    request: Request
    successor_plan_id: str
    successor_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    previous_authority_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    successor_authority_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    previous_policy_sha256: str | None
    successor_policy_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    shadow_record_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    certificate_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    control_generation: int = Field(ge=0)
    decision_session: date
    recorded_at: datetime
    broker_mutations: Literal[0] = 0


def _signature(value):
    return publication._receipt_hmac({'purpose': SCHEMA, 'receipt': value})


def require_quiescent(conn, *, plan, now):
    """Recheck under the canonical writer; it grants no broker transport."""
    if not local_paper.require_bound_account(conn):
        raise Refused('policy replacement requires the bound owner PAPER account')
    control = store.load_control(conn, for_update=True)
    live_lease = conn.execute('SELECT EXISTS(SELECT 1 FROM sentinel_automation_lease '
        'WHERE holder_id IS NOT NULL AND expires_at>clock_timestamp())').fetchone()[0]
    if control.enabled or not control.kill_switch_engaged or live_lease:
        raise Refused('policy replacement requires disabled, killed automation with no live leader')
    opened = calendar.session_window(plan.effective_session)[0]
    if now.utcoffset() is None or now >= opened:
        raise Refused('policy replacement is only available before the regular open')
    return control.generation


def require_unsent(conn, plan):
    """A PLANNED label cannot erase transport/recovery history or fills."""
    deployment = DeploymentIdentity(plan.deployment_id, plan.broker,
                                    plan.broker_account_id, plan.takeover_epoch)
    _require_unsent_history(conn, plan, deployment)
    if conn.execute('SELECT EXISTS(SELECT 1 FROM sentinel_commands WHERE broker=%s '
            'AND broker_account_id=%s AND state=ANY(%s::text[]))',
            (plan.broker, plan.broker_account_id, sorted(s.value for s in IN_FLIGHT))).fetchone()[0]:
        raise Refused('policy replacement waits for unresolved account commands')


def _require_unsent_history(conn, plan, deployment, *, retired=False):
    allowed = {CommandState.PLANNED, CommandState.SUPERSEDED} if retired else {CommandState.PLANNED}
    for command in journal.load_commands(conn, deployment, plan_id=plan.plan_id):
        if (command.state not in allowed or command.filled_quantity != 0
                or command.broker_order_id is not None or command.recovered_key is not None):
            raise Refused('policy replacement requires wholly unsent commands')
        history = journal.command_history(conn, command.client_key)
        if not history or any(event['from'] not in (None, 'PLANNED') or event['to'] not in {s.value for s in allowed}
                or event['filled'] is not None and Decimal(event['filled']) != 0 for event in history):
            raise Refused('policy replacement refuses command transport or recovery history')
        if conn.execute('SELECT EXISTS(SELECT 1 FROM sentinel_fills WHERE client_key=%s)',
                        (command.client_key,)).fetchone()[0]:
            raise Refused('policy replacement refuses retained fill evidence')


def _authenticated(raw):
    if (not isinstance(raw, dict) or set(raw) != {'receipt', 'hmac_sha256'}
            or not isinstance(raw['receipt'], dict)
            or set(raw['receipt']) != set(Receipt.model_fields)
            or not hmac.compare_digest(str(raw['hmac_sha256']), _signature(raw['receipt']))):
        raise Refused('policy replacement receipt authentication failed')
    try:
        return Receipt.model_validate_json(json.dumps(raw['receipt']))
    except ValueError as exc:
        raise Refused('policy replacement receipt is malformed') from exc


def _validate_retained(conn, receipt):
    old = journal.load_plan(conn, receipt.request.plan_id)
    new = journal.load_plan(conn, receipt.successor_plan_id)
    prior = dual_plan_authority.load_authority(conn, plan_id=receipt.request.plan_id)
    current = dual_plan_authority.load_authority(conn, plan_id=receipt.successor_plan_id)
    if (old is None or new is None or prior is None or current is None
            or old.fingerprint() != receipt.request.plan_fingerprint
            or new.fingerprint() != receipt.successor_fingerprint
            or old.plan_id == new.plan_id or old.superseded_by != new.plan_id
            or prior['plan_fingerprint'] != old.fingerprint()
            or current['plan_fingerprint'] != new.fingerprint()
            or prior['authority_sha256'] != receipt.previous_authority_sha256
            or current['authority_sha256'] != receipt.successor_authority_sha256
            or prior.get('market_buy_policy_sha256') != receipt.previous_policy_sha256
            or current.get('market_buy_policy_sha256') != receipt.successor_policy_sha256
            or receipt.successor_policy_sha256 != MarketBuyPolicy(fractional=True).fingerprint()
            or receipt.previous_policy_sha256 == receipt.successor_policy_sha256
            or prior['shadow_record_sha256'] != current['shadow_record_sha256']
            or current['shadow_record_sha256'] != receipt.shadow_record_sha256
            or old.decision_session != new.decision_session
            or new.decision_session != receipt.decision_session
            or new.rollout_certificate_sha256 != receipt.certificate_sha256
            or old.rollout_certificate_sha256 == receipt.certificate_sha256
            or old.rollout_version >= new.rollout_version
            or old.rollout_mode != 'CONTROLLER' or new.rollout_mode != 'CONTROLLER'
            or old.shadow_snapshot_hash != new.shadow_snapshot_hash
            or old.publication_fingerprint != new.publication_fingerprint
            or (old.deployment_id, old.broker, old.broker_account_id, old.takeover_epoch)
               != (new.deployment_id, new.broker, new.broker_account_id, new.takeover_epoch)):
        raise Refused('policy replacement receipt differs from its retained plans or authorities')
    # Only predecessor history must remain unsent. The successor may subsequently execute.
    _require_unsent_history(conn, old, DeploymentIdentity(old.deployment_id,
        old.broker, old.broker_account_id, old.takeover_epoch), retired=True)


def pending_request(conn, *, request, plan, decision_session, policy, rollout, now):
    if plan is None or decision_session != plan.decision_session:
        raise Refused('policy replacement requires the current same-decision plan')
    if policy != MarketBuyPolicy(fractional=True):
        raise Refused('policy replacement requires the selected fractional market policy')
    require_quiescent(conn, plan=plan, now=now)
    row = conn.execute('SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                       (PREFIX + request.plan_id,)).fetchone()
    if row is not None:
        receipt = _authenticated(row[1])
        _validate_retained(conn, receipt)
        if (row[0] != receipt.decision_session or receipt.request != request
                or plan.plan_id != receipt.successor_plan_id
                or (plan.rollout_mode, plan.rollout_version, plan.rollout_certificate_sha256)
                   != (rollout.mode.value, rollout.version, rollout.certificate_sha256)):
            raise Refused('policy replacement request differs from its current retained successor')
        return None
    if plan.plan_id != request.plan_id or plan.fingerprint() != request.plan_fingerprint:
        raise Refused('policy replacement does not name the exact current plan')
    require_unsent(conn, plan)
    previous = dual_plan_authority.load_authority(conn, plan_id=plan.plan_id)
    if (previous is None or previous.get('market_buy_policy_sha256') == policy.fingerprint()
            or previous.get('held_share_targets') is None):
        raise Refused('policy replacement requires a quantity policy and original held-share basis')
    return request


def record(conn, *, request, previous, successor, now):
    generation = require_quiescent(conn, plan=previous, now=now)
    require_unsent(conn, previous)
    prior = dual_plan_authority.load_authority(conn, plan_id=previous.plan_id)
    current = dual_plan_authority.load_authority(conn, plan_id=successor.plan_id)
    receipt = Receipt(request=request, successor_plan_id=successor.plan_id,
        successor_fingerprint=successor.fingerprint(),
        previous_authority_sha256=prior['authority_sha256'],
        successor_authority_sha256=current['authority_sha256'],
        previous_policy_sha256=prior.get('market_buy_policy_sha256'),
        successor_policy_sha256=current['market_buy_policy_sha256'],
        shadow_record_sha256=current['shadow_record_sha256'],
        certificate_sha256=successor.rollout_certificate_sha256,
        control_generation=generation, decision_session=successor.decision_session,
        recorded_at=now)
    _validate_retained(conn, receipt)
    value = receipt.model_dump(mode='json')
    conn.execute('INSERT INTO sentinel_processed_sessions (cursor_name,session,state) '
        'VALUES (%s,%s,%s::jsonb)', (PREFIX + request.plan_id, successor.decision_session,
        json.dumps(dict(receipt=value, hmac_sha256=_signature(value)))))


def verify_receipts(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT cursor_name,session,state '
                    'FROM sentinel_processed_sessions WHERE cursor_name LIKE %s', (PREFIX + '%',))
        rows = cur.fetchall()
    for name, session, raw in rows:
        receipt = _authenticated(raw)
        if name != PREFIX + receipt.request.plan_id or session != receipt.decision_session:
            raise Refused('policy replacement receipt is stored under another identity')
        _validate_retained(conn, receipt)
