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

from sentinel.panel.model import MAXIMUM_FUTURE_SKEW, OK, Panel, PaperOrderOutcome, ShadowSlot
from sentinel.panel.presentation import describe


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
    admitted = (row is not None and row.effective_status(panel.now) == OK
                and plan is not None and plan.execute_at > panel.now)
    if not admitted:
        return ('<section class="overview-card next-plan" aria-labelledby="next-plan-title">'
                '<div class="overview-heading"><h2 id="next-plan-title">Next trading plan</h2></div>'
                '<p class="overview-unavailable">No current saved plan available.</p>'
                '<p class="overview-note">Open System details for the recorded preparation and execution status.</p>'
                '</section>')
    actions = [leg for leg in plan.legs if leg.action != 'HOLD']
    date = plan.effective_session.strftime('%A, %b %d').replace(' 0', ' ')
    start = plan.execute_at.astimezone(ZoneInfo('America/Los_Angeles')).strftime('%I:%M %p').lstrip('0')
    outcomes = [outcome for outcome in row.order_outcomes
                if outcome.observed_at-panel.now <= MAXIMUM_FUTURE_SKEW]
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


def _account_html(panel: Panel) -> str:
    row = panel.row('alpaca_account')
    account = row.paper_account if row is not None and row.effective_status(panel.now) == OK else None
    if account is not None and account.observed_at-panel.now > MAXIMUM_FUTURE_SKEW:
        account = None
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
            +retained+_plan_html(panel)+_account_html(panel)+_slots_html(panel)+'</main>')


