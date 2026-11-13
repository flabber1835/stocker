"""Plain-language display only; never alter a financial or operational verdict."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo
from typing import Literal

from sentinel.panel.model import (
    RecoveryEvidence, Row, FINANCIAL_AUTHORITY_ROW_KEYS,
    OPERATIONAL_INFORMATIONAL_ROW_KEYS,
)

_CLOSING_DATA_PHASES = frozenset({
    'SOURCE_FRONTIER', 'POST_CLOSE_SOURCE_WAIT', 'SOURCE_PUBLICATION',
    'AUTOMATION_CLOSING_DATA', 'AUTHORITY_RECHECK_AFTER_DATA',
    'SHADOW_ATTESTATION', 'AUTOMATION_SHADOW_ATTESTATION', 'AUTHORITY_RECHECK_AFTER_SHADOW',
    'READINESS_HANDOFF', 'AUTHORITY_RECHECK_AFTER_HANDOFF',
})
_CLOSING_DATA_ROWS = frozenset({
    'shadow_verification', 'shadow_nav', 'shadow_return', 'exposure', 'book',
    'terminals', 'paper_reconciliation', 'feed', 'ingest', 'automation_cycle',
    'automation_step_data', 'authority',
})

_COPY = {
    'paper_plan': ('Next paper plan', 'Saved targets for the next market open. Proposed trades are estimates, not submitted orders or fills.'),
    'shadow_worker': ('Strategy worker', 'Checks that the worker updating the simulated portfolio is running. A verified saved portfolio can still be displayed while its worker is halted.'),
    'shadow_verification': ('Simulated portfolio check', 'Checks that the strategy portfolio was built correctly from the available market data. This is separate from your Alpaca account.'),
    'shadow_nav': ('Simulated strategy value', 'The controller’s simulated value combines the Core allocation and Treasury-bill sleeve, including costs. This differs from the unscaled Wealth Core book and the recorded Alpaca PAPER account.'),
    'shadow_return': ('Simulated strategy gain or loss', 'The simulated gain or loss from the Core allocation and Treasury-bill sleeve, including costs, since the starting portfolio. Broker deposits are separate.'),
    'paper_reconciliation': ('Paper account alignment', 'Checks whether Alpaca’s paper holdings and orders match the trading plan. Alignment is confirmed after execution and reconciliation.'),
    'trial_verification': ('Paper account check', 'Checks the paper account’s holdings, cash and trading results. Unverified results should not be treated as confirmed performance.'),
    'actual_account': ('Paper account value', 'The value of simulated money held at Alpaca. No real-money trading takes place.'),
    'trial_return': ('Paper account gain or loss', 'The change in the paper account after accounting for deposits and withdrawals.'),
    'trial_drawdown': ('Fall from peak value', 'How far the paper account has fallen from its highest recorded value.'),
    'trial_annualized': ('Annualized paper return', 'An estimate of the yearly growth rate implied by the recorded paper results.'),
    'trial_intent': ('Next trading plan', 'What the system intends to hold. A plan is not proof that the broker has filled its orders.'),
    'ownership': ('Account connected to Sentinel', 'Shows whether Sentinel has been assigned control of a paper account. Shadow-only operation does not require paper trading.'),
    'feed': ('Market data', 'The latest trading day with accepted prices and company information. It should catch up before the next trading decision.'),
    'ingest': ('Data download', 'Shows the most recent attempt to download and prepare market data.'),
    'book': ('Unscaled Wealth Core book', 'The stock-selection book’s shares, cash and noncash dividend receivables, before the controller’s Core allocation. Book weights use this book’s own total value. Receivables are not spending cash.'),
    'exposure': ('Planned Core exposure', 'The controller’s target allocation to Core; the remainder goes to the Treasury-bill sleeve. Core can retain cash, so this is not measured stock exposure in the Alpaca PAPER account.'),
    'terminals': ('Company events', 'Checks events such as delistings and acquisitions that can affect held shares.'),
    'broker': ('Paper holdings and orders', 'The broker account’s recorded holdings and order state. These are separate from the simulated strategy portfolio.'),
    'automation': ('Automatic paper trading', 'Shows whether scheduled paper trading is enabled. Disabled means the system will not submit paper orders.'),
    'automation_leader': ('Daily worker', 'Checks that one worker is responsible for the scheduled daily work.'),
    'automation_cycle': ('Current daily run', 'Tracks the current run from preparing the next trading plan to checking the paper account.'),
    'automation_alerts': ('System notifications', 'Recorded notification history: messages awaiting delivery, failed deliveries and alerts awaiting acknowledgement. Acknowledgement and delivery are separate.'),
    'alert_dispatcher': ('Notification delivery', 'Shows notification sender health and recorded delivery attempts. A healthy sender or push-service acceptance does not confirm receipt on your device.'),
    'alpaca_account': ('Recorded Alpaca paper account', 'Shows the last recorded account check. Its timestamp tells you when Alpaca was reached; this page does not poll the broker.'),
    'backup_restore': ('Backup and recovery', 'Checks that a recent database backup can actually be restored and its portfolio verified.'),
    'runtime_identity': ('Installed software', 'Checks that the running software matches the reviewed release.'),
    'authority': ('Permission to trade', 'Shows whether this software and account have permission to submit paper orders. A working dashboard alone does not grant permission.'),
}

_STEPS = {
    'discovery': ('Start the daily run', 'Finds the next scheduled trading day and any unfinished work.'),
    'data': ('Update market data', 'Downloads and prepares the prices needed for the next decision.'),
    'open': ('Wait for market open', 'Waits for the trading session before sending the plan to Alpaca.'),
    'transport': ('Place paper orders', 'Sends the approved plan to the Alpaca paper account.'),
    'complete': ('Finish the daily run', 'Records the completed run after its checks finish.'),
    'refresh': ('Update market data', 'Downloads and accepts the prices needed for the next decision.'),
    'preflight': ('Check readiness', 'Checks data, software, account permission and execution prerequisites for the selected operating mode.'),
    'prepare': ('Calculate the next trading plan', 'Prepares the next effective trading session’s plan from the strategy portfolio and controller allocation.'),
    'execute': ('Place paper orders', 'Sends the approved plan to the Alpaca paper account.'),
    'reconcile': ('Check shares and cash', 'Checks filled orders and account balances against the plan.'),
    'close': ('Finish daily accounting', 'Records the final result of the day’s paper run.'),
    'recover': ('Recover interrupted work', 'Resumes unfinished work without guessing whether an order was placed.'),
}


def _core_percentage(value: str) -> str:
    """Format only the model's owned fraction grammar; retain every caveat."""
    fraction, separator, suffix = value.partition(' ')
    if (suffix not in {'', 'PINNED', 'NOT ADOPTED'} or (separator and not suffix)
            or re.fullmatch(r'(?:0|1)(?:\.\d{1,12})?', fraction) is None):
        return value
    try:
        amount = Decimal(fraction)
        if (not amount.is_finite() or not 0 <= amount <= 1
                or not -12 <= amount.as_tuple().exponent <= 2):
            return value
        percent = format(amount * 100, 'f')
    except (InvalidOperation, ValueError):
        return value
    if '.' in percent:
        percent = percent.rstrip('0').rstrip('.')
    return percent+'%'+(' · '+suffix if separator else '')


def _pacific(value: datetime | None) -> str | None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        return None
    return value.astimezone(ZoneInfo('America/Los_Angeles')).strftime('%Y-%m-%d at %I:%M %p Pacific')


def is_closing_data_preparation(row: Row, status: str) -> bool:
    """Recognize accepted current evidence, using the caller's effective status."""
    recovery = row.recovery
    return (row.key in _CLOSING_DATA_ROWS and row.status == status == 'warn'
            and row.required_current and row.as_of is not None
            and recovery is not None and recovery.phase in _CLOSING_DATA_PHASES
            and recovery.automatic and not recovery.operator_required
            and _pacific(row.valid_until) is not None
            and row.valid_until == recovery.deadline)


