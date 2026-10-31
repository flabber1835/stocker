"""The plan-first dashboard projection. Pure formatting of admitted facts only.

The full operational rows remain the source of status and freshness. Moving a
fact into this overview must never extend its authority or turn a target into
a broker holding. This module performs no reads, writes, clock calls or trades.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from sentinel.panel.model import FAIL, OK, UNKNOWN, Panel, PaperOrderOutcome, ShadowSlot
from sentinel.panel.presentation import describe, dashboard_health, preparation_stage, visible_preparation


def _esc(value) -> str:
    return escape(str(value), quote=True)


def _quantity(value: Decimal | None) -> str:
    if value is None:
        return 'Unavailable'
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _clock(value: datetime | None) -> str:
    if value is None:
        return 'Unavailable'
    local = value.astimezone(ZoneInfo('America/Los_Angeles'))
    return local.strftime('%b %d, %Y · %I:%M %p Pacific').replace(' 0', ' ')


def _stamp(value: datetime | None, *, label: str) -> str:
    return '<p class="overview-evidence">'+_esc(label)+' '+_esc(_clock(value))+'</p>'


def _outcome_text(outcome: PaperOrderOutcome) -> str:
    filled, total = _quantity(outcome.filled_quantity), _quantity(outcome.quantity)
    if outcome.state == 'FILLED':
        state = 'filled'
    elif outcome.state == 'CANCELLED':
        # The command journal normalizes native cancellation and expiry. It
        # does not retain enough native evidence to distinguish their causes.
        state = 'ended unfilled' if outcome.filled_quantity == 0 else 'ended partially filled'
    elif outcome.state == 'REJECTED':
        state = 'rejected'
    elif outcome.state == 'PARTIALLY_FILLED':
        state = 'partially filled; remainder not confirmed complete'
    elif outcome.state == 'ACKNOWLEDGED':
        state = 'recorded as working'
    elif outcome.state == 'CANCEL_PENDING':
        state = 'cancellation pending'
    elif outcome.state == 'UNKNOWN':
        state = 'outcome uncertain'
    elif outcome.state in {'PLANNED', 'SEND_PENDING'}:
        state = 'submission not confirmed'
    else:
        state = 'superseded; final broker outcome not established'
    return f'Previous {outcome.side.lower()} {state} · {filled}/{total} shares filled'


def _outcome_html(outcome: PaperOrderOutcome) -> str:
    return (
        '<div class="plan-outcome" data-order-state="'+_esc(outcome.state)+'">'
        +_esc(_outcome_text(outcome))
        +'<details class="overview-inline-details" data-detail-key="overview-order-'
        +_esc(outcome.broker_order_id)+'"><summary>Order evidence</summary>'
        '<div class="detail-body">Recorded '+_esc(_clock(outcome.observed_at))
        +'<br>Client order: '+_esc(outcome.client_key)
        +'<br>Broker order: '+_esc(outcome.broker_order_id)+'</div></details></div>')


def _leg_html(leg, outcomes) -> str:
    if leg.action == 'UNAVAILABLE':
        action, quantity = 'Change unavailable', 'Recorded shares unavailable'
    elif leg.opening_dollars is not None:
        action, quantity = 'Buy', f'${leg.opening_dollars:,.2f} budget'
    elif leg.action in {'BUY', 'SELL'}:
        action = leg.action.title()
        amount = abs(leg.change_quantity) if leg.change_quantity is not None else None
        quantity = _quantity(amount)+' '+('share' if amount == 1 else 'shares')
    else:
        action, quantity = 'Keep', _quantity(leg.target_quantity)+' shares'
    target = ('$'+f'{leg.opening_dollars:,.2f}'+' budget · sized at execution'
              if leg.opening_dollars is not None else _quantity(leg.target_quantity)+' target')
    prior = ''.join(_outcome_html(outcome) for outcome in outcomes
                    if outcome.security_id == leg.security_id and outcome.side == leg.action)
    return (
        '<li class="plan-leg '+_esc(leg.action.lower())+'" data-security-id="'+_esc(leg.security_id)+'">'
        '<div class="plan-leg-main"><strong class="plan-ticker">'+_esc(leg.ticker)+'</strong>'
        '<span class="plan-action">'+_esc(action)+'</span>'
        '<strong class="plan-quantity">'+_esc(quantity)+'</strong></div>'
        '<div class="plan-leg-basis">'+_esc(_quantity(leg.current_quantity))+' recorded → '
        +_esc(target)+'</div>'+prior+'</li>')


def _plan_html(panel: Panel) -> str:
    row = panel.row('paper_plan')
    plan = row.paper_plan if row is not None else None
    # The saved plan expires at the same boundary as its original row. Neither
    # the overview nor a retained response can promote an expired plan.
    admitted = row is not None and row.can_show_paper_plan(panel.now)
    if not admitted:
        current = _run_html(panel)
        if current:
            return current
        unavailable = any(item is not None and item.effective_status(panel.now) in {FAIL, UNKNOWN}
                          for item in (row, panel.row('trading_run'),
                                       panel.row('completed_trading_run')))
        if not unavailable and visible_preparation(panel) is not None:
            return ''  # The dated preparation card already describes this absence.
        message = 'Saved trading plan unavailable.' if unavailable else 'Next trading plan pending.'
        return ('<section class="overview-card next-plan" aria-labelledby="next-plan-title">'
                '<div class="overview-heading"><h2 id="next-plan-title">Next trading plan</h2></div>'
                '<p class="overview-unavailable">'+_esc(message)+'</p>'
                '<p class="overview-note">Open System details for the recorded preparation and execution status.</p>'
                '</section>')
    actions = [leg for leg in plan.legs if leg.action != 'HOLD']
    date = plan.effective_session.strftime('%A, %b %d').replace(' 0', ' ')
    start = plan.execute_at.astimezone(ZoneInfo('America/Los_Angeles')).strftime('%I:%M %p').lstrip('0')
    outcomes = row.visible_order_outcomes(panel.now)
    changes = (''.join(_leg_html(leg, outcomes) for leg in actions)
               if actions else '<li class="no-plan-changes">No share changes in the saved plan.</li>')
    targets = ''.join(
        '<tr><th scope="row">'+_esc(leg.ticker)+'</th><td>'+_esc(leg.action.title())+'</td><td>'
        +_esc(_quantity(leg.current_quantity))+'</td><td>'
        +_esc(('$'+f'{leg.opening_dollars:,.2f}'+' budget') if leg.opening_dollars is not None
               else _quantity(leg.target_quantity))+'</td></tr>' for leg in plan.legs)
    return (
        '<section class="overview-card next-plan" aria-labelledby="next-plan-title">'
        '<div class="overview-heading"><div><p class="overview-eyebrow">The next session</p>'
        '<h2 id="next-plan-title">Next trading plan</h2></div>'
        '<span class="overview-tag">PAPER</span></div>'
        '<div class="plan-schedule"><strong>'+_esc(date)+'</strong><span>From '+_esc(start)+' Pacific</span></div>'
        '<ul class="plan-legs">'+changes+'</ul>'
        '<p class="overview-note">Saved proposals, not submitted orders or fills. Buy limits and funding '
        'are checked at execution.</p>'
        +_stamp(plan.observation_at, label='Recorded shares:')
        +'<details class="overview-disclosure" data-detail-key="overview-all-targets"><summary>All saved targets <span>'
        +str(len(plan.legs))+'</span></summary><div class="detail-body">'
        '<div class="overview-table-scroll"><table><thead><tr><th>Ticker</th><th>Action</th>'
        '<th>Recorded shares</th><th>Target</th></tr></thead><tbody>'+targets+'</tbody></table></div>'
        '<p class="overview-note">Decision close: '+_esc(plan.decision_session)+'. Saved '
        +_esc(_clock(plan.created_at))+'. Targets are estimates based on the dated account snapshot.</p>'
        '</div></details></section>')


def _preparation_html(panel: Panel, *, refresh_pending: bool = False) -> str:
    planned = panel.row('paper_plan')
    if planned is not None and planned.can_show_paper_plan(panel.now):
        return ''
    work = visible_preparation(panel)
    if work is None:
        return ''
    stage = preparation_stage(panel)
    if stage is None:
        return ''
    if refresh_pending:
        stage = 'Last known · '+stage
    date = work.effective_session.strftime('%A, %b %d').replace(' 0', ' ')
    retry = (_stamp(work.next_retry, label='Recorded retry:')
             if work.state in {'WAIT_SOURCE', 'RETRY_WAIT'} and work.next_retry is not None else '')
    return (
        '<section class="overview-card next-plan" aria-labelledby="preparation-title">'
        '<div class="overview-heading"><div><p class="overview-eyebrow">The next session</p>'
        '<h2 id="preparation-title">Next trading plan · preparing</h2></div>'
        '<span class="overview-tag">PAPER</span></div>'
        '<div class="plan-schedule"><strong>'+_esc(date)+'</strong>'
        '<span>Plan not ready yet</span></div>'
        '<p id="preparation-stage" class="overview-note">'+_esc(stage)+'</p>'
        '<p class="overview-note">Current-stage rows recorded: '+_esc(f'{work.rows_done:,}')
        +'. Source components completed: '+_esc(f'{work.components_done:,}')+'.</p>'
        '<p class="overview-note">Closing session: '+_esc(work.decision_session)
        +'. These recorded counters do not estimate completion time.</p>'
        +_stamp(work.last_progress_at, label='Last recorded progress:')+retry+'</section>')


def _plan_readiness_html(panel: Panel, *, refresh_pending: bool = False) -> str:
    readiness = dashboard_health(panel)['plan_readiness']
    value = {'ready': 'Next trading plan: saved for its scheduled market open.',
             'pending': 'Next trading plan: not ready yet.',
             'unavailable': 'Next trading plan: unavailable; see System details.'}[readiness]
    if refresh_pending:
        value = 'Last known · '+value
    return '<p id="plan-readiness" class="overview-note">'+_esc(value)+'</p>'


def _run_html(panel: Panel) -> str:
    row = panel.row('trading_run')
    historical = row is None
    if historical:
        row = panel.row('completed_trading_run')
    if row is None or not row.can_show_trading_run(panel.now):
        return ''
    run = row.trading_run
    heading = ('Today’s trades · completed' if run.state == 'SUCCEEDED'
               else 'Today’s trading plan')
    stage = {'EXECUTING':'Trading in progress','RECONCILING':'Reconciling fills',
             'RETRY_WAIT':'Waiting for the next check','SUCCEEDED':'Run completed',
             'FAILED':'Run failed','ABANDONED':'Run abandoned','SUPERSEDED':'Run superseded',
             'PLAN_READY':'Plan ready','WAITING_OPEN':'Waiting for market open'}[run.state]
    rows = []
    for leg in run.intent.legs:
        if leg.action == 'HOLD':
            continue
        orders = [item for item in run.orders if item.security_id == leg.security_id]
        filled = sum((item.filled_quantity for item in orders),Decimal(0))
        submitted = sum((item.quantity for item in orders),Decimal(0))
        value = sum((item.filled_quantity*(item.filled_average_price or Decimal(0))
                     for item in orders),Decimal(0))
        states = {item.state for item in orders}
        state = ('Outcome uncertain' if 'UNKNOWN' in states else 'Cancellation pending'
                 if 'CANCEL_PENDING' in states else 'Submission not confirmed'
                 if 'SEND_PENDING' in states else 'Filled' if orders and states=={'FILLED'}
                 else 'Partly filled' if filled>0 else 'Rejected' if 'REJECTED' in states
                 else 'Ended unfilled' if states and states<={'CANCELLED','REJECTED','SUPERSEDED'}
                 else 'Working' if states & {'ACKNOWLEDGED','PARTIALLY_FILLED'}
                 else 'Awaiting submission' if run.state!='SUCCEEDED' else 'No order recorded')
        amount = ('Budget $'+f'{leg.opening_dollars:,.2f}' if leg.opening_dollars is not None
                  else _quantity(abs(leg.change_quantity))+' shares')
        progress = (state+' · '+_quantity(filled)+'/'+_quantity(submitted)+' submitted shares filled'
                    if orders else state)
        if filled:
            progress += ' · avg $'+f'{value/filled:,.2f}'
        detail = ''.join('<p>'+_esc(item.state)+' · '+_quantity(item.filled_quantity)+'/'
            +_quantity(item.quantity)+' shares · '+_esc(_clock(item.observed_at))
            +'<br>'+_esc(item.order_terms['order_type'].title())
            +(' $'+_esc(item.order_terms['limit_price']) if item.order_terms['limit_price'] is not None else '')
            +' · '+_esc(item.order_terms['time_in_force'].upper())
            +'<br>Client order: '+_esc(item.client_key)+'<br>Broker order: '
            +_esc(item.broker_order_id or 'Not confirmed')+'</p>' for item in orders)
        rows.append('<li class="plan-leg '+leg.action.lower()+'"><div class="plan-leg-main">'
            '<strong class="plan-ticker">'+_esc(leg.ticker)+'</strong><span class="plan-action">'
            +_esc(leg.action.title())+'</span><strong class="plan-quantity">'+_esc(amount)
            +'</strong></div><p class="run-progress">'+_esc(progress)+'</p>'
            +('<details class="overview-inline-details" data-detail-key="run-'+_esc(leg.security_id)
              +'"><summary>Order details</summary><div class="detail-body">'+detail+'</div></details>' if orders else '')+'</li>')
    recorded_note = ''
    if historical:
        future = panel.row('paper_plan')
        next_note = ('' if future is not None and future.can_show_paper_plan(panel.now)
                     else ' The next trading plan is unavailable.' if future is not None
                         and future.effective_status(panel.now) in {FAIL, UNKNOWN}
                     else ' The next trading plan is pending.')
        recorded_note = '<p class="overview-note">Recorded completed run.'+next_note+'</p>'
    return ('<section class="overview-card current-trades" aria-labelledby="current-trades-title">'
        '<div class="overview-heading"><h2 id="current-trades-title">'+_esc(heading)+'</h2>'
        '<span class="overview-tag">PAPER</span></div><div class="plan-schedule"><strong>'
        +_esc(run.intent.effective_session.strftime('%A, %b %d'))+'</strong><span>'+_esc(stage)
        +'</span></div><ul class="plan-legs">'+(''.join(rows) or '<li>No share changes in this plan.</li>')
        +'</ul><p class="overview-note">Original saved plan; progress comes from recorded orders. '
        'Post-close account verification is separate.</p>'
        +recorded_note
        +_stamp(row.as_of,label='Progress recorded:')+'</section>')


def _account_html(panel: Panel) -> str:
    row = panel.row('alpaca_account')
    account = row.paper_account if row is not None and row.can_show_paper_account(panel.now) else None
    if account is None:
        return ('<section class="overview-card account-overview" aria-labelledby="account-overview-title">'
                '<h2 id="account-overview-title">Recorded paper account</h2>'
                '<p class="overview-unavailable">Account totals unavailable.</p></section>')
    return (
        '<section class="overview-card account-overview" aria-labelledby="account-overview-title">'
        '<div class="overview-heading"><h2 id="account-overview-title">Recorded paper account</h2>'
        '<span class="overview-tag">ALPACA</span></div>'
        '<div class="account-stats"><div><span>Account value</span><strong>$'+f'{account.equity:,.2f}'
        +'</strong></div><div><span>Cash · '+f'{account.cash/account.equity*100:.1f}'
        +'%</span><strong>$'+f'{account.cash:,.2f}'+'</strong></div></div>'
        +_stamp(account.observed_at, label='Account snapshot:')+'</section>')


def _slot_html(slot: ShadowSlot) -> str:
    number = f'{slot.slot_id+1:02d}'
    if slot.state == 'OCCUPIED':
        main = _esc(slot.ticker)
        state = 'Exit signalled' if slot.exit_pending else 'Holding'
        detail = 'Model quantity: '+_quantity(slot.model_quantity)+' shares.'
        if slot.exit_pending:
            detail += ' Pending strategy exit'+(': '+str(slot.exit_reason) if slot.exit_reason else '')+'.'
    elif slot.state == 'COOLING':
        main = str(slot.cooldown_remaining)
        state = 'session left' if slot.cooldown_remaining == 1 else 'sessions left'
        detail = (f'Cooldown: {slot.cooldown_elapsed} of {slot.cooldown_total} trading sessions completed. '
                  'This slot retains cash while cooling down.')
    elif slot.state == 'RESERVED':
        main, state = _esc(slot.ticker), 'Entry pending'
        detail = 'Reserved for a pending strategy entry. This is not a filled model or paper holding.'
    else:
        main, state = 'Ready', 'Awaiting signal'
        detail = 'Cooldown complete. Available for a qualifying strategy entry; no purchase is promised.'
    css = slot.state.lower()+(' exit-pending' if slot.exit_pending else '')
    return (
        '<li class="slot-tile '+css+'" data-slot-id="'+str(slot.slot_id)+'" data-slot-state="'+slot.state+'">'
        '<span class="slot-number">Slot '+number+'</span><strong class="slot-main">'+main+'</strong>'
        '<span class="slot-state">'+_esc(state)+'</span>'
        '<details class="slot-evidence" data-detail-key="overview-slot-'+str(slot.slot_id)+'">'
        '<summary><span class="sr-only">Slot '+number+' </span>Details</summary>'
        '<div>'+_esc(detail)+'<br>Canonical slot index: '+str(slot.slot_id)+'.</div></details></li>')


def _slots_html(panel: Panel) -> str:
    row = panel.row('book')
    book = row.shadow_book if row is not None and row.can_show_shadow_book(panel.now) else None
    if book is None or not book.slots:
        return ('<section class="overview-card core-slots" aria-labelledby="core-slots-title">'
                '<h2 id="core-slots-title">Wealth Core slots</h2>'
                '<p class="overview-unavailable">Canonical slots unavailable.</p>'
                '<p class="overview-note">Missing evidence is not treated as empty or ready slots.</p></section>')
    counts = {state: sum(slot.state == state for slot in book.slots)
              for state in ('OCCUPIED', 'COOLING', 'RESERVED', 'READY')}
    badges = ''.join('<span>'+str(counts[state])+' '+label+'</span>' for state, label in (
        ('OCCUPIED', 'held'), ('COOLING', 'cooling'), ('RESERVED', 'reserved'), ('READY', 'ready'))
        if counts[state] or state in {'OCCUPIED', 'COOLING'})
    exposure_row = panel.row('exposure')
    exposure = ('<span class="overview-tag">Planned Core '+_esc(describe(exposure_row, OK)[1])+'</span>'
                if exposure_row is not None and exposure_row.effective_status(panel.now) == OK else '')
    historical = row.effective_status(panel.now) != OK
    return (
        '<section class="overview-card core-slots" aria-labelledby="core-slots-title">'
        '<div class="overview-heading"><div><p class="overview-eyebrow">The strategy book</p>'
        '<h2 id="core-slots-title">Wealth Core · '+str(len(book.slots))+' slots</h2></div>'+exposure+'</div>'
        '<p class="slot-counts">'+badges+'</p>'
        +('<p class="overview-history">Last attested through '+_esc(book.session)
          +' · current session not verified.</p>' if historical else '')
        +'<ol class="slot-grid" aria-label="Canonical strategy slots">'
        +''.join(_slot_html(slot) for slot in sorted(book.slots, key=lambda item: item.slot_id))+'</ol>'
        '<p class="overview-note">Unscaled model book as of '+_esc(book.session)
        +'. These are strategy slots, not paper share counts. Cooldowns count trading sessions; '
        'empty slots keep cash.</p></section>')


def overview_html(panel: Panel, *, refresh_pending: bool = False) -> str:
    """Render admitted trading intent, account totals and canonical slot facts."""
    retained = ('<p class="overview-retained">Last known overview · refreshing status. '
                'The original evidence times are shown below.</p>' if refresh_pending else '')
    css = 'overview retained-overview' if refresh_pending else 'overview'
    return ('<main class="'+css+'" aria-label="Trading overview">'
            '<p class="overview-withdrawn">Last known overview · status is not current.</p>'
            +retained+_plan_readiness_html(panel, refresh_pending=refresh_pending)
            +_preparation_html(panel, refresh_pending=refresh_pending)+_plan_html(panel)
            +(_run_html(panel) if panel.row('paper_plan') is not None
              and panel.row('paper_plan').can_show_paper_plan(panel.now) else '')
            +_account_html(panel)+_slots_html(panel)+'</main>')