OVERVIEW_CSS = '''
:root,:root[data-theme="dark"],:root[data-theme="light"]{
 --bg:#16111f;--card:#241c30;--ink:#f5eee3;--muted:#c2b7c8;--line:#4d3c57;
 --ok:#8ce0b4;--warn:#f2cd83;--fail:#ffa69e;--pending:#c4bfd1;
 --okbg:#20392f;--warnbg:#493b23;--failbg:#492c32;--pendingbg:#30283c;
 --shadow:0 8px 28px #0002;
}
body{background:radial-gradient(ellipse at 50% 0%,#342039 0,transparent 52%),#16111f;
 padding:max(18px,env(safe-area-inset-top)) max(14px,env(safe-area-inset-right))
 max(24px,env(safe-area-inset-bottom)) max(14px,env(safe-area-inset-left));font-size:15px}
.wrap{max-width:760px}.casino-stage,.casino-accent{display:none}
header{padding:6px 0 0;border:0;border-radius:0;background:none;box-shadow:none;margin:0 0 18px}
.brand{gap:12px}.brand img{width:42px;height:42px;border-radius:11px;border:1px solid #a98750}
h1{font-family:Georgia,serif;font-size:clamp(16px,4.9vw,25px);letter-spacing:.11em;color:#eacb8e;line-height:1.2}
.brand-subtitle{font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--muted);margin-top:5px}
.state{display:block;border:1px solid currentColor;border-radius:12px;font-size:12px;letter-spacing:.045em;
 padding:12px 14px;margin-top:19px;line-height:1.4;text-transform:none}
.heartbeat{margin:9px 2px 0;font-size:11px;letter-spacing:0;line-height:1.5}
.status-reasons{padding:0 3px}.status-reasons ul{padding-left:19px}.status-reasons a{color:var(--fail)}
.overview{display:grid;gap:14px}.overview-card{min-width:0;background:linear-gradient(135deg,#2c2336,#211a2b);
 border:1px solid #56435c;border-radius:17px;padding:20px;box-shadow:var(--shadow)}
.overview-heading{display:flex;gap:12px;align-items:center;justify-content:space-between;min-width:0}
.overview h2{font-family:Georgia,serif;font-size:23px;font-weight:400;color:#f2e5cb;margin:0;line-height:1.25}
.overview-eyebrow{margin:0 0 5px;color:#cdb899;font-size:10px;letter-spacing:.15em;text-transform:uppercase}
.overview-tag{font-size:10px;color:#e5c68c;border:1px solid #806348;border-radius:6px;padding:4px 7px;
 flex:0 0 auto;max-width:47%;overflow-wrap:anywhere;letter-spacing:.055em}
.plan-schedule{display:flex;justify-content:space-between;gap:12px;margin:17px 0 0;font-size:12px;color:var(--muted);
 flex-wrap:wrap}.plan-schedule strong{color:#eddfca;font-weight:600}.plan-legs{list-style:none;margin:12px 0;padding:0}
.plan-leg{border-top:1px solid var(--line);padding:14px 0 12px}.plan-leg-main{display:grid;
 grid-template-columns:minmax(60px,1fr) auto minmax(78px,auto);align-items:center;gap:10px}
.plan-ticker{font-size:21px;font-weight:650;overflow-wrap:anywhere}.plan-action{font-size:10px;text-transform:uppercase;
 padding:4px 8px;border-radius:5px;letter-spacing:.05em;color:var(--pending);background:var(--pendingbg)}
.plan-leg.buy .plan-action{color:var(--ok);background:var(--okbg)}
.plan-leg.sell .plan-action{color:#ffb2ab;background:#492f37}
.plan-quantity{font-size:14px;text-align:right;font-weight:550;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.plan-leg-basis{font-size:11px;color:var(--muted);margin-top:4px;font-variant-numeric:tabular-nums}
.plan-outcome{border-left:2px solid #bb904d;background:#3b2d29;padding:9px 10px;margin-top:11px;
 color:#f1cc8d;font-size:12px;line-height:1.5}.no-plan-changes{color:var(--muted);font-size:14px;padding:10px 0}
.overview-note,.overview-evidence{font-size:11px;line-height:1.6;color:var(--muted);margin:9px 0 0;overflow-wrap:anywhere}
.overview-evidence{font-size:10px}.overview-inline-details{background:none;border:0;border-radius:0;box-shadow:none;margin:4px 0 0}
.overview-inline-details summary{padding:0;font-size:10px;font-weight:400;text-decoration:underline;color:inherit}
.overview-inline-details .detail-body{padding:7px 0 0;color:var(--muted);font-size:10px;overflow-wrap:anywhere}
.overview-disclosure{border:0;border-top:1px solid var(--line);border-radius:0;background:none;box-shadow:none;margin:14px 0 0}
.overview-disclosure summary{padding:12px 0 0;color:#e7c88f;font-size:12px;font-weight:500}
.overview-disclosure summary span{float:right;color:var(--muted)}.overview-disclosure .detail-body{padding:12px 0 0}
.overview-table-scroll{overflow-x:auto}.overview table{min-width:350px}.overview th,.overview td{font-size:11px}
.overview td{white-space:nowrap}.account-overview{padding:16px 20px}.account-overview h2{font-size:17px}
.account-stats{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:14px}
.account-stats>div+div{border-left:1px solid var(--line);padding-left:20px}
.account-stats span{font-size:11px;color:var(--muted);display:block}.account-stats strong{font-size:24px;
 font-weight:550;display:block;margin-top:3px;font-variant-numeric:tabular-nums;letter-spacing:-.02em;overflow-wrap:anywhere}
.slot-counts{display:flex;flex-wrap:wrap;gap:7px 15px;font-size:11px;color:var(--muted);margin:12px 0 15px}
.slot-counts span:first-child{color:#bfe1c9}.slot-grid{list-style:none;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
 gap:9px;padding:0;margin:0}.slot-tile{min-width:0;display:flex;flex-direction:column;align-items:flex-start;
 background:#30263b;border:1px solid #5a485e;border-radius:10px;padding:11px 10px;min-height:120px}
.slot-tile.occupied{border-top:2px solid #8caf91}.slot-tile.exit-pending{border-top-color:#df9a94}
.slot-tile.cooling{background:#2a2433;border-style:dashed;border-color:#665140}
.slot-tile.reserved{border-top:2px solid #baafdb}.slot-tile.ready{border-color:#8caf91}
.slot-number{font-size:9px;color:#baacc3;text-transform:uppercase;letter-spacing:.07em}
.slot-main{font-size:22px;line-height:1.25;font-weight:550;margin:7px 0 3px;overflow-wrap:anywhere;max-width:100%}
.slot-tile.cooling .slot-main{color:#edcb89}.slot-tile.ready .slot-main{color:var(--ok);font-size:20px}
.slot-state{font-size:10px;line-height:1.35;color:#d0c4d5}.exit-pending .slot-state{color:#ffb2ab}
.slot-evidence{margin:8px 0 0;border:0;border-radius:0;background:none;box-shadow:none;overflow:visible;width:100%}
.slot-evidence summary{padding:0;font-size:9px;font-weight:400;color:#bbadbd}
.slot-evidence>div{font-size:10px;line-height:1.5;color:var(--muted);padding-top:7px;overflow-wrap:anywhere}
.overview-unavailable{color:var(--warn);font-size:14px;margin:14px 0 0}
.overview-history,.overview-retained,.overview-withdrawn{font-size:12px;line-height:1.5;margin:0;
 color:var(--warn);padding:10px 12px;background:var(--warnbg);border-radius:8px}
.overview-history{margin-bottom:12px}.overview-withdrawn{display:none}
.not-current .overview-withdrawn{display:block;color:var(--fail);background:var(--failbg)}
.not-current .overview-card{border-color:var(--fail)}
.not-current .overview-card h2::after{content:" · LAST KNOWN";font:10px ui-sans-serif,sans-serif;color:var(--fail)}
.not-current .plan-action,.not-current .plan-leg.buy .plan-action,.not-current .overview-tag,
 .not-current .slot-state,.not-current .slot-tile.ready .slot-main,.not-current .slot-counts span:first-child{color:var(--fail)}
.refreshing-status .overview-withdrawn{display:block;color:var(--warn);background:var(--warnbg)}
.refreshing-status .overview-card{border-color:#9a7949}
.refreshing-status .overview-card h2::after{content:" · LAST KNOWN";font:10px ui-sans-serif,sans-serif;color:var(--warn)}
.retained-overview .overview-card{border-color:#9a7949}
.retained-overview .overview-card h2::after{content:" · LAST KNOWN";font:10px ui-sans-serif,sans-serif;color:var(--warn)}
.refreshing-status .slot-tile,.refreshing-status .slot-tile.occupied,.refreshing-status .slot-tile.ready,
 .retained-overview .slot-tile,.retained-overview .slot-tile.occupied,.retained-overview .slot-tile.ready{border-color:#9a7949}
.refreshing-status .plan-leg.buy .plan-action,.refreshing-status .slot-tile.ready .slot-main,
 .refreshing-status .slot-counts span:first-child,.retained-overview .plan-leg.buy .plan-action,
 .retained-overview .slot-tile.ready .slot-main,.retained-overview .slot-counts span:first-child{color:var(--warn)}
.not-current .slot-tile,.not-current .slot-tile.occupied,.not-current .slot-tile.ready{border-color:var(--fail)}
.not-current .plan-leg.buy .plan-action,.not-current .slot-tile.ready .slot-main,
 .not-current .slot-counts span:first-child{color:var(--fail)}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
#system-details{margin-top:18px;background:#201a29;border-color:#493c51;border-radius:13px}
#system-details>summary{padding:15px 17px;color:#cbbcce;font-size:13px;font-weight:500}
#system-details>.detail-body{padding:0 12px 12px;overflow:visible}#system-details .mode-guide{margin-top:0;font-size:12px}
#system-details .row{padding:14px 13px;background:#261f30;border-radius:11px;border-color:#493c51}
#system-details .value{font-size:17px}#system-details .label{font-size:10px}
#system-details .detail{font-size:12px;line-height:1.5}#system-details .push-card{background:#261f30}
button:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid #f4d79b;outline-offset:3px}
footer{font-size:10px;color:#b5a8be;line-height:1.7;margin-top:18px}footer>.technical{font-size:10px;background:none;border:0;box-shadow:none}
footer>.technical>summary{font-size:10px;font-weight:400;padding:4px}
@media(min-width:600px){.overview-card{padding:23px}.slot-grid{gap:12px}.slot-tile{min-height:127px;padding:14px}.slot-main{font-size:26px}}
@media(max-width:420px){.overview-card{padding:17px 14px}.overview h2{font-size:21px}.account-overview h2{font-size:16px}
 .account-stats strong{font-size:22px}.slot-grid{gap:7px}.slot-tile{padding:10px 7px}.slot-main{font-size:20px}
 .overview-heading{gap:8px}.overview-tag{font-size:9px;padding:4px 5px}.plan-leg-main{gap:7px}}
@media(max-width:360px){.slot-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.slot-tile{min-height:115px;padding:12px}
 .slot-main{font-size:24px}.overview h2{font-size:20px}.account-overview h2{font-size:16px}.account-stats strong{font-size:21px}
 .account-stats>div+div{padding-left:14px}.account-stats{gap:10px}.plan-ticker{font-size:19px}.plan-quantity{font-size:13px}}
'''
