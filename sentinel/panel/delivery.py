"""Scope-aware current styling, separate from native facts and transport age."""
from dataclasses import replace
from datetime import timedelta

from sentinel.panel import model

_FINANCIAL_SHADOW = model.SHADOW_ROW_KEYS | {'exposure', 'book', 'terminals'}
_SHADOW = _FINANCIAL_SHADOW | {'feed', 'ingest', 'shadow_segment',
    'paper_plan', 'trading_run', 'completed_trading_run', 'authority', 'automation_cycle'}
_PAPER = frozenset({'paper_reconciliation', 'paper_plan', 'trading_run',
    'completed_trading_run', 'alpaca_account', 'actual_account', 'broker',
    'ownership', 'automation', 'automation_leader', 'automation_cycle',
    'authority', 'runtime_identity', 'issuer_reference', *model.TRIAL_ROW_KEYS})
_INDEPENDENT = frozenset({'backup_restore', 'shadow_worker', 'automation_alerts',
    'alert_dispatcher', 'trading_environment'})
_KNOWN = _SHADOW | _PAPER | _INDEPENDENT


def display_current(panel):
    """Human delivery can be proved independently of strict financial subjects."""
    return (panel.observation_current if panel.observation_display_current is None
            else panel.observation_display_current)


def display_keys(panel):
    return tuple(row.key for row in panel.rows
                 if row.key in _KNOWN or row.key.startswith('automation_step_'))


def opening_refresh_deadline(panel):
    """Bound an opening refresh label to the original signed display window."""
    from sentinel.panel.operational_snapshot import MAX_SECONDS

    generated = panel.observation_generated_at
    until = panel.observation_valid_until
    review = panel.operator_review
    if (not panel.local_paper_mode or panel.source_errors
            or set(panel.observation_changed_scopes) - {'PAPER'}
            or generated is None or until is None or review is None
            or review.status not in {'CLEAN', 'REVIEW'}):
        return None
    boundary = min(until, generated + timedelta(seconds=MAX_SECONDS))
    if not generated <= panel.now < boundary:
        return None
    cycle = panel.row('automation_cycle')
    if (cycle is None or cycle.operational_fact is None
            or cycle.operational_fact.kind != 'AUTOMATION_CYCLE'):
        return None
    state = cycle.operational_fact.state
    plan_row = panel.row('paper_plan')
    plan = plan_row.paper_plan if plan_row is not None else None
    if (state == 'WAITING_OPEN' and plan is not None and plan_row.status == model.OK
            and any(stamp is not None and generated < stamp <= panel.now
                    for stamp in (plan.execution_open_at, plan.execute_at))):
        return boundary
    trading = panel.row('trading_run')
    run = trading.trading_run if trading is not None else None
    broker = panel.row('broker')
    recovery = broker.recovery if broker is not None else None
    if (state in {'EXECUTING', 'RECONCILING'} and run is not None and run.state == state
            and trading.status == model.WARN and run.intent.execute_at <= run.updated_at <= generated
            and recovery is not None and recovery.phase == 'BROKER_CALLBACK_REFRESH'
            and recovery.deadline is not None and panel.now < recovery.deadline
            and recovery.active(panel.now)):
        return min(boundary, recovery.deadline)
    return None


def bell_handoff(conn, panel, *, expired_at, now):
    """Cross only the market clock tick with independently current waiting facts."""
    from sentinel.execution import opening_display
    from sentinel.panel.operational_snapshot import MAX_SECONDS
    from sentinel.panel.presentation import _row_boundary, _scheduled_work_normal, health_facts

    saved = panel.row('paper_plan')
    plan = saved.paper_plan if saved is not None else None
    broker = panel.row('broker')
    review = panel.operator_review
    if (plan is None or plan.execution_open_at != expired_at
            or not panel.local_paper_mode or panel.source_errors
            or review is None or review.status != 'CLEAN'
            or not panel.now < expired_at <= now < plan.execute_at
            or now >= panel.now + timedelta(seconds=MAX_SECONDS)
            or broker is None or broker.effective_status(now) != model.OK
            or broker.is_stale(now) or broker.is_future(now)
            or not _scheduled_work_normal(replace(panel, now=now))):
        return None
    for row in panel.rows:
        boundary = _row_boundary(row)
        if row.required_current and (row.is_future(now) or boundary is not None and now >= boundary):
            return None
    if any(health_facts(replace(panel, now=now)).values()):
        return None
    observed = opening_display.observed_at(
        conn, cycle_id=plan.cycle_id, plan_id=plan.plan_id, waiting=True)
    return display_keys(panel) if observed is not None and observed == broker.as_of else None


