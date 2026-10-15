"""Saved next-open intent for display/notification; never execution authority."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
import re

# A dated estimate survives the overnight wait. This is display authority only;
# the executor independently requires fresh broker evidence before any order.
MAX_OBSERVATION_AGE = timedelta(hours=26)


def quantity(value):
    if isinstance(value, bool):
        raise ValueError('boolean is not a planned quantity')
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or result.adjusted() > 18 or result.as_tuple().exponent < -30:
        raise ValueError('planned quantity is outside display bounds')
    return result


class PlannedLeg(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    security_id: str = Field(min_length=1,max_length=100)
    ticker: str = Field(min_length=1,max_length=100)
    current_quantity: Decimal | None
    target_quantity: Decimal
    change_quantity: Decimal | None
    opening_dollars: Decimal | None = None
    action: Literal['BUY','SELL','HOLD','UNAVAILABLE']

    @model_validator(mode='after')
    def bounded_values(self):
        for value in (self.current_quantity,self.target_quantity,self.opening_dollars):
            if value is not None:
                quantity(value)
        if self.change_quantity is not None:
            quantity(abs(self.change_quantity))
            if self.current_quantity is None or self.change_quantity != self.target_quantity-self.current_quantity:
                raise ValueError('planned share delta is inconsistent')
        return self


class PlanPreview(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    cycle_id: str = Field(min_length=1,max_length=100)
    plan_id: str = Field(min_length=1,max_length=100)
    decision_session: date
    effective_session: date
    execute_at: datetime
    created_at: datetime
    observation_at: datetime | None
    legs: list[PlannedLeg] = Field(max_length=100)

    @model_validator(mode='after')
    def coherent_dates(self):
        if self.effective_session <= self.decision_session:
            raise ValueError('planned effective session is not prospective')
        if any(value is not None and value.utcoffset() is None
               for value in (self.execute_at,self.created_at,self.observation_at)):
            raise ValueError('paper plan timestamps must have timezones')
        if len({leg.security_id for leg in self.legs}) != len(self.legs):
            raise ValueError('duplicate planned security')
        return self

    @property
    def buys(self):
        return sum(leg.action == 'BUY' for leg in self.legs)

    @property
    def sells(self):
        return sum(leg.action == 'SELL' for leg in self.legs)

    @property
    def trades(self):
        return self.buys + self.sells


def project(*, plan, positions, observation_at, tickers, now):
    if not isinstance(plan['target_basket'],dict) or len(plan['target_basket'])>100:
        raise ValueError('paper plan exceeds display holdings bound')
    if positions is not None and (not isinstance(positions,dict) or len(positions)>100):
        raise ValueError('broker positions exceed display holdings bound')
    targets = {str(key):quantity(value) for key,value in plan['target_basket'].items()}
    if len(targets) > 100 or positions is not None and len(positions) > 100:
        raise ValueError('paper plan exceeds display holdings bound')
    current = None
    if observation_at is not None and timedelta(0) <= now-observation_at <= MAX_OBSERVATION_AGE:
        current = {str(key):quantity(value) for key,value in positions.items()} if positions is not None else None
    openings = {}
    if plan.get('opening_intents'):
        raw = plan['opening_intents']
        if (set(raw) != {'kind','plan_id','plan_fingerprint','intents'}
                or raw.get('kind') != 'plan-opening-intents/v1' or raw.get('plan_id') != plan['plan_id']
                or not isinstance(raw.get('plan_fingerprint'),str)
                or not re.fullmatch('[0-9a-f]{64}',raw['plan_fingerprint'])
                or not isinstance(raw.get('intents'),list) or len(raw['intents']) > 100):
            raise ValueError('paper opening intent does not match the saved plan')
        slots = set()
        for item in raw['intents']:
            if (set(item) != {'security_id','slot_id','intended_dollars'}
                    or type(item['slot_id']) is not int or not 0 <= item['slot_id'] < 20):
                raise ValueError('paper opening intent shape is invalid')
            sid = item['security_id']
            dollars = quantity(item['intended_dollars'])
            if (not isinstance(sid, str) or sid in openings
                    or item['slot_id'] in slots or targets.get(sid) != 0 or dollars <= 0):
                raise ValueError('paper opening intent is contradictory')
            slots.add(item['slot_id'])
            openings[sid] = dollars
    legs = []
    for sid in sorted(set(targets) | set(current or {})):
        if not sid.strip():
            raise ValueError('planned security identity is empty')
        target = targets.get(sid,Decimal(0))
        held = current.get(sid,Decimal(0)) if current is not None else None
        delta = target-held if held is not None else None
        dollars = openings.get(sid)
        action = ('UNAVAILABLE' if held is None or dollars and held != 0 else 'BUY' if dollars or delta > 0
                  else 'SELL' if delta < 0 else 'HOLD')
        legs.append(PlannedLeg(security_id=sid,ticker=tickers.get(sid,sid),
            current_quantity=held,target_quantity=target,change_quantity=None if dollars else delta,
            opening_dollars=dollars,action=action))
    return PlanPreview(**{k:plan[k] for k in ('cycle_id','plan_id','decision_session',
        'effective_session','execute_at','created_at')},observation_at=observation_at,legs=legs)


def still_current(conn, *, cycle_id, plan_id):
    """Reject obsolete queued notifications without broker calls or writes."""
    with conn.cursor() as cur:
        cur.execute("""SELECT EXISTS (SELECT 1 FROM sentinel_automation_cycles c
            JOIN sentinel_automation_control a ON a.id=1 AND a.enabled AND NOT a.kill_switch_engaged
              AND a.generation=c.control_generation AND a.deployment_id=c.deployment_id
              AND a.broker=c.broker AND a.broker_account_id=c.broker_account_id
              AND a.takeover_epoch=c.takeover_epoch
            JOIN sentinel_execution_plans p ON p.plan_id=c.plan_id
              AND p.deployment_id=c.deployment_id AND p.broker=c.broker
              AND p.broker_account_id=c.broker_account_id AND p.takeover_epoch=c.takeover_epoch
              AND p.decision_session=c.decision_session AND p.effective_session=c.effective_session
            WHERE c.cycle_id=%s AND p.plan_id=%s AND c.state IN ('PLAN_READY','WAITING_OPEN')
              AND NOT c.historical_state_only AND p.superseded_by IS NULL
              AND c.execute_at>clock_timestamp())""", (cycle_id,plan_id))
        return cur.fetchone()[0] is True


def read(conn, *, unnotified=False):
    """Bounded SELECT projection of one future current-generation paper plan."""
    with conn.cursor() as cur:
        cur.execute("""SELECT c.cycle_id,p.plan_id,p.decision_session,p.effective_session,
            c.execute_at,p.created_at,p.target_basket,p.broker,p.broker_account_id,
            clock_timestamp() FROM sentinel_automation_cycles c
            JOIN sentinel_automation_control a ON a.id=1 AND a.enabled AND NOT a.kill_switch_engaged
              AND a.generation=c.control_generation AND a.deployment_id=c.deployment_id
              AND a.broker=c.broker AND a.broker_account_id=c.broker_account_id
              AND a.takeover_epoch=c.takeover_epoch
            JOIN sentinel_execution_plans p ON p.plan_id=c.plan_id
              AND p.deployment_id=c.deployment_id AND p.broker=c.broker
              AND p.broker_account_id=c.broker_account_id AND p.takeover_epoch=c.takeover_epoch
              AND p.decision_session=c.decision_session AND p.effective_session=c.effective_session
            WHERE c.state IN ('PLAN_READY','WAITING_OPEN') AND NOT c.historical_state_only
              AND p.superseded_by IS NULL AND c.execute_at>clock_timestamp()
              AND (NOT %s OR NOT EXISTS (SELECT 1 FROM sentinel_alert_outbox o
                WHERE o.idempotency_key='next-open-plan:'||c.cycle_id||':'||p.plan_id))
            ORDER BY c.execute_at LIMIT 2""", (unnotified,))
        values = cur.fetchall()
        if len(values)>1:
            raise ValueError('multiple current next-open plans')
        if not values:
            return None
        row = values[0]
        plan = dict(zip(('cycle_id','plan_id','decision_session','effective_session','execute_at',
                         'created_at','target_basket','broker','account','now'),row,strict=True))
        cur.execute("SELECT o.positions,o.observed_at FROM sentinel_observations o "
            "JOIN sentinel_observation_provenance p ON p.observation_seq=o.seq "
            "WHERE p.broker=%s AND p.broker_account_id=%s AND o.completeness='COMPLETE' "
            "ORDER BY o.observed_at DESC,o.seq DESC LIMIT 1",(plan['broker'],plan['account']))
        observation = cur.fetchone()
        cur.execute('SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                    ('plan-opening-intents:v1:'+plan['plan_id'],))
        opening = cur.fetchone()
        if opening:
            if opening[0] != plan['effective_session']:
                raise ValueError('paper opening intent session differs')
            plan['opening_intents'] = opening[1]
        identities = sorted(set(plan['target_basket']) | set(observation[0] if observation else {}))
        if len(identities)>100:
            raise ValueError('paper plan exceeds display holdings bound')
        from sentinel import dual_plan_authority
        sizing = dual_plan_authority.load_authority(conn, plan_id=plan['plan_id'])
        tickers = dict(sizing['tickers']) if sizing else {}
        cur.execute("SELECT security_id,ticker FROM sentinel_bars WHERE session=%s AND security_id=ANY(%s) "
            "UNION SELECT security_id,ticker FROM sentinel_defensive_bars WHERE session=%s AND security_id=ANY(%s)",
            (plan['decision_session'],identities,plan['decision_session'],identities))
        for sid,ticker in cur.fetchall():
            if sid in tickers and tickers[sid] != ticker:
                raise ValueError('planned security ticker is ambiguous')
            tickers[sid] = ticker
        return project(plan=plan,positions=observation[0] if observation else None,
            observation_at=observation[1] if observation else None,tickers=tickers,now=plan['now'])