def _aware(value) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _row_boundary(row: Row) -> datetime | None:
    values = []
    if _aware(row.valid_until):
        values.append(row.valid_until)
    elif _aware(row.as_of) and row.freshness is not None:
        values.append(row.as_of+row.freshness)
    if row.recovery is not None and _aware(row.recovery.deadline):
        values.append(row.recovery.deadline)
    return min(values) if values else None


def _fresh_worker(panel, key: str) -> bool:
    row = panel.row(key)
    return (row is not None and row.effective_status(panel.now) == 'ok'
            and row.required_current and _aware(row.as_of)
            and not row.is_future(panel.now) and not row.is_stale(panel.now)
            and _row_boundary(row) is not None and panel.now < _row_boundary(row))


def _closing_source_proof(panel) -> bool:
    return (_fresh_worker(panel, 'shadow_worker') and any(
        is_closing_data_preparation(row, row.effective_status(panel.now))
        and row.recovery.active(panel.now)
        and row.recovery.phase in {
            'SOURCE_FRONTIER', 'POST_CLOSE_SOURCE_WAIT', 'SOURCE_PUBLICATION',
            'SHADOW_ATTESTATION', 'READINESS_HANDOFF'} for row in panel.rows))


def _enabled_policy(row: Row | None) -> bool:
    fact = row.operational_fact if row is not None else None
    return fact is not None and fact.kind == 'AUTOMATION_POLICY' and fact.state == 'ENABLED_RELEASED'


def _workflow(row: Row | None, state: Literal['DISCOVERY_WAIT', 'WAITING_OPEN', 'SUCCEEDED']) -> bool:
    fact = row.operational_fact if row is not None else None
    return fact is not None and fact.kind == 'AUTOMATION_CYCLE' and fact.state == state


def _paper_verification(row: Row | None, state: Literal['CHECKING', 'PENDING']) -> bool:
    fact = row.operational_fact if row is not None else None
    return fact is not None and fact.kind == 'PAPER_VERIFICATION' and fact.state == state


def _current_input_session(panel, session: str) -> bool:
    feed, shadow = panel.row('feed'), panel.row('shadow_verification')
    source = feed.operational_fact if feed is not None else None
    verified = shadow.operational_fact if shadow is not None else None
    return (source is not None and source.kind == 'MARKET_DATA' and source.state == 'READY'
            and source.sessions_behind == 0 and source.session == date.fromisoformat(session)
            and verified is not None and verified.kind == 'SHADOW_VERIFICATION'
            and verified.state == 'VERIFIED' and verified.session == source.session)


def _normal_idle(panel, row: Row) -> bool:
    policy = panel.row('automation')
    return (row.key in {'automation_cycle', 'automation_step_discovery'}
            and _workflow(row, 'DISCOVERY_WAIT')
            and row.recovery is not None and row.recovery.phase == 'AUTOMATION_DISCOVERY'
            and row.recovery.active(panel.now) and _aware(row.recovery.deadline)
            and panel.now < row.recovery.deadline and policy is not None
            and policy.effective_status(panel.now) == 'ok'
            and _enabled_policy(policy)
            and _fresh_worker(panel, 'automation_leader'))


_HISTORY_CURRENT_FACTS = (
    'automation', 'automation_leader', 'authority', 'alpaca_account', 'broker',
    'feed', 'shadow_worker', 'shadow_verification', 'book', 'exposure', 'terminals',
    'runtime_identity', 'backup_restore', 'alert_dispatcher',
)


def _current_health_fact(panel, key: str) -> bool:
    row = panel.row(key)
    if (row is None or row.effective_status(panel.now) != 'ok'
            or not _aware(row.as_of) or row.is_future(panel.now) or row.is_stale(panel.now)):
        return False
    boundary = _row_boundary(row)
    return boundary is None or panel.now < boundary


def _current_reconciliation_usable(panel) -> bool:
    """Current display evidence; native execution still rechecks restrictions."""
    row = panel.row('broker')
    return (_current_health_fact(panel, 'broker')
            and row.required_current is True and row.recovery is None
            and _row_boundary(row) is not None)


def _paper_check_normal(panel, row: Row | None) -> bool:
    from sentinel.panel.model import checking_paper_row
    return checking_paper_row(row,now=panel.now)


def _historical_schedule_evidence(panel, history: Row | None, saved: Row) -> bool:
    if (history is None or history.paper_alignment != 'SCHEDULED_WITH_HISTORY'
            or history.effective_status(panel.now) != 'warn'
            or history.required_current is not True or history.recovery is not None
            or not _aware(history.as_of)
            or history.is_future(panel.now) or history.is_stale(panel.now)):
        return False
    plan = saved.paper_plan
    return (history.valid_until == plan.execute_at-timedelta(microseconds=1)
            and panel.now < history.valid_until
            and (history.freshness is None or panel.now < history.as_of+history.freshness))


def _scheduled_wait_proven(panel) -> bool:
    """Prove the scheduled facts without borrowing an independent backup verdict."""
    if (not panel.local_paper_mode or panel.source_errors
            or len({row.key for row in panel.rows}) != len(panel.rows)):
        return False
    paper, saved = panel.row('paper_reconciliation'), panel.row('paper_plan')
    if (saved is None or not saved.can_show_paper_plan(panel.now)
            or not (_historical_schedule_evidence(panel, paper, saved)
                    or _paper_check_normal(panel, paper))):
        return False
    plan = saved.paper_plan
    notifications = panel.row('automation_alerts')
    if (notifications is None or notifications.effective_status(panel.now) not in {'ok', 'warn'}
            or notifications.is_stale(panel.now) or notifications.is_future(panel.now)):
        return False
    if (any(leg.action == 'UNAVAILABLE' for leg in plan.legs)
            or not all(_current_health_fact(panel, key) for key in _HISTORY_CURRENT_FACTS
                       if key != 'backup_restore')
            or not _enabled_policy(panel.row('automation'))
            or not panel.row('alpaca_account').can_show_paper_account(panel.now)
            or not _current_input_session(panel, str(plan.decision_session))
            or not _current_reconciliation_usable(panel)):
        return False
    for key, phase in (('automation_cycle', 'AUTOMATION_WAITING_OPEN'),
                       ('automation_step_open', 'AUTOMATION_OPEN')):
        row = panel.row(key)
        recovery = row.recovery if row is not None else None
        if (row is None or not _workflow(row, 'WAITING_OPEN')
                or row.effective_status(panel.now) != 'warn' or not row.required_current
                or not _aware(row.as_of) or row.is_future(panel.now) or row.is_stale(panel.now)
                or recovery is None or recovery.phase != phase
                or not recovery.automatic or recovery.operator_required
                or not _aware(recovery.deadline) or recovery.deadline < plan.execute_at
                or not recovery.active(panel.now)):
            return False
    return True


def _scheduled_work_normal(panel) -> bool:
    """Complete original admission for green styling and its proof boundaries."""
    return (_current_health_fact(panel, 'backup_restore')
            and _scheduled_wait_proven(panel))


def _backup_maintenance_normal(panel, row: Row) -> bool:
    recovery = row.recovery
    return (row.key == 'backup_restore' and row.value == 'BACKUP CHECK IN PROGRESS'
            and row.effective_status(panel.now) == 'warn' and row.required_current
            and not row.is_future(panel.now) and _aware(row.as_of)
            and recovery is not None and recovery.phase == 'BACKUP_MAINTENANCE'
            and recovery.automatic and not recovery.operator_required
            and recovery.active(panel.now) and _aware(recovery.deadline)
            and panel.now < recovery.deadline and row.valid_until == recovery.deadline)


def _scheduled_wait_attributable(panel) -> bool:
    """An observed backup incident cannot invent a second waiting incident.

    This grants neither green admission nor a financial verdict. Every other
    current capability and the complete dated waiting/history proof still bind.
    Missing or unadmitted backup evidence supplies no attribution exception.
    """
    from sentinel.panel.delivery import row_current
    backup = panel.row('backup_restore')
    return (backup is not None and backup.required_current
            and row_current(panel, backup)
            and backup.effective_status(panel.now) in {'warn', 'fail', 'unknown'}
            and _scheduled_wait_proven(panel))


