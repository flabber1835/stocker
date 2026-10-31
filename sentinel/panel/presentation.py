"""Plain-language display only; never alter a financial or operational verdict."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo

from sentinel.panel.model import (
    Row, FINANCIAL_AUTHORITY_ROW_KEYS,
    OPERATIONAL_INFORMATIONAL_ROW_KEYS,
)

_CLOSING_DATA_PHASES = frozenset({
    'SOURCE_FRONTIER', 'POST_CLOSE_SOURCE_WAIT', 'SOURCE_PUBLICATION',
    'AUTOMATION_CLOSING_DATA', 'AUTHORITY_RECHECK_AFTER_DATA',
    'SHADOW_ATTESTATION', 'AUTOMATION_SHADOW_ATTESTATION', 'AUTHORITY_RECHECK_AFTER_SHADOW',
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
            'SHADOW_ATTESTATION'} for row in panel.rows))


def _normal_idle(panel, row: Row) -> bool:
    policy = panel.row('automation')
    return (row.key in {'automation_cycle', 'automation_step_discovery'}
            and row.value in {'WAITING FOR NEXT DECISION', 'WAITING FOR CYCLE'}
            and row.recovery is not None and row.recovery.phase == 'AUTOMATION_DISCOVERY'
            and row.recovery.active(panel.now) and _aware(row.recovery.deadline)
            and panel.now < row.recovery.deadline and policy is not None
            and policy.effective_status(panel.now) == 'ok'
            and policy.value == 'ENABLED · KILL RELEASED'
            and _fresh_worker(panel, 'automation_leader'))


_HISTORY_CURRENT_FACTS = (
    'automation', 'automation_leader', 'authority', 'alpaca_account', 'broker',
    'feed', 'shadow_worker', 'shadow_verification', 'book', 'exposure', 'terminals',
    'runtime_identity', 'backup_restore', 'alert_dispatcher', 'automation_alerts',
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
    recovery = row.recovery if row is not None else None
    return (row is not None and row.key == 'paper_reconciliation'
            and row.value == 'CHECK IN PROGRESS' and row.paper_alignment is None
            and row.status == row.effective_status(panel.now) == 'warn'
            and row.required_current is True and not row.is_future(panel.now)
            and not row.is_stale(panel.now) and recovery is not None
            and recovery.phase == 'FINANCIAL_VERIFICATION'
            and recovery.automatic and not recovery.operator_required
            and _aware(recovery.deadline) and panel.now < recovery.deadline
            and row.valid_until == recovery.deadline and recovery.active(panel.now))


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


def _scheduled_work_normal(panel) -> bool:
    """Share current scheduling proof for historical audit and bounded PAPER work."""
    if (not panel.local_paper_mode or panel.source_errors
            or len({row.key for row in panel.rows}) != len(panel.rows)):
        return False
    paper, saved = panel.row('paper_reconciliation'), panel.row('paper_plan')
    if (saved is None or not saved.can_show_paper_plan(panel.now)
            or not (_historical_schedule_evidence(panel, paper, saved)
                    or _paper_check_normal(panel, paper))):
        return False
    plan = saved.paper_plan
    if (any(leg.action == 'UNAVAILABLE' for leg in plan.legs)
            or not all(_current_health_fact(panel, key) for key in _HISTORY_CURRENT_FACTS)
            or panel.row('automation').value != 'ENABLED · KILL RELEASED'
            or not panel.row('alpaca_account').can_show_paper_account(panel.now)
            or panel.row('feed').value != str(plan.decision_session)+' · 0 sessions behind'
            or panel.row('shadow_verification').value != 'SHADOW VERIFIED THROUGH '+str(plan.decision_session)
            or not _current_reconciliation_usable(panel)):
        return False
    for key, phase in (('automation_cycle', 'AUTOMATION_WAITING_OPEN'),
                       ('automation_step_open', 'AUTOMATION_OPEN')):
        row = panel.row(key)
        recovery = row.recovery if row is not None else None
        if (row is None or row.value != 'WAITING_OPEN'
                or row.effective_status(panel.now) != 'warn' or not row.required_current
                or not _aware(row.as_of) or row.is_future(panel.now) or row.is_stale(panel.now)
                or recovery is None or recovery.phase != phase
                or not recovery.automatic or recovery.operator_required
                or not _aware(recovery.deadline) or recovery.deadline < plan.execute_at
                or not recovery.active(panel.now)):
            return False
    return True


def _normal_warning(panel, row: Row) -> bool:
    if (row.key in {'paper_reconciliation', 'automation_cycle', 'automation_step_open'}
            and _scheduled_work_normal(panel)):
        return True
    recovery = row.recovery
    if (row.effective_status(panel.now) != 'warn' or recovery is None
            or not recovery.automatic or recovery.operator_required
            or not recovery.active(panel.now) or not _aware(recovery.deadline)
            or not panel.now < recovery.deadline or row.is_future(panel.now)):
        return False
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
            and row.value == 'WAITING_OPEN'
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
    """Describe admitted work, never infer a live stage from a retry string."""
    if _scheduled_work_normal(panel):
        return ('Checking paper account' if _paper_check_normal(panel, panel.row('paper_reconciliation'))
                else 'Waiting for market open')
    if _closing_source_proof(panel):
        phases = {row.recovery.phase for row in panel.rows
                  if is_closing_data_preparation(row, row.effective_status(panel.now))
                  and row.recovery.active(panel.now)}
        if 'SOURCE_PUBLICATION' in phases:
            return 'Publishing closing data'
        if phases & {'SHADOW_ATTESTATION', 'AUTOMATION_SHADOW_ATTESTATION'}:
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


def dashboard_health(panel) -> dict:
    """Human system health is separate from unchanged machine readiness."""
    plan = panel.row('paper_plan')
    plan_readiness = ('ready' if plan is not None and plan.can_show_paper_plan(panel.now)
                      else 'unavailable' if plan is not None
                      and plan.effective_status(panel.now) in {'fail', 'unknown'} else 'pending')
    statuses = [(row, row.effective_status(panel.now)) for row in panel.rows]
    warnings = [row for row, status in statuses
                if status == 'warn' and row.key not in OPERATIONAL_INFORMATIONAL_ROW_KEYS]
    negative = bool(panel.source_errors) or any(
        status in {'fail', 'unknown'} for _row, status in statuses)
    normal = bool(panel.rows) and not negative and (
        all(_normal_warning(panel, row) for row in warnings) if warnings
        else any(status == 'ok' for _row, status in statuses))
    status = 'fail' if negative else 'ok' if normal else 'warn'
    stage = preparation_stage(panel)
    label = ('Needs attention' if negative else 'Healthy'+(' · '+stage if stage else '')
             if status == 'ok' else
             ('Preparation delayed' if stage in {'Waiting to retry data acquisition',
                 'Data preparation awaiting a worker'} else 'Needs review')
             +(' · '+stage if stage else ''))
    broker = panel.row('broker')
    if (status == 'warn' and broker is not None and broker.effective_status(panel.now) == 'warn'
            and broker.recovery is not None and broker.recovery.phase == 'BROKER_FILL_SNAPSHOT'
            and broker.recovery.active(panel.now)):
        label = 'Reconciling fills'
    admitted = [row for row in warnings if _normal_warning(panel, row)]
    boundaries = [_row_boundary(row) for row in admitted]
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
    boundaries = [value for value in boundaries if value is not None]
    work = visible_preparation(panel)
    if work is not None:
        boundary = _preparation_boundary(work)
        if boundary is not None:
            boundaries.append(boundary)
        if work.active_at(panel.now) and not (stage == 'Publishing closing data'):
            boundaries.append(work.active_until)
    boundary = min(boundaries) if boundaries else None
    return dict(status=status, color={'ok': 'green', 'warn': 'amber', 'fail': 'red'}[status],
                label=label, valid_until=boundary.isoformat() if boundary is not None else None,
                plan_readiness=plan_readiness)


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
    if key == 'paper_reconciliation' and row.paper_alignment == 'SCHEDULED_WITH_HISTORY':
        label = 'Historical paper audit'
        if status == 'warn':
            value = 'Earlier-plan discrepancy retained · current plan scheduled'
            explanation = ('An authenticated discrepancy on an earlier transported plan remains '
                'recorded for audit. It does not by itself describe a current scheduling failure. '
                'PAPER performance remains unverified; future execution still runs its fresh '
                'account, restriction and reconciliation checks. '+row.detail)
        else:
            value = 'Current scheduled proof cannot be confirmed'
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