def closing_refresh_deadline(panel):
    """Bound partial close delivery to already proved operational progress."""
    from sentinel.feed import calendar
    from sentinel.panel.operational_snapshot import MAX_SECONDS
    from sentinel.panel.presentation import _fresh_worker, _row_boundary

    generated, until = panel.observation_generated_at, panel.observation_valid_until
    review = panel.operator_review
    changed = set(panel.observation_changed_scopes)
    if (not panel.local_paper_mode or panel.source_errors or not changed
            or changed - {'SHADOW', 'PAPER'} or generated is None or until is None
            or review is None or review.status not in {'CLEAN', 'REVIEW'}):
        return None
    now = panel.now
    boundary = min(until, generated + timedelta(seconds=MAX_SECONDS))
    if not generated <= now < boundary or not _fresh_worker(panel, 'shadow_worker'):
        return None
    worker = panel.row('shadow_worker')
    if not row_current(panel, worker):
        return None
    feed = panel.row('feed')
    if feed is None or not row_current(panel, feed) or feed.is_future(now) or feed.is_stale(now):
        return None
    fact, recovery = feed.operational_fact, feed.recovery
    ready = (feed.effective_status(now) == model.OK and fact is not None
             and fact.kind == 'MARKET_DATA' and fact.state == 'READY' and fact.sessions_behind == 0)
    preparing = (feed.effective_status(now) == model.WARN and recovery is not None
                 and recovery.phase in {'FEED_INGEST', 'POST_CLOSE_SOURCE_WAIT',
                                        'SOURCE_PUBLICATION', 'SHADOW_ATTESTATION', 'READINESS_HANDOFF'}
                 and recovery.active(now))
    if not ready and not preparing:
        return None
    session = calendar.latest_closed_session(now)
    closed = calendar.session_window(session)[1]
    opened = calendar.session_window(calendar.next_session(session))[0]
    if not closed <= now < opened or ready and str(fact.session) != session:
        return None
    boundary = min(boundary, opened, worker.valid_until, _row_boundary(feed) or boundary)
    return boundary if now < boundary else None


def row_current(panel, row):
    if panel.observation_current:
        return True
    if row.key in panel.observation_display_keys and (
            row.key in _KNOWN or row.key.startswith('automation_step_')):
        if row.status in {model.FAIL, model.UNKNOWN}:
            return True
        if row.is_future(panel.now) or row.is_stale(panel.now):
            return False
        from sentinel.panel.presentation import _row_boundary
        boundary = _row_boundary(row)
        return ((boundary is None or panel.now < boundary)
                and (row.paper_plan is None or panel.now < row.paper_plan.execute_at))
    changed = set(panel.observation_changed_scopes)
    if (not changed and not panel.observation_retained) or changed - {'SHADOW', 'PAPER'}:
        return False
    negative = row.status in {model.FAIL, model.UNKNOWN}
    if row.key not in _KNOWN and not row.key.startswith('automation_step_') and not (
            panel.observation_retained and negative):
        return False
    revalidated = row.key in panel.observation_revalidated_keys and (
            'SHADOW' in changed and row.key in _FINANCIAL_SHADOW
            or 'PAPER' in changed and row.key == 'paper_reconciliation')
    current = revalidated or not (('SHADOW' in changed and (row.key in _SHADOW or row.key.startswith('automation_step_')))
                or ('PAPER' in changed and (row.key in _PAPER
                    or row.key.startswith('automation_step_'))))
    if not current or not panel.observation_retained:
        return current
    if negative:
        return True
    if row.is_future(panel.now):
        return False
    from sentinel.panel.presentation import _row_boundary
    boundary = _row_boundary(row)
    if row.paper_plan is not None:
        boundary = min(boundary, row.paper_plan.execute_at) if boundary else row.paper_plan.execute_at
    return boundary is not None and panel.now < boundary


def row_status(panel, row):
    native = row.effective_status(panel.now)
    return native if row_current(panel, row) else model.PENDING


def row_color(panel, row):
    from sentinel.operational_status import color
    native = row.effective_status(panel.now)
    return color(native) if row_current(panel, row) else 'neutral'


def payload_panel(panel):
    """A detached presentation view cannot expose stale payloads as current."""
    return replace(panel, rows=[row if row_current(panel, row) else replace(row,
        shadow_book=None, paper_plan=None, paper_account=None, trading_run=None,
        preparation=None, order_outcomes=[]) for row in panel.rows])