def _green_eligible(panel) -> bool:
    """Attribution of an ordinary wait never substitutes for full admission."""
    if _execution_work_normal(panel) and not _current_health_fact(panel, 'broker'):
        return False
    if (_historical_skip_record(panel) and not _clean_skip_work_normal(panel) and not _retired_check_work_normal(panel)
            and not (_scheduled_work_normal(panel) or _preparing_work_normal(panel))):
        return False
    return not _scheduled_wait_attributable(panel) or _scheduled_work_normal(panel)


def _historical_skip_record(panel) -> bool:
    """A proved old outcome is not positive current financial evidence."""
    from sentinel.panel.delivery import row_current
    row = panel.row('trading_run')
    fact = row.operational_fact if row is not None else None
    run = row.trading_run if row is not None else None
    return (fact is not None and fact.kind == 'EXECUTION_HISTORY' and fact.state == 'SUPERSEDED'
        and fact.opening is not None and fact.opening.terminal_reason == 'POST_PLAN_CASH_ACTIVITY_RECONCILED'
        and fact.opening.reconciled_at is not None and run is not None and run.state == 'SUPERSEDED'
        and (run.intent.cycle_id, run.intent.plan_id) == (fact.opening.cycle_id, fact.opening.plan_id)
        and run.updated_at == fact.opening.started_at
        and run.intent.execute_at <= fact.opening.reconciled_at <= run.updated_at <= panel.now < fact.opening.deadline
        and row.status == 'warn' and row.effective_status(panel.now) == 'warn'
        and row.valid_until is not None and panel.now < row.valid_until <= fact.opening.deadline
        and not row.is_future(panel.now) and not row.required_current
        and any(order.state not in {'FILLED', 'CANCELLED'} for order in run.orders) is False
        and row_current(panel, row))


def _opening_capabilities(panel, *, broker=True, maintenance=False) -> bool:
    from sentinel.panel.delivery import row_current
    keys = [key for key in _HISTORY_CURRENT_FACTS if broker or key != 'broker']
    return (panel.local_paper_mode and not panel.source_errors
        and len({row.key for row in panel.rows}) == len(panel.rows)
        and all((_current_health_fact(panel, key) or maintenance and key == 'backup_restore' and panel.row(key) is not None
                 and _backup_maintenance_normal(panel,panel.row(key)))
                and row_current(panel, panel.row(key)) for key in keys)
        and _enabled_policy(panel.row('automation'))
        and panel.row('book').can_show_shadow_book(panel.now)
        and panel.row('alpaca_account').can_show_paper_account(panel.now))


def _retired_workflow_history(panel, row: Row) -> bool:
    """Attribute only this immutable resolution, independently of a new check."""
    from sentinel.panel import model
    from sentinel.panel.delivery import row_current
    current,cycle = panel.row('trading_run'),panel.row('automation_cycle')
    if (row is None or row.key not in {'automation_cycle','automation_step_transport','automation_step_reconcile','automation_step_complete'}
            or not _historical_skip_record(panel) or not model.historical_skip_subject(current,now=panel.now)
            or cycle is None or not _workflow(cycle,'SUPERSEDED')
            or cycle.as_of != current.trading_run.updated_at or not row_current(panel,cycle)
            or not _workflow(row,'SUPERSEDED') or row.status != 'warn' or row.effective_status(panel.now) != 'warn'
            or row.recovery is not None or row.required_current or not row_current(panel,row)
            or row.valid_until != current.operational_fact.opening.deadline or row.is_future(panel.now)):
        return False
    return (row.as_of == current.trading_run.updated_at
            or model.resolved_skip_transport(row,current))


def _retired_current_capabilities(panel) -> bool:
    """Independent current capabilities, without selecting a PAPER verdict."""
    paper,current,broker,cycle = (panel.row(key) for key in (
        'paper_reconciliation','trading_run','broker','automation_cycle'))
    candidate = broker.operational_fact if broker is not None else None
    history = current.operational_fact.opening if current is not None and current.operational_fact is not None else None
    return (cycle is not None and _retired_workflow_history(panel,cycle)
        and all(_retired_workflow_history(panel,panel.row(key)) for key in (
            'automation_step_transport','automation_step_reconcile','automation_step_complete'))
        and _opening_capabilities(panel,maintenance=True)
        and candidate is not None and candidate.kind == 'EXECUTION_PROGRESS'
        and candidate.state == 'AWAITING_NEXT_DECISION' and candidate.opening is not None
        and all(getattr(candidate.opening,key) == getattr(history,key)
                for key in ('cycle_id','plan_id','observation_id','started_at'))
        and panel.now < candidate.opening.deadline <= history.deadline
        and broker.valid_until == candidate.opening.deadline and broker.recovery is None
        and history.reconciled_at <= broker.as_of <= history.started_at
        and _current_input_session(panel,str(current.trading_run.intent.decision_session)))


def _retired_check_work_normal(panel) -> bool:
    """Current independent checking may accompany an already resolved outcome."""
    from sentinel.panel.delivery import row_current
    paper = panel.row('paper_reconciliation')
    return (_retired_current_capabilities(panel) and _paper_check_normal(panel,paper)
            and row_current(panel,paper))


def _positive_retirement_paper(panel, row: Row) -> bool:
    """Attribute this current positive check without borrowing another row's health."""
    from sentinel.panel.delivery import row_current
    fact = row.operational_fact if row is not None else None
    current = panel.row('trading_run')
    return (row is not None and row.key == 'paper_reconciliation' and _historical_skip_record(panel)
        and fact is not None and fact.kind == 'PAPER_VERIFICATION' and fact.state == 'AWAITING_NEXT_DECISION'
        and fact.opening is not None and all(getattr(fact.opening,key) == getattr(current.operational_fact.opening,key)
            for key in ('cycle_id','plan_id','observation_id','started_at'))
        and row_current(panel,row) and row.status == row.effective_status(panel.now) == 'warn'
        and row.required_current and row.recovery is not None and row.recovery.phase == 'AWAITING_NEXT_DECISION'
        and row.valid_until == row.recovery.deadline == fact.opening.deadline
        and row.recovery.active(panel.now) and panel.now < row.valid_until and not row.is_future(panel.now))


def _execution_work_normal(panel) -> bool:
    from sentinel.panel.delivery import row_current
    broker, cycle, current, paper = (panel.row(key) for key in (
        'broker', 'automation_cycle', 'trading_run', 'paper_reconciliation'))
    fact = broker.operational_fact if broker is not None else None
    run = current.trading_run if current is not None else None
    if (fact is None or fact.kind != 'EXECUTION_PROGRESS' or fact.opening is None
            or fact.state not in {'EXECUTING', 'RECONCILING'}
            or run is None or run.state != fact.state
            or (run.intent.cycle_id, run.intent.plan_id) != (fact.opening.cycle_id, fact.opening.plan_id)
            or not run.intent.execute_at <= run.updated_at <= fact.opening.started_at <= panel.now < fact.opening.deadline
            or any(order.state not in {'ACKNOWLEDGED', 'PARTIALLY_FILLED', 'FILLED'} for order in run.orders)
            or current.status != 'warn' or current.is_future(panel.now) or current.is_stale(panel.now)
            or not row_current(panel, current) or not row_current(panel, broker)
            or not _workflow(cycle, run.state) or cycle.as_of != run.updated_at
            or cycle.effective_status(panel.now) != 'warn' or cycle.recovery is None
            or cycle.recovery.phase != 'AUTOMATION_'+run.state or not cycle.recovery.active(panel.now)
            or broker.effective_status(panel.now) not in {'ok', 'warn'}
            or broker.recovery is None or broker.recovery.phase != 'BROKER_CALLBACK_REFRESH'
            or not broker.recovery.active(panel.now) or not _opening_capabilities(panel, broker=False)
            or not _current_input_session(panel, str(run.intent.decision_session))):
        return False
    if _paper_check_normal(panel, paper):
        return row_current(panel, paper)
    paper_fact = paper.operational_fact if paper is not None else None
    paper_recovery = paper.recovery if paper is not None else None
    return (paper is not None and row_current(panel, paper)
        and paper.status == paper.effective_status(panel.now) == 'warn' and paper.required_current
        and paper_fact is not None and paper_fact.kind == 'PAPER_VERIFICATION' and paper_fact.state == 'PENDING'
        and paper_recovery is not None and paper_recovery.phase == 'PAPER_TRANSPORT'
        and _aware(paper.valid_until) and paper.valid_until == paper_recovery.deadline
        and panel.now < paper.valid_until and paper_recovery.active(panel.now))


