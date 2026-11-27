"""Pure, dated execution-display projections. No I/O or trading authority."""
from datetime import datetime, timedelta
from decimal import Decimal

from sentinel.panel import delivery, model
from sentinel.paper_plan_preview import project_original_intent, quantity


def confirmed_sent(order: model.RunOrder) -> bool:
    return order.broker_order_id is not None or order.filled_quantity > 0


def current_execution_refusal(panel: model.Panel) -> str | None:
    """Describe a recorded refusal only while this plan and cycle are current."""
    row = panel.row('automation_cycle')
    if (row is None or row.operational_fact is None or not row.required_current
            or not delivery.display_current(panel) or panel.observation_retained
            or panel.observation_valid_until is not None and panel.now >= panel.observation_valid_until
            or not delivery.row_current(panel, row) or row.as_of is None
            or row.is_stale(panel.now) or row.is_future(panel.now)
            or row.effective_status(panel.now) not in {model.FAIL, model.WARN}):
        return None
    fact = row.operational_fact
    refusal = fact.execution_refusal
    if refusal is None:
        return None
    run_row = panel.row('trading_run')
    plan_row = panel.row('paper_plan')
    run = run_row.trading_run if run_row and delivery.row_current(panel, run_row) else None
    plan = plan_row.paper_plan if plan_row and delivery.row_current(panel, plan_row) else None
    if any((intent.cycle_id, intent.plan_id) != (refusal.cycle_id, refusal.plan_id)
           for intent in (plan, run.intent if run else None) if intent is not None):
        return None
    if run and run.updated_at >= row.as_of and (
            run.state == 'SUCCEEDED' or run.updated_at > row.as_of and run.state != fact.state):
        return None
    if refusal.code == 'PURCHASES_REQUIRE_DATABASE_ANCHOR':
        return 'Purchases withheld. An operator must verify the recovery history of this database and broker account before Sentinel can buy.'
    return 'Last execution attempt: ' + (refusal.detail or 'The plan still had trades to place.')


def order_summary(run: model.TradingRun) -> str:
    """Summarize distinct journal commands, keeping unconfirmed transport explicit."""
    if not run.orders:
        if run.unsent_at_cutoff:
            counts = ['0 recorded orders']
        elif run.state in {'FAILED', 'ABANDONED', 'SUPERSEDED', 'RETRY_WAIT', 'RECONCILING', 'EXECUTING'}:
            return 'No orders recorded. Submission and fill counts are unavailable.'
        else:
            return ''
    else:
        counts = [f'{len(run.orders)} recorded order' + ('s' if len(run.orders) != 1 else ''),
                  f'{sum(confirmed_sent(order) for order in run.orders)} confirmed sent',
                  f'{sum(order.state == "FILLED" for order in run.orders)} fully filled']
        for states, label in (({'ACKNOWLEDGED', 'PARTIALLY_FILLED'}, 'working'),
                              ({'PLANNED'}, 'still planned'), ({'SEND_PENDING'}, 'awaiting submission confirmation'),
                              ({'UNKNOWN'}, 'with outcome unknown'), ({'CANCEL_PENDING'}, 'awaiting cancellation confirmation'),
                              ({'CANCELLED', 'REJECTED', 'SUPERSEDED'}, 'ended without a full fill')):
            number = sum(order.state in states for order in run.orders)
            if number:
                counts.append(f'{number} {label}')
    if run.unsent_at_cutoff:
        number = len(run.unsent_at_cutoff)
        counts.append(f'{number} trade' + ('s' if number != 1 else '') + ' with an unsent remainder at cutoff')
    return ' · '.join(counts)


def project_run(plan, authority, commands, *, purchase_allocations=(), below_whole_share=None):
    """Recover original proposed deltas from their immutable sizing snapshot."""
    intent = project_original_intent(plan,authority)
    orders = [model.RunOrder(**item) for item in commands]
    return model.TradingRun(intent=intent, state=plan['state'],
        updated_at=plan['updated_at'], completed_at=plan['completed_at'], orders=orders,
        purchase_allocations=list(purchase_allocations),
        below_whole_share=below_whole_share or {})


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
    if any(order.notional is not None for order in run.orders):
        return None  # Dollars cannot establish a position-leading share envelope.
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
