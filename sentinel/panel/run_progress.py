"""Pure, dated execution-display projections. No I/O or trading authority."""
from datetime import datetime, timedelta
from decimal import Decimal

from sentinel.panel import model
from sentinel.paper_plan_preview import PlanPreview, PlannedLeg, quantity


def project_run(plan, authority, commands):
    """Recover original proposed deltas from their immutable sizing snapshot."""
    if (authority['plan_id'] != plan['plan_id']
            or authority['plan_fingerprint'] != plan['plan_fingerprint']):
        raise ValueError('current trading run and sizing authority disagree')
    observation = authority['broker_observation']
    if (observation['completeness'] != 'COMPLETE'
            or observation['account_identity']['account_id'] != plan['broker_account_id']
            or observation['account_identity']['broker'] != plan['broker']):
        raise ValueError('original trading-run snapshot has wrong account authority')
    baseline = {}
    for position in observation['positions']:
        sid = position['instrument']['security_id']
        if sid in baseline:
            raise ValueError('duplicate original position')
        baseline[sid] = quantity(position['quantity'])
    targets = {sid: quantity(value) for sid, value in plan['target_basket'].items()}
    if len(set(baseline) | set(targets)) > 100:
        raise ValueError('trading-run holdings exceed display bounds')
    openings = {}
    reserved_slots = set()
    for item in plan.get('opening_intents', []):
        sid, slot = item['security_id'], item['slot_id']
        dollars = quantity(item['intended_dollars'])
        if (sid in openings or sid not in targets or targets[sid] != 0
                or baseline.get(sid,Decimal(0)) != 0 or dollars <= 0
                or type(slot) is not int or not 0<=slot<20 or slot in reserved_slots):
            raise ValueError('current trading run has contradictory opening intents')
        openings[sid] = dollars
        reserved_slots.add(slot)
    legs = []
    for sid in sorted(set(baseline) | set(targets)):
        current, target = baseline.get(sid, Decimal(0)), targets.get(sid, Decimal(0))
        delta = target-current
        dollars = openings.get(sid)
        legs.append(PlannedLeg(security_id=sid, ticker=authority['tickers'].get(sid, sid),
            current_quantity=current, target_quantity=target,
            change_quantity=None if dollars else delta, opening_dollars=dollars,
            action='BUY' if dollars or delta>0 else 'SELL' if delta<0 else 'HOLD'))
    intent = PlanPreview(cycle_id=plan['cycle_id'], plan_id=plan['plan_id'],
        decision_session=plan['decision_session'], effective_session=plan['effective_session'],
        execute_at=plan['execute_at'], created_at=plan['created_at'],
        observation_at=observation['observed_at'], legs=legs)
    orders = [model.RunOrder(**item) for item in commands]
    return model.TradingRun(intent=intent, state=plan['state'],
        updated_at=plan['updated_at'], completed_at=plan['completed_at'], orders=orders)


def moving_snapshot_recovery(*, run, observation, callback, first_inconsistent, now,
                             failure_code=None):
    """A finite unverified wait, only for an explained moving owned basket."""
    if (run is None or run.state not in {'EXECUTING', 'RECONCILING'}
            or failure_code not in {None, 'COMMANDS_IN_FLIGHT'}
            or observation['completeness'] != 'INCONSISTENT'
            or observation['runtime_state'] != 'RECONCILING' or not callback):
        return None
    started, deadline = callback.get('started_at'), callback.get('deadline')
    observed = observation['observed_at']
    if not all(isinstance(value, datetime) and value.utcoffset() is not None
               for value in (started, deadline, observed, first_inconsistent, now)):
        return None
    if not run.intent.execute_at <= started <= first_inconsistent <= observed <= now:
        return None
    deadline = min(deadline, first_inconsistent+timedelta(seconds=120))
    if not now < deadline:
        return None
    if (not run.orders or any(order.state not in {
            'ACKNOWLEDGED', 'PARTIALLY_FILLED', 'FILLED', 'CANCELLED', 'REJECTED'}
            or order.observed_at > now+model.MAXIMUM_FUTURE_SKEW for order in run.orders)):
        return None
    by_key = {order.client_key: order for order in run.orders}
    legs = {leg.security_id: leg for leg in run.intent.legs}
    capacities = {}
    for order in run.orders:
        leg = legs[order.security_id]
        if leg.action != order.side or leg.change_quantity is None or not order.broker_order_id:
            return None
        amount = order.quantity if order.state not in {'CANCELLED','REJECTED'} else order.filled_quantity
        capacities[order.security_id] = capacities.get(order.security_id, Decimal(0))+amount
        if capacities[order.security_id] > abs(leg.change_quantity):
            return None
    if not observation['orders']:
        return None
    for raw in observation['orders']:
        command = by_key.get(raw.get('key'))
        if (command is None or raw.get('id') != command.broker_order_id
                or raw.get('security_id') != command.security_id
                or raw.get('symbol') != command.ticker or raw.get('side') != command.side
                or raw.get('state') not in {'ACKNOWLEDGED','PARTIALLY_FILLED'}
                or raw.get('external_replacement') or raw.get('replaces') or raw.get('replaced_by')
                or raw.get('order_terms') != command.order_terms
                or quantity(raw.get('qty')) != command.quantity
                or quantity(raw.get('filled')) > command.quantity):
            return None
    for sid in set(observation['positions']) | set(legs):
        if sid not in legs:
            return None
        leg = legs[sid]
        held = quantity(observation['positions'].get(sid, '0'))
        capacity = capacities.get(sid, Decimal(0))
        signed = capacity if leg.action == 'BUY' else -capacity
        before = leg.current_quantity
        if before is None or not min(before,before+signed) <= held <= max(before,before+signed):
            return None
    return model.RecoveryEvidence(phase='BROKER_FILL_SNAPSHOT', automatic=True, deadline=deadline)