def _clean_skip_work_normal(panel) -> bool:
    from sentinel.panel.delivery import row_current
    paper, cycle, current, broker = (panel.row(key) for key in (
        'paper_reconciliation', 'automation_cycle', 'trading_run', 'broker'))
    fact = paper.operational_fact if paper is not None else None
    run = current.trading_run if current is not None else None
    candidate = broker.operational_fact if broker is not None else None
    if _positive_retirement_paper(panel,paper) and _retired_current_capabilities(panel):
        return True
    if (not _opening_capabilities(panel) or fact is None or fact.kind != 'PAPER_VERIFICATION'
            or fact.state != 'AWAITING_NEXT_DECISION' or fact.opening is None
            or candidate is None or candidate.kind != 'EXECUTION_PROGRESS'
            or candidate.state != 'AWAITING_NEXT_DECISION' or candidate.opening is None
            or any(getattr(fact.opening, key) != getattr(candidate.opening, key)
                   for key in ('cycle_id', 'plan_id', 'observation_id', 'started_at'))
            or run is None or run.state != 'SUPERSEDED'
            or (run.intent.cycle_id, run.intent.plan_id) != (fact.opening.cycle_id, fact.opening.plan_id)
            or not run.intent.execute_at <= run.updated_at == fact.opening.started_at <= panel.now < fact.opening.deadline
            or any(order.state not in {'FILLED', 'CANCELLED'} for order in run.orders)
            or cycle is None or cycle.operational_fact is None or cycle.operational_fact.state != 'SUPERSEDED'
            or cycle.as_of != run.updated_at or not _current_input_session(panel, str(run.intent.decision_session))):
        return False
    for row in (paper, cycle, current):
        if (not row_current(panel, row) or row.status != 'warn' or row.effective_status(panel.now) != 'warn'
                or row.recovery is None or row.recovery.phase != 'AWAITING_NEXT_DECISION'
                or row.valid_until is None or row.recovery.deadline != row.valid_until
                or row.valid_until > fact.opening.deadline
                or not row.recovery.active(panel.now) or row.is_future(panel.now)):
            return False
    return True


def _completed_work_normal(panel) -> bool:
    """Combine the authenticated completed-history fact with current capabilities.

    The producer proves plan/generation/publication identity and clean durable
    reconciliation. This projection never verifies or modifies the audit itself.
    """
    if (not panel.local_paper_mode or panel.source_errors
            or len({row.key for row in panel.rows}) != len(panel.rows)):
        return False
    history, recorded = panel.row('paper_reconciliation'), panel.row('trading_run')
    if (history is None or history.paper_alignment != 'COMPLETED_WITH_HISTORY'
            or history.effective_status(panel.now) != 'warn'
            or not _aware(history.as_of) or history.recovery is not None
            or recorded is None or not _current_health_fact(panel, 'trading_run')
            or not recorded.can_show_trading_run(panel.now)):
        return False
    run = recorded.trading_run
    if (run.state != 'SUCCEEDED' or not _aware(run.completed_at)
            or not run.intent.execute_at <= run.completed_at <= panel.now
            or run.updated_at != run.completed_at
            or any(order.state != 'FILLED' for order in run.orders)
            or any(leg.action == 'UNAVAILABLE' for leg in run.intent.legs)
            or (not run.orders and any(leg.action != 'HOLD' for leg in run.intent.legs))):
        return False
    if (not all(_current_health_fact(panel, key) for key in _HISTORY_CURRENT_FACTS)
            or not _enabled_policy(panel.row('automation'))
            or not panel.row('alpaca_account').can_show_paper_account(panel.now)
            or not _current_reconciliation_usable(panel)
            or not _current_input_session(panel, str(run.intent.decision_session))):
        return False
    for key in ('automation_cycle', 'automation_step_complete'):
        row = panel.row(key)
        if (not _current_health_fact(panel, key) or not _workflow(row, 'SUCCEEDED')
                or not row.required_current or row.recovery is not None
                or row.as_of != run.completed_at):
            return False
    notifications = panel.row('automation_alerts')
    return (notifications is not None and notifications.effective_status(panel.now) in {'ok', 'warn'}
            and not notifications.is_stale(panel.now) and not notifications.is_future(panel.now))


def _unadopted_preparation_fact(panel, *, phase='AUTOMATION_PREPARING', session=None) -> bool:
    """The controller decision precedes its saved plan; no adoption is claimed."""
    if session is None:
        from sentinel.feed import calendar
        session = calendar.latest_closed_session(panel.now)
    row, cycle, plan = (panel.row(key) for key in ('exposure', 'automation_cycle', 'paper_plan'))
    fact = row.operational_fact if row is not None else None
    return (row is not None and row.status == 'warn' and row.required_current
            and row.recovery is None and _aware(row.as_of)
            and not row.is_future(panel.now) and not row.is_stale(panel.now)
            and (row.valid_until is None or _aware(row.valid_until))
            and _row_boundary(row) is not None and panel.now < _row_boundary(row)
            and fact is not None and fact.kind == 'CONTROLLER_DECISION'
            and (fact.state == 'NOT_ADOPTED' or fact.state == 'PINNED' and fact.exposure == 1)
            and fact.session == date.fromisoformat(session)
            and cycle is not None and cycle.recovery is not None
            and cycle.recovery.phase == phase
            and plan is not None and plan.status == 'pending' and plan.paper_plan is None)


def _deferred_adoption_boundary(panel, row: Row | None, *, prepare_witness=None) -> datetime | None:
    """Attribute one current exposure fact during its bounded planless handoff."""
    from sentinel.panel.delivery import row_current
    cycle, plan = panel.row('automation_cycle'), panel.row('paper_plan')
    recovery = cycle.recovery if cycle is not None else None
    if (row is None or row.status != 'warn' or recovery is None
            or not panel.local_paper_mode or panel.source_errors or plan is None
            or not _enabled_policy(panel.row('automation'))
            or not row_current(panel, row) or not cycle.required_current
            or (prepare_witness is None and (not row_current(panel, plan) or not row_current(panel, cycle)))
            or cycle.status != cycle.effective_status(panel.now) or cycle.status != 'warn'
            or not recovery.active(panel.now) or not _aware(recovery.deadline)
            or not _aware(cycle.as_of) or cycle.is_future(panel.now) or cycle.is_stale(panel.now)):
        return None
    phase = recovery.phase
    direct = {'AUTOMATION_PREFLIGHT_RECOVER': 'DISCOVERED',
              'AUTOMATION_REFRESHING_DATA': 'REFRESHING_DATA',
              'AUTOMATION_PREPARING': 'PREPARING'}
    preflight = phase in {'AUTOMATION_PREFLIGHT_RECOVER', 'AUTOMATION_PREFLIGHT_RECOVER_AVAILABILITY'}
    if phase in direct:
        if (not _workflow(cycle, direct[phase])
                or phase != 'AUTOMATION_PREPARING' and recovery.next_attempt_at is not None):
            return None
    elif (phase not in {'AUTOMATION_PREFLIGHT_RECOVER_AVAILABILITY',
                        'AUTOMATION_REFRESH_AVAILABILITY', 'AUTOMATION_PREPARE_AVAILABILITY'}
            or not _workflow(cycle, 'RETRY_WAIT') or type(recovery.attempt) is not int
            or recovery.attempt < 1 or not _aware(recovery.next_attempt_at)
            or not cycle.as_of < recovery.next_attempt_at <= recovery.deadline
            or not preflight and panel.now >= recovery.next_attempt_at):
        return None
    from sentinel.feed import calendar
    session = calendar.latest_closed_session(panel.now)
    closed = calendar.session_window(session)[1]
    opened = calendar.session_window(calendar.next_session(session))[0]
    if prepare_witness is not None:
        updated, saved_open, native_deadline = prepare_witness
        if (set(panel.observation_changed_scopes) != {'PAPER'}
                or phase not in {'AUTOMATION_REFRESHING_DATA', 'AUTOMATION_PREPARING'}
                or not all(_aware(value) for value in prepare_witness)
                or saved_open != opened
                or not cycle.as_of <= updated <= panel.now < native_deadline <= opened):
            return None
    deadline = opened if phase in direct else opened-timedelta(microseconds=1)
    if (not closed <= cycle.as_of <= panel.now < recovery.deadline <= deadline
            or not preflight and recovery.deadline != deadline
            or not _unadopted_preparation_fact(panel, phase=phase, session=session)
            or row.as_of < closed
            or not _current_input_session(panel, session)):
        return None
    inputs = ('feed', 'shadow_verification', 'book', 'terminals')
    if not all(_current_health_fact(panel, key) and row_current(panel, panel.row(key)) for key in inputs):
        return None
    book = panel.row('book')
    if not book.can_show_shadow_book(panel.now) or book.shadow_book.session != session:
        return None
    owners = ('automation_leader', 'shadow_worker')
    if not all(_fresh_worker(panel, key) and (
            row_current(panel, panel.row(key)) or key == 'automation_leader' and prepare_witness is not None)
            for key in owners):
        return None
    bounds = [_row_boundary(panel.row(key)) for key in (*inputs, *owners, 'exposure', 'automation_cycle')]
    bounds.append(recovery.deadline if preflight or phase in direct else recovery.next_attempt_at)
    if prepare_witness is not None:
        bounds.append(native_deadline)
    return min(bound for bound in bounds if bound is not None)


