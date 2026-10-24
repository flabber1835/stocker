"""Plain-language display only; never alter a financial or operational verdict."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo

from sentinel.panel.model import Row, FINANCIAL_AUTHORITY_ROW_KEYS

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
                       'PR release certification is suspended; this is separate from the '
                       'authority certificate’s original software references.')
    scheduled_paper = key == 'paper_reconciliation' and row.value == (
        'PAPER NOT VERIFIED · SCHEDULED · POST-CLOSE EVIDENCE PENDING')
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
    source_wait = row.recovery is not None and row.recovery.phase == 'SOURCE_FRONTIER'
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
    if source_wait and status == 'warn':
        explanation += (' Market data for the next decision is still pending. '
                        'Current-session verification must wait; retained values and holdings '
                        'keep their original attestation date.')
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
