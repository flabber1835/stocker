"""Pure, dated execution-display projections. No I/O or trading authority."""
from datetime import datetime, timedelta
from decimal import Decimal

from sentinel.panel import model
from sentinel.paper_plan_preview import project_original_intent, quantity


def project_run(plan, authority, commands):
    """Recover original proposed deltas from their immutable sizing snapshot."""
    intent = project_original_intent(plan,authority)
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