def project_planless_exposure(panel, *, prepare_witness=None):
    """Keep a verified pending adoption coherent in detail rows and headline."""
    row = panel.row('exposure')
    deadline = _deferred_adoption_boundary(panel, row, prepare_witness=prepare_witness)
    if deadline is None or deadline <= panel.now + timedelta(microseconds=1):
        return panel
    boundary = deadline - timedelta(microseconds=1)
    pending = replace(row, valid_until=boundary,
        recovery=RecoveryEvidence(phase='PLANLESS_EXPOSURE_ADOPTION',
            automatic=True, deadline=boundary))
    return replace(panel, rows=[pending if value is row else value for value in panel.rows])


def _preparation_inputs_current(panel) -> bool:
    from sentinel.feed import calendar
    session = calendar.latest_closed_session(panel.now)
    return (all(_current_health_fact(panel, key) for key in (
                'feed', 'shadow_verification', 'book', 'terminals'))
            and (_current_health_fact(panel, 'exposure') or _unadopted_preparation_fact(panel))
            and _current_input_session(panel, session)
            and panel.row('book').can_show_shadow_book(panel.now)
            and panel.row('book').shadow_book.session == session)


def _preparing_work_normal(panel) -> bool:
    """Ordinary pending PAPER work can accompany proven next-close preparation.

    No financial verdict is promoted: the independently observed raw pending
    row, current capabilities and original preparation clocks remain separate.
    """
    if (not panel.local_paper_mode or panel.source_errors
            or len({row.key for row in panel.rows}) != len(panel.rows)):
        return False
    paper, plan, cycle = (panel.row(key) for key in (
        'paper_reconciliation', 'paper_plan', 'automation_cycle'))
    # Reject non-preparation before loading a calendar or evaluating inputs.
    # WAITING_OPEN is common; it cannot earn this preparation exception.
    if (cycle is None or cycle.recovery is None or cycle.recovery.phase not in {
            'AUTOMATION_CLOSING_DATA', 'AUTOMATION_SHADOW_ATTESTATION',
            'AUTOMATION_REFRESHING_DATA', 'AUTOMATION_PREPARING', 'AUTOMATION_PLAN_READY'}
            or cycle.effective_status(panel.now) != 'warn' or not cycle.required_current
            or not _aware(cycle.as_of) or cycle.is_future(panel.now)
            or not cycle.recovery.automatic or cycle.recovery.operator_required
            or not cycle.recovery.active(panel.now) or not _aware(cycle.recovery.deadline)
            or not _fresh_worker(panel, 'automation_leader')
            or not _fresh_worker(panel, 'shadow_worker')):
        return False
    if not _closing_source_proof(panel) and not _preparation_inputs_current(panel):
        return False
    from sentinel.feed import calendar
    session = calendar.latest_closed_session(panel.now)
    following = calendar.next_session(session)
    opened = calendar.session_window(following)[0]
    closed = calendar.session_window(session)[1]
    if not closed <= panel.now < opened:
        return False
    pending = (paper is not None and paper.status == 'warn'
        and _paper_verification(paper, 'PENDING')
        and paper.paper_alignment is None and paper.recovery is None
        and _aware(paper.as_of) and not paper.is_future(panel.now)
        and (paper.valid_until is None or _aware(paper.valid_until))
        and _row_boundary(paper) is not None and panel.now < _row_boundary(paper)
        and paper.effective_status(panel.now) == 'warn')
    if not (pending or _paper_check_normal(panel, paper)) or plan is None:
        return False
    if cycle.as_of < closed:
        return False
    if (cycle.recovery.phase in {'AUTOMATION_REFRESHING_DATA', 'AUTOMATION_PREPARING'}
            and cycle.recovery.deadline != opened):
        return False
    if cycle.recovery.phase == 'AUTOMATION_PREPARING' and not _preparation_inputs_current(panel):
        return False
    if cycle.recovery.phase == 'AUTOMATION_PLAN_READY':
        if (not _preparation_inputs_current(panel) or not plan.can_show_paper_plan(panel.now)
                or str(plan.paper_plan.decision_session) != session
                or str(plan.paper_plan.effective_session) != following):
            return False
    elif plan.status != 'pending' or plan.paper_plan is not None:
        return False
    for key in _HISTORY_CURRENT_FACTS:
        row = panel.row(key)
        if _current_health_fact(panel, key):
            continue
        if key == 'exposure' and _unadopted_preparation_fact(panel):
            continue
        if (row is None or not is_closing_data_preparation(row, row.effective_status(panel.now))
                or not row.recovery.active(panel.now) or row.is_future(panel.now)
                or row.is_stale(panel.now)):
            return False
    notifications = panel.row('automation_alerts')
    return (_enabled_policy(panel.row('automation'))
            and panel.row('alpaca_account').can_show_paper_account(panel.now)
            and _current_reconciliation_usable(panel)
            and notifications is not None and notifications.effective_status(panel.now) in {'ok', 'warn'}
            and not notifications.is_future(panel.now) and not notifications.is_stale(panel.now))


def _normal_warning(panel, row: Row) -> bool:
    if (row.key == 'exposure' and row.status == 'warn' and row.recovery is not None
            and row.recovery.phase == 'PLANLESS_EXPOSURE_ADOPTION'
            and row.recovery.active(panel.now)
            and row.valid_until == row.recovery.deadline
            and not row.is_future(panel.now)):
        return True
    if row.key == 'trading_run' and _historical_skip_record(panel):
        return True
    if _retired_workflow_history(panel,row):
        return True
    if row.key == 'paper_reconciliation' and _positive_retirement_paper(panel,row):
        return True
    if (row.key in {'paper_reconciliation', 'automation_cycle', 'automation_step_transport',
                    'automation_step_reconcile', 'automation_step_complete', 'trading_run'}
            and _clean_skip_work_normal(panel)):
        if row.key == 'automation_step_transport' and row.value == 'INTERRUPTED · RECONCILED · PLAN SKIPPED':
            from sentinel.panel.model import resolved_skip_transport
            if not resolved_skip_transport(row, panel.row('trading_run'), panel.row('paper_reconciliation')):
                return False
        return (row.status == 'warn' and row.recovery is not None
            and row.recovery.phase == 'AWAITING_NEXT_DECISION'
            and row.recovery.deadline <= panel.row('paper_reconciliation').valid_until
            and row.valid_until == row.recovery.deadline and row.recovery.active(panel.now))
    if (row.key in {'paper_reconciliation', 'broker', 'automation_cycle', 'automation_step_transport',
                    'automation_step_reconcile', 'trading_run'} and _execution_work_normal(panel)):
        if row.effective_status(panel.now) != 'warn':
            return False
        if row.key in {'paper_reconciliation', 'broker', 'trading_run'}:
            return True
        run = panel.row('trading_run').trading_run
        phases = {'automation_cycle': 'AUTOMATION_'+run.state,
                  'automation_step_transport': 'AUTOMATION_TRANSPORT',
                  'automation_step_reconcile': 'AUTOMATION_RECONCILE'}
        return (row.operational_fact is not None and row.operational_fact.kind == 'AUTOMATION_CYCLE'
            and row.operational_fact.state == run.state and row.as_of == run.updated_at
            and row.required_current and row.recovery is not None
            and row.recovery.phase == phases[row.key] and row.recovery.active(panel.now))
    if (row.key in {'paper_reconciliation', 'exposure', 'automation_cycle', 'automation_step_data',
                    'automation_step_prepare', 'automation_step_open'}
            and _preparing_work_normal(panel)):
        if row.key == 'paper_reconciliation':
            return True
        if row.key == 'exposure':
            return _unadopted_preparation_fact(panel)
        cycle = panel.row('automation_cycle')
        phases = {cycle.recovery.phase}
        if cycle.recovery.phase == 'AUTOMATION_PLAN_READY':
            phases.add('AUTOMATION_OPEN')
        if (row.effective_status(panel.now) == 'warn' and row.required_current
                and _aware(row.as_of) and not row.is_future(panel.now)
                and row.recovery is not None and row.recovery.phase in phases
                and row.recovery.active(panel.now)):
            return True
    if row.key == 'paper_reconciliation' and _completed_work_normal(panel):
        return True
    if (row.key in {'paper_reconciliation', 'automation_cycle', 'automation_step_open'}
            and (_scheduled_work_normal(panel) or _scheduled_wait_attributable(panel))):
        return True
    recovery = row.recovery
    if (row.effective_status(panel.now) != 'warn' or recovery is None
            or not recovery.automatic or recovery.operator_required
            or not recovery.active(panel.now) or not _aware(recovery.deadline)
            or not panel.now < recovery.deadline or row.is_future(panel.now)):
        return False
    if _backup_maintenance_normal(panel, row):
        return True
    if (is_closing_data_preparation(row, 'warn') and _closing_source_proof(panel)):
        return True
    if _paper_check_normal(panel, row):
        return True
    if (row.key == 'ingest' and recovery.phase == 'FEED_INGEST'
            and row.can_show_preparation(panel.now)
            and row.preparation.active_at(panel.now)):
        return True
    if _normal_idle(panel, row):
        return True
    alignment = panel.row('paper_reconciliation')
    return (panel.local_paper_mode and panel.operational == 'ok'
            and row.key in {'automation_cycle', 'automation_step_open'}
            and _workflow(row, 'WAITING_OPEN')
            and recovery.phase in {'AUTOMATION_WAITING_OPEN', 'AUTOMATION_OPEN'}
            and alignment is not None and alignment.paper_alignment == 'SCHEDULED'
            and alignment.effective_status(panel.now) == 'ok')


def _preparation_boundary(work) -> datetime | None:
    boundary = work.observed_at+timedelta(seconds=45)
    if work.state == 'PUBLISHED':
        from sentinel.feed import calendar
        try:
            opened, _closed = calendar.session_window(work.effective_session.isoformat())
        except (ValueError, TypeError, RuntimeError, OverflowError):
            return None
        boundary = min(boundary, opened)
    return boundary


def visible_preparation(panel):
    """Completed data work stops describing next-plan preparation at its open."""
    row = panel.row('ingest')
    if row is None or not row.can_show_preparation(panel.now):
        return None
    work = row.preparation
    if work.state == 'PUBLISHED':
        boundary = _preparation_boundary(work)
        if boundary is None or panel.now >= boundary:
            return None
    return work


def preparation_stage(panel) -> str | None:
    if _retired_check_work_normal(panel):
        return 'Checking paper account · recorded plan skipped'
    if _clean_skip_work_normal(panel):
        return 'Waiting for next decision · plan skipped'
    if _execution_work_normal(panel):
        return ('Executing paper plan' if _current_health_fact(panel, 'broker')
                else 'Refreshing recorded broker evidence')
    """Describe admitted work, never infer a live stage from a retry string."""
    if _scheduled_work_normal(panel):
        return ('Checking paper account' if _paper_check_normal(panel, panel.row('paper_reconciliation'))
                else 'Waiting for market open')
    if _completed_work_normal(panel):
        return 'Today’s trading complete'
    cycle = panel.row('automation_cycle')
    if (cycle is not None and cycle.effective_status(panel.now) == 'warn'
            and cycle.recovery is not None and cycle.recovery.phase in {
                'AUTOMATION_PREFLIGHT_RECOVER', 'AUTOMATION_PREFLIGHT_RECOVER_AVAILABILITY'}):
        return 'Checking the recorded broker account'
    if _closing_source_proof(panel):
        phases = {row.recovery.phase for row in panel.rows
                  if is_closing_data_preparation(row, row.effective_status(panel.now))
                  and row.recovery.active(panel.now)}
        if 'SOURCE_PUBLICATION' in phases:
            return 'Publishing closing data'
        if phases & {'SHADOW_ATTESTATION', 'AUTOMATION_SHADOW_ATTESTATION', 'READINESS_HANDOFF'}:
            return 'Preparing strategy verification'
    work = visible_preparation(panel)
    if work is not None:
        if work.active_at(panel.now):
            return {'ACQUIRING': 'Downloading closing data',
                    'STAGING': 'Preparing downloaded data',
                    'VALIDATING': 'Validating market data',
                    'READY': 'Waiting to publish validated data'}[work.state]
        if work.state == 'PUBLISHED':
            plan = panel.row('paper_plan')
            saved = plan is not None and plan.can_show_paper_plan(panel.now)
            return 'Market data published'+('' if saved else ' · plan preparation pending')
        if work.state in {'WAIT_SOURCE', 'RETRY_WAIT'}:
            return 'Waiting to retry data acquisition'
        return 'Data preparation awaiting a worker'
    if _closing_source_proof(panel):
        return 'Waiting for closing data'
    if any(row.key == 'paper_reconciliation' and row.recovery is not None
           and row.recovery.phase == 'FINANCIAL_VERIFICATION'
           and _normal_warning(panel, row) for row in panel.rows):
        return 'Checking paper account'
    if any(_normal_idle(panel, row) for row in panel.rows):
        return 'Waiting for next decision'
    return None


def _classify_health_rows(panel, *, include_inactive_warnings=False):
    from sentinel.panel.delivery import row_current

    for row in panel.rows:
        status = row.effective_status(panel.now)
        current = row_current(panel, row)
        admits_warning = ((current or include_inactive_warnings) and status == 'warn'
                          or current and status == 'fail' and row.key == 'exposure'
                          and row.status == 'warn')
        yield row, status, current, admits_warning and _normal_warning(panel, row)


def health_facts(panel, *, boundaries: list[datetime] | None = None) -> dict:
    """Current facts only; old notification severity is not current failure."""
    return _health_facts(panel, list(_classify_health_rows(panel)), boundaries=boundaries)


def _health_facts(panel, classifications, *, boundaries) -> dict:
    active = ['backend_sources'] if panel.source_errors else []
    warnings = []
    for row, status, current, normal_warning in classifications:
        if not current:
            continue
        if status == 'fail' and row.key == 'exposure' and row.status == 'warn':
            if normal_warning:
                continue
            adoption_boundary = _deferred_adoption_boundary(panel, row)
            if adoption_boundary is not None:
                if boundaries is not None:
                    boundaries.append(adoption_boundary)
                continue
        if status in {'fail', 'unknown'}:
            active.append(row.key)
        elif (status == 'warn' and row.key != 'automation_alerts'
              and row.key not in OPERATIONAL_INFORMATIONAL_ROW_KEYS
              and not normal_warning):
            warnings.append(row.key)
    if not active and not warnings and not any(
            current and (status == 'ok' or status == 'warn' and normal_warning)
            for _, status, current, normal_warning in classifications):
        warnings.append('no_current_operation')
    return {'active': sorted(set(active)), 'warnings': sorted(set(warnings))}


def dashboard_health(panel) -> dict:
    """Human system health is separate from unchanged machine readiness."""
    plan = panel.row('paper_plan')
    from sentinel.panel.delivery import display_current, row_current
    plan_readiness = ('unavailable' if plan is not None and not row_current(panel, plan)
                      else 'ready' if plan is not None and plan.can_show_paper_plan(panel.now)
                      else 'unavailable' if plan is not None
                      and plan.effective_status(panel.now) in {'fail', 'unknown'} else 'pending')
    classifications = list(_classify_health_rows(panel, include_inactive_warnings=True))
    boundaries = []
    facts = _health_facts(panel, classifications, boundaries=boundaries)
    negative = bool(facts['active'])
    normal = (not negative and not facts['warnings'] and _green_eligible(panel) and any(
        status == 'ok' or status == 'warn' and normal_warning
        for _, status, _, normal_warning in classifications))
    review = panel.operator_review
    status = ('fail' if negative or review is not None and review.status in {'FAILED', 'UNAVAILABLE'}
              else 'ok' if normal and review is not None and review.status == 'CLEAN'
              else 'warn')
    stage = preparation_stage(panel)
    label = ('Needs attention' if negative else 'Healthy'+(' · '+stage if stage else '')
             if status == 'ok' else
             ('Preparation delayed' if stage in {'Waiting to retry data acquisition',
                 'Data preparation awaiting a worker'} else 'Needs review')
             +(' · '+stage if stage else ''))
    if review is not None and review.status == 'UNAVAILABLE':
        label = 'Review history unavailable'
    if not negative and status == 'warn':
        if review is None or review.status == 'UNAVAILABLE':
            label = 'Review history unavailable'
        elif review.status == 'REVIEW' and not facts['warnings']:
            label = 'Acknowledgement required'
        elif not facts['warnings'] and _execution_work_normal(panel):
            label = 'Refreshing recorded broker evidence'
    broker = panel.row('broker')
    if (status == 'warn' and broker is not None and broker.effective_status(panel.now) == 'warn'
            and broker.recovery is not None and broker.recovery.phase == 'BROKER_FILL_SNAPSHOT'
            and broker.recovery.active(panel.now)):
        label = 'Reconciling fills'
    admitted = [row for row, status, _, normal_warning in classifications
                if status == 'warn' and normal_warning
                and row.key not in OPERATIONAL_INFORMATIONAL_ROW_KEYS]
    execution_normal = _execution_work_normal(panel)
    boundaries.extend(row.operational_fact.opening.deadline
        if execution_normal and row.key == 'broker' and row.is_stale(panel.now)
        else _row_boundary(row) for row in admitted)
    if execution_normal or _clean_skip_work_normal(panel) or _retired_check_work_normal(panel):
        boundaries.extend(_row_boundary(panel.row(key)) for key in _HISTORY_CURRENT_FACTS
                          if key != 'broker' or not execution_normal or not panel.row(key).is_stale(panel.now))
        boundaries.append(_row_boundary(panel.row('trading_run')))
    if any(is_closing_data_preparation(row, 'warn') for row in admitted):
        boundaries.append(_row_boundary(panel.row('shadow_worker')))
    if any(_normal_idle(panel, row) for row in admitted):
        boundaries.append(_row_boundary(panel.row('automation_leader')))
    if _scheduled_work_normal(panel):
        boundaries.extend(_row_boundary(panel.row(key)) for key in _HISTORY_CURRENT_FACTS)
        boundaries.append(panel.row('paper_plan').paper_plan.execute_at)
        history = panel.row('paper_reconciliation')
        if history.freshness is not None and _aware(history.as_of):
            boundaries.append(history.as_of+history.freshness)
    if _completed_work_normal(panel):
        boundaries.extend(_row_boundary(panel.row(key)) for key in _HISTORY_CURRENT_FACTS)
        boundaries.append(_row_boundary(panel.row('trading_run')))
        boundaries.append(_row_boundary(panel.row('paper_reconciliation')))
    if _preparing_work_normal(panel):
        boundaries.extend(_row_boundary(panel.row(key)) for key in _HISTORY_CURRENT_FACTS)
        boundaries.append(_row_boundary(panel.row('paper_reconciliation')))
        from sentinel.feed import calendar
        boundaries.append(calendar.session_window(calendar.next_session(
            calendar.latest_closed_session(panel.now)))[0])
    boundaries = [value for value in boundaries if value is not None]
    if panel.observation_valid_until is not None:
        boundaries.append(panel.observation_valid_until)
    work = visible_preparation(panel)
    if work is not None:
        boundary = _preparation_boundary(work)
        if boundary is not None:
            boundaries.append(boundary)
        if work.active_at(panel.now) and not (stage == 'Publishing closing data'):
            boundaries.append(work.active_until)
    boundary = min(boundaries).astimezone(timezone.utc) if boundaries else None
    if not display_current(panel) and not negative:
        from sentinel.panel.delivery import closing_refresh_deadline, opening_refresh_deadline
        opening = opening_refresh_deadline(panel)
        if opening is not None:
            return dict(status='warn', color='amber', label='Refreshing opening evidence',
                        valid_until=opening.isoformat(), plan_readiness='unavailable',
                        active_conditions=facts['active'], review_conditions=facts['warnings'],
                        opening_refresh=True)
        closing = closing_refresh_deadline(panel)
        if closing is not None:
            return dict(status='warn', color='amber', label='Refreshing closing evidence',
                        valid_until=closing.isoformat(), plan_readiness='unavailable',
                        active_conditions=facts['active'], review_conditions=facts['warnings'],
                        closing_refresh=True)
        return dict(status='pending', color='neutral', label='Status not current · refreshing',
                    valid_until=boundary.isoformat() if boundary is not None else None,
                    plan_readiness='unavailable', active_conditions=facts['active'],
                    review_conditions=facts['warnings'])
    return dict(status=status, color={'ok': 'green', 'warn': 'amber', 'fail': 'red'}[status],
                label=label, valid_until=boundary.isoformat() if boundary is not None else None,
                plan_readiness=plan_readiness, active_conditions=facts['active'],
                review_conditions=facts['warnings'])


def describe(row: Row, status: str) -> tuple[str, str, str]:
    """Return display copy; caller retains row keys, raw evidence and status."""
    key = row.key
    copy = _COPY.get(key)
    if key.startswith('automation_step_'):
        copy = _STEPS.get(key.removeprefix('automation_step_'))
    label, explanation = copy or (row.label, row.detail)
    value = row.value
    if key == 'broker' and row.recovery is not None and row.recovery.phase == 'BROKER_FILL_SNAPSHOT':
        explanation = ('Reconciling fills. The broker snapshot is temporarily inconsistent while '
                       'known orders change positions. It is not verified; the original bounded '
                       'observation deadline remains in force.' if status == 'warn' else
                       'The bounded broker snapshot wait expired or is no longer current. '
                       'The snapshot remains unverified and needs attention.')
    if key == 'exposure':
        value = _core_percentage(value)
    if key == 'backup_restore' and row.value == 'DISABLED BY OWNER':
        label = 'Backups suspended'
        explanation = ('Backup creation, restore drills and backup verification are suspended '
                       'by owner instruction for local PAPER operation. No restore assurance is claimed.')
    if key == 'runtime_identity' and row.value.startswith('LOCAL PAPER '):
        label = 'Installed local software'
        explanation = ('Shows the owner-authorized local commit and image. '
                       'This is separate from the authority certificate’s original software '
                       'references and historical strategy certification.')
    scheduled_paper = key == 'paper_reconciliation' and row.value == (
        'PAPER NOT VERIFIED · SCHEDULED · POST-CLOSE EVIDENCE PENDING')
    if key == 'paper_reconciliation' and row.paper_alignment in {'SCHEDULED_WITH_HISTORY', 'COMPLETED_WITH_HISTORY'}:
        label = 'Historical paper audit'
        completed = row.paper_alignment == 'COMPLETED_WITH_HISTORY'
        if status == 'warn':
            value = ('Earlier-plan discrepancy retained · today’s trading complete' if completed
                     else 'Earlier-plan discrepancy retained · current plan scheduled')
            explanation = ('An authenticated discrepancy on an earlier transported plan remains '
                'recorded for audit. It does not by itself describe a current trading failure. '
                'PAPER performance and post-close verification remain unverified; future execution still runs its fresh '
                'account, restriction and reconciliation checks. '+row.detail)
        else:
            value = ('Current completed-trade proof cannot be confirmed' if completed
                     else 'Current scheduled proof cannot be confirmed')
            explanation = ('The historical record remains retained, but its current scheduling '
                'proof is unavailable or expired. Current checks need attention. '+row.detail)
    if scheduled_paper:
        label = 'Paper alignment pending'
        value = ('Scheduled · alignment and post-close verification pending'
                 if status == 'ok' else 'Scheduled readiness cannot be confirmed')
        explanation = ('A saved plan is ready to wait for its execution time. '
                       'Future holdings alignment and post-close verification remain pending; '
                       'this is not proof of submitted orders, fills or verified PAPER performance.'
                       if status == 'ok' else
                       'The saved scheduled state no longer establishes current readiness. '
                       'Holdings alignment and post-close verification remain unconfirmed.')
    if key == 'automation_alerts':
        counts = re.fullmatch(r'(\d+) pending · (\d+) DLQ · (\d+) unacked', value)
        if counts is not None:
            pending, failed, unacknowledged = counts.groups()
            value = (f'{pending} awaiting delivery · {failed} failed '
                     f'{"delivery" if failed == "1" else "deliveries"} · '
                     f'{unacknowledged} unacknowledged '
                     f'{"alert" if unacknowledged == "1" else "alerts"}')
    if key == 'shadow_worker' and row.status == 'ok' and status != 'ok':
        value = 'WORKER STATUS NOT CURRENT'
    if row.recovery is not None and row.recovery.phase == 'FINANCIAL_VERIFICATION' and status == 'warn':
        explanation += ' A fresh verification is running; last-known numbers keep their original timestamp. '+row.detail
    elif status == 'ok' and 'background refresh running; last verified ' in row.detail:
        explanation += ' The last successful check is still current. '+row.detail
    if key == 'backup_restore' and value == 'BACKUP CHECK IN PROGRESS':
        explanation += ' A replacement backup is being restored and checked. It is not yet confirmed recoverable.'
    if key == 'paper_plan' and row.paper_plan is not None:
        plan = row.paper_plan
        scheduled = _pacific(plan.execute_at)
        if scheduled is not None:
            explanation += ' Saved execution: '+scheduled+'.'
        if not any(leg.action == 'UNAVAILABLE' for leg in plan.legs):
            value = (f'{plan.effective_session} · {plan.buys} '
                     f'{"buy" if plan.buys == 1 else "buys"} · {plan.sells} '
                     f'{"sell" if plan.sells == 1 else "sells"}')
    source_wait = is_closing_data_preparation(row, status)
    availability_wait = row.recovery is not None and row.recovery.phase in {
        'AUTOMATION_REFRESH_AVAILABILITY', 'AUTOMATION_PREPARE_AVAILABILITY'}
    working_orders = row.value == 'DAY ORDERS WORKING'
    missed_buys = row.value == 'MISSED UNSENT BUYs'
    scheduled_wait = (key in {'automation_cycle', 'automation_step_open'}
                      and row.value == 'WAITING_OPEN' and row.recovery is not None
                      and row.recovery.phase in {'AUTOMATION_WAITING_OPEN', 'AUTOMATION_OPEN'})
    if scheduled_wait:
        start = _pacific(row.recovery.next_attempt_at)
        deadline = _pacific(row.recovery.deadline)
        if start is not None:
            explanation += ' Saved execution start: '+start+'.'
        if deadline is not None:
            explanation += (' Saved recovery deadline (market close): '+deadline+'. '
                            'This is separate from the execution start and the new-order submission cutoff.')
    if source_wait:
        # Keep retained numbers and holdings visible with their historical label.
        # Current verification/publication waits have a plain-language value.
        awaiting_shadow = row.recovery.phase in {
            'SHADOW_ATTESTATION', 'AUTOMATION_SHADOW_ATTESTATION', 'AUTHORITY_RECHECK_AFTER_SHADOW'}
        if key not in {'shadow_nav', 'shadow_return', 'exposure', 'book'}:
            value = 'Preparing strategy verification' if awaiting_shadow else 'Preparing closing data'
        explanation += (
            ' Closing data is published. Current strategy attestation is still pending; '
            'no current portfolio values or holdings are certified.' if awaiting_shadow else
            ' Preparing closing data. Market data for the next decision is still pending. '
            'Current-session verification must wait; retained values and holdings '
            'keep their original attestation date.')
        # The strict exclusive bound is one microsecond before the original
        # clock. Display the original minute without changing machine expiry.
        original_deadline = row.recovery.deadline
        if original_deadline is not None and original_deadline.microsecond == 999999:
            original_deadline += timedelta(microseconds=1)
        deadline = _pacific(original_deadline)
        if deadline is not None:
            explanation += ' Original preparation deadline: '+deadline+'.'
    elif availability_wait and status == 'warn':
        explanation += (' Automatic retries are continuing before the saved market-open deadline. '
                        'Trading still requires a ready plan.')
    elif working_orders and status == 'warn':
        explanation += (' Known DAY orders remain open at the paper broker. '
                        'The system is checking for fills or terminal outcomes; '
                        'target completion is not yet confirmed.')
    elif working_orders:
        explanation += (' The recorded working-order evidence is no longer current. '
                        'Fills, cancellation or expiry still need to be confirmed.')
    elif missed_buys:
        explanation += (' Some planned buys were not submitted before the original cutoff. '
                        'Existing broker orders still require reconciliation; '
                        'target completion is not confirmed.')
    value = {
        'WAITING_OPEN': 'Waiting for market open',
        'UNKNOWN': 'Status unavailable',
        'DAY ORDERS WORKING': 'DAY orders recorded as working',
        'MISSED UNSENT BUYs': 'Buy submission window expired',
    }.get(value, value)
    if copy:
        value = (value.replace('TRIAL NOT VERIFIED', 'Paper account not verified')
                 .replace('TRIAL VERIFIED THROUGH', 'Paper account checked through')
                 .replace('SHADOW NOT VERIFIED', 'Simulated portfolio not verified')
                 .replace('SHADOW VERIFIED THROUGH', 'Simulated portfolio checked through')
                 .replace('PAPER NOT VERIFIED', 'Paper account not verified')
                 .replace('MIRROR CLEAN', 'Holdings and orders match')
                 .replace('NOT STARTED', 'Not started')
                 .replace('STATUS UNREADABLE', 'Unable to read status'))
        if status in {'fail', 'unknown'}:
            explanation += ' Attention needed: this check is failing or cannot be confirmed. Open the technical details for the recorded reason.'
        elif status == 'warn' and row.value == 'WAITING_OPEN':
            explanation += ' The plan is ready and waiting for its scheduled execution time.'
        elif status == 'warn' and not (source_wait or availability_wait or working_orders):
            explanation += ' This is waiting or needs review; it is not a completed check.'
        elif status == 'pending' and key.startswith('automation_step_'):
            if row.value == 'NOT REACHED':
                value = 'Pending earlier steps'
                explanation += ' This step is pending until its predecessor completes; no completion is claimed.'
            elif row.value == 'MAINTENANCE':
                explanation += ' Automation is deliberately disabled; this step is not running.'
            elif row.value == 'NOT INSTALLED':
                explanation += ' Automation is not installed; this step is unavailable.'
            else:
                explanation += ' This step is pending in the current daily run.'
        elif status == 'pending':
            explanation += ' This check is pending.'
    if key in FINANCIAL_AUTHORITY_ROW_KEYS and status != 'ok':
        explanation += ' This result is unverified; do not treat it as confirmed performance.'
    if status != 'ok' and row.detail.startswith(('LAST KNOWN · ', 'NOT CURRENT · LAST KNOWN · ')):
        value = 'LAST KNOWN · '+value.removeprefix('LAST KNOWN · ')
    return label, value, explanation
