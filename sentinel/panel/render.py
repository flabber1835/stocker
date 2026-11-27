"""The panel's HTML. PURE: takes a `Panel`, returns a string.

ONE PAGE, NO TABS, NO FINANCIAL ACTIONS. The Stocker dashboard had eight tabs
and a trade-approval button; this replaces all of it. Read-only means there is
no control on this page that could ever submit, approve or liquidate — not
disabled, ABSENT. The remaining actions manage this browser's notification
delivery or acknowledge reviewed operator history; neither changes orders.

MOBILE FIRST, and specifically for a phone held in one hand at 22:47 wondering
whether the seed is still alive. The layout is a single column at every width;
there is no breakpoint at which content moves, because the failure mode of a
responsive dashboard is that the thing you needed was in the column that
collapsed.

JavaScript can invalidate an old DOM and manage a Web Push subscription. It
never computes or promotes a financial verdict and cannot express an order.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from sentinel.panel.presentation import (
    activation_wait_history, activation_wait_withdraws, current_activation_fee_wait,
    dashboard_health, describe,
)
from sentinel.panel.overview import overview_html
from sentinel.panel.run_progress import current_execution_refusal, order_summary
from sentinel.panel.styles import CSS
from sentinel.panel.banner import BANNER_SCRIPT
from sentinel.panel.dom_refresh import SCRIPT as DOM_REFRESH_SCRIPT
from sentinel.panel.pwa import (
    CURRENT_DOCUMENT_SCRIPT, MAX_DOCUMENT_AGE_SECONDS, REQUEST_DEADLINE_SCRIPT,
)
from sentinel.panel.review_controls import render as render_review, SCRIPT as REVIEW_SCRIPT

from sentinel.panel.model import (
    FAIL, OK, PENDING, TRIAL_ROW_KEYS,
    UNKNOWN, WARN, Panel, Row)

#: Refresh cadence. Long enough not to hammer the database from a phone left on
#: a desk, short enough that a stalled ingest is visible within a coffee.
REFRESH_SECONDS = 30
PRESENTATION_MAX_AGE_SECONDS = MAX_DOCUMENT_AGE_SECONDS

_DOT = {OK: "●", WARN: "▲", FAIL: "■", PENDING: "○", UNKNOWN: "?", 'neutral': '○'}


# The inline controller is part of this source file. Imported scripts contribute
# their actual bytes so an edit to any running handler changes the handoff ID.
CONTROLLER_VERSION = sha256(Path(__file__).read_bytes() + b'\0' +
    '\0'.join((CURRENT_DOCUMENT_SCRIPT, DOM_REFRESH_SCRIPT, REVIEW_SCRIPT, BANNER_SCRIPT, CSS)).encode()).hexdigest()


def _ago(delta) -> str:
    if delta is None:
        return ""
    s = int(delta.total_seconds())
    if s < 0:
        return "in the future"          # clock skew; say so rather than hide it
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        h, m = s // 3600, (s % 3600) // 60
        return f"{h}h {m}m ago" if m else f"{h}h ago"
    d, h = s // 86400, (s % 86400) // 3600
    return f"{d}d {h}h ago" if h else f"{d}d ago"



PUSH_SCRIPT = r"""
(function(){
""" + REQUEST_DEADLINE_SCRIPT + r"""
  var card = document.getElementById("push-card");
  var enable = document.getElementById("push-enable");
  var remove = document.getElementById("push-remove");
  var status = document.getElementById("push-status");
  function message(value) { status.textContent = value; }
  function decode(value) {
    var padding = "=".repeat((4 - value.length % 4) % 4);
    var binary = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(binary, function(ch) { return ch.charCodeAt(0); });
  }
  async function registration() {
    return navigator.serviceWorker.register("/service-worker.js", {scope: "/", updateViaCache: "none"});
  }
  function pushRequest(url, options, error, readJson) {
    var controller = new AbortController();
    return dashboardDeadline(controller, async function() {
      var response = await fetch(url, Object.assign({}, options, {signal: controller.signal}));
      if (!response.ok) { throw new Error(error); }
      return readJson ? response.json() : undefined;
    });
  }
  function deliveryMessage(receipt) {
    if (receipt.delivery_status === "ACCEPTED") {
      message("Test accepted by the push service. Check this device’s notifications.");
      return true;
    }
    if (receipt.delivery_status === "FAILED") {
      message("Test notification failed. Check Notification delivery on the dashboard.");
      return true;
    }
    if (receipt.delivery_status === "CANCELLED") {
      message("Test cancelled because notifications were disabled on this device.");
      return true;
    }
    message(receipt.sender_available
      ? "A single test notification is queued; waiting for the push service."
      : "Test queued, but the notification sender is unavailable. Check Notification delivery on the dashboard.");
    return false;
  }
  async function followTest(receipt) {
    if (deliveryMessage(receipt) || !receipt.alert_id) { return; }
    for (var attempt = 0; attempt < 10; attempt++) {
      await new Promise(function(resolve) { setTimeout(resolve, 2000); });
      try {
        receipt = await pushRequest("/push/tests/" + encodeURIComponent(receipt.alert_id), {
          credentials: "same-origin", cache: "no-store"
        }, "status unavailable", true);
      } catch (_) {
        message("Test is queued, but its current delivery status could not be read.");
        return;
      }
      if (deliveryMessage(receipt)) { return; }
    }
  }
  async function refreshButtons() {
    var reg = await registration();
    var sub = await reg.pushManager.getSubscription();
    enable.textContent = sub ? "Send test notification" : "Enable notifications";
    remove.hidden = !sub;
    message(sub ? "This browser has a notification subscription. Send a test to check delivery." : "Notifications are off on this device.");
  }
  if (!(window.isSecureContext && "serviceWorker" in navigator &&
        "PushManager" in window && "Notification" in window)) {
    card.hidden = false;
    enable.hidden = true;
    message("Web Push is unavailable here. On iPhone, install this HTTPS page to the Home Screen.");
    return;
  }
  card.hidden = false;
  refreshButtons().catch(function() { message("Notification status could not be read."); });
  enable.addEventListener("click", async function() {
    enable.disabled = true;
    try {
      var permission = await Notification.requestPermission();
      if (permission !== "granted") { throw new Error("Notification permission was not granted."); }
      var reg = await registration();
      var sub = await reg.pushManager.getSubscription();
      if (!sub) {
        var config = await pushRequest("/push/config", {cache: "no-store"},
          "Push configuration is unavailable.", true);
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: decode(config.applicationServerKey)
        });
      }
      var body = sub.toJSON();
      body.test_id = crypto.randomUUID();
      var receipt = await pushRequest("/push/subscriptions", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
      }, "Subscription could not be saved.", true);
      remove.hidden = false;
      enable.textContent = "Send test notification";
      await followTest(receipt);
    } catch (error) {
      message(error && error.message ? error.message : "Notification enrollment failed.");
    } finally { enable.disabled = false; }
  });
  remove.addEventListener("click", async function() {
    remove.disabled = true;
    try {
      var reg = await registration();
      var sub = await reg.pushManager.getSubscription();
      if (sub) {
        await pushRequest("/push/subscriptions/remove", {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({endpoint: sub.endpoint})
        }, "Subscription removal could not be saved.", false);
        await sub.unsubscribe();
      }
      message("Notifications disabled on this device.");
      remove.hidden = true;
      enable.textContent = "Enable notifications";
    } catch (error) {
      message(error && error.message ? error.message : "Notification removal failed.");
    } finally { remove.disabled = false; }
  });
})();
""".strip()


def _asset_name(name, body):
    stem, extension = name.split('.')
    return f'{stem}.{sha256(body.encode()).hexdigest()}.{extension}'


_DEVICE_SCRIPT = PUSH_SCRIPT + '\n' + BANNER_SCRIPT
STYLE_ASSET = _asset_name('dashboard.css', CSS)
DEVICE_ASSET = _asset_name('dashboard-device.js', _DEVICE_SCRIPT)
STATIC_ASSETS = {
    STYLE_ASSET: (CSS, 'text/css'),
    DEVICE_ASSET: (_DEVICE_SCRIPT, 'text/javascript'),
}


def _display_value(row: Row, value: str) -> str:
    if row.key == 'broker' and row.as_of is not None and ' positions' in row.value:
        observed = row.as_of.astimezone(ZoneInfo('America/Los_Angeles')).strftime('%b %d, %I:%M:%S %p Pacific')
        return f'{value} in the {observed} broker snapshot'
    return value


def _row_html(r: Row, now: datetime, *, refresh_pending: bool = False, current: bool = True,
              activation_pending: bool = False, historical_warning: bool = False,
              live: bool = False) -> str:
    st = r.effective_status(now)
    label, value, explanation = describe(r, st, now=now if current and not refresh_pending else None, live=live)
    value = _display_value(r, value)
    # Retained HTML is presentation only. Mutating an OK required-current row
    # to WARN would make the authority classifier invent a failure.
    display_status = ('neutral' if not current or refresh_pending and st not in {FAIL, UNKNOWN, PENDING}
                      else PENDING if activation_pending else st)
    if (historical_warning and current and not refresh_pending and not activation_pending
            and st in {FAIL, UNKNOWN}):
        # The exact continuity witness may classify an old failure as a current
        # review warning. Keep the original verdict and clock in the row data.
        display_status = WARN
    if activation_pending:
        value = 'Awaiting PAPER activation'
    if r.key == 'broker':
        explanation += ' See the trading run for submitted orders and fills.'
    detail = r.detail
    if refresh_pending or not current:
        value = 'LAST KNOWN · ' + value.removeprefix('LAST KNOWN · ')
        explanation = 'LAST KNOWN · not current · ' + explanation
        detail = 'LAST KNOWN · not current · ' + detail
    stale = r.is_stale(now)
    age = _ago(r.staleness(now))
    age_html = ""
    if age:
        cls = "age stale" if stale else "age"
        suffix = " · STALE" if stale else ""
        age_html = f'<div class="{cls}">{_esc(age)}{suffix}</div>'
    return (
        f'<div class="row {display_status}" id="status-{_esc(r.key)}" data-key="{_esc(r.key)}" data-status="{display_status}" data-current="{str(current and not refresh_pending).lower()}" data-original-status="{st}">'
        f'<div class="dot {display_status}">{_DOT.get(display_status, "?")}</div>'
        f'<div class="label">{_esc(label)}</div>'
        f'<div class="value">{_esc(value)}</div>'
        f'<div class="detail">{_esc(explanation)}{age_html}</div>'
        + (_holdings_html(r, now) + _paper_plan_html(r, now) if current else '') +
        f'<details class="technical" data-detail-key="{_esc(r.key)}"><summary>Technical details</summary>'
        f'<div class="detail-body">{_esc(r.label)} · {_esc(r.value)}<br>{_esc(detail)}</div></details>'
        f"</div>"
    )


def _holdings_html(row: Row, now: datetime) -> str:
    book = row.shadow_book
    status = row.effective_status(now)
    historical = (row.status == 'warn' and status == 'warn'
                  and row.required_current and row.recovery is not None
                  and row.recovery.phase == 'SOURCE_FRONTIER'
                  and row.recovery.active(now))
    if not row.can_show_shadow_book(now):
        return ''
    def number(value, money=False):
        if value is None:
            return 'Unavailable'
        return f'${value:,.2f}' if money else format(value, 'f')
    rows = [(holding.ticker, number(holding.quantity), number(holding.raw_close, True),
             number(holding.value, True), f'{holding.weight*100:.2f}%' if holding.weight is not None else 'Unavailable')
            for holding in book.holdings]
    rows.append(('Cash', '', '', number(book.cash, True), f'{book.cash/book.nav*100:.2f}%'))
    if book.receivables > 0:
        rows.append(('Dividend receivables (not cash)', '', '',
                     number(book.receivables, True), f'{book.receivables/book.nav*100:.2f}%'))
    return ('<details class="technical" data-detail-key="shadow-holdings"><summary>View shadow holdings</summary>'
            '<div class="detail-body"><p>'
            + ('LAST ATTESTED THROUGH ' + _esc(book.session) + ' · CURRENT SESSION NOT VERIFIED. '
               if historical else '')
            + 'Unscaled Wealth Core stock-selection book as of ' + _esc(book.session)
            + '. These simulated shares are separate from Alpaca holdings. Book value: '
            + number(book.nav, True) + '. The simulated strategy value includes the controller’s '
            'Core allocation, Treasury-bill sleeve and transaction costs, so the two totals can differ.</p>'
            + f'<p>{book.pending_operations} pending strategy operations; these are not filled holdings. '
            'Weights are percentages of this Wealth Core book, not the Alpaca account. '
            'Dividend receivables can include securities no longer held and are not spending cash. '
            'Unavailable prices are not treated as zero.</p><div style="overflow-x:auto">'
            + _table(('Ticker', 'Quantity', 'Close', 'Value', 'Book weight'), rows, portfolio=True) + '</div></div></details>')


def _paper_plan_html(row: Row, now: datetime) -> str:
    plan = row.paper_plan
    if not row.can_show_paper_plan(now):
        return ''
    def number(value):
        return 'Unavailable' if value is None else format(value,'f')
    legacy_rows = []
    for leg in plan.legs:
        estimate = leg.opening_estimate
        if estimate is not None:
            target = f'${estimate.account_budget:,.2f} paper budget · ${estimate.limit_price:,.2f} limit'
            change = (f'{number(estimate.shares)} estimated '+('share' if estimate.shares==1 else 'shares') if estimate.shares
                      else 'Budget below one share')
        elif leg.opening_dollars is not None:
            if leg.action == 'UNAVAILABLE':
                target = '$'+number(leg.opening_dollars)+' strategy intent'
                change = 'Estimate unavailable'
            else:
                target = '$'+number(leg.opening_dollars)+' budget'
                change = 'Sized at execution'
        else:
            target, change = number(leg.target_quantity), number(leg.change_quantity)
        legacy_rows.append((leg.ticker,leg.action,number(leg.current_quantity),target,change))
    rows = legacy_rows if plan.buy_policy is None else [(leg.ticker,leg.action,number(leg.current_quantity),
             'Pending' if leg.reason == 'CORPORATE_ACTION_PENDING' else
             '$'+number(leg.opening_dollars)+' budget' if leg.opening_dollars is not None else number(leg.target_quantity),
             '$'+number(leg.purchase_notional)+' market order' if leg.purchase_notional is not None
             else 'Budget below minimum order' if leg.action == 'SKIP'
             else 'Corporate action pending' if leg.reason == 'CORPORATE_ACTION_PENDING'
             else 'Sizing evidence unavailable' if leg.reason == 'REFERENCE_UNAVAILABLE'
             else 'Sized at execution' if leg.opening_dollars else number(leg.change_quantity)) for leg in plan.legs]
    policy_note = (' Dollar purchases assume fractional eligibility and reserve $1 per purchase. '
                   'Ineligible securities use whole-share market orders; actual shares depend on execution.'
                   if plan.buy_policy == 'FRACTIONAL_MARKET_DAY_V1' else '')
    opened = plan.execute_at.astimezone(ZoneInfo('America/Los_Angeles'))
    observed = (plan.observation_at.astimezone(ZoneInfo('America/Los_Angeles')).strftime(
        '%Y-%m-%d at %I:%M:%S %p Pacific') if plan.observation_at else 'Unavailable')
    return ('<details class="technical" data-detail-key="next-paper-plan"><summary>View planned trades</summary>'
        '<div class="detail-body"><p>Trading date: '+_esc(plan.effective_session)+
        ' · scheduled '+_esc(opened.strftime('%I:%M %p Pacific'))+'. Decision close: '+_esc(plan.decision_session)+
        '. These are saved targets, not orders or fills. Final orders depend on the selected execution policy, '
        'corporate actions, and fresh account and funding checks. Targets show shares, or a dollar budget '
        'sized when execution begins.'+_esc(policy_note)+'</p>'
        '<p>Recorded broker shares as of '+_esc(observed)+
        '. These estimates use that dated snapshot; they are not current broker holdings. No orders have been submitted by this view.</p><div style="overflow-x:auto">'+
        _table(('Ticker','Proposed action','Recorded shares','Target',
                'Proposed order' if plan.buy_policy == 'FRACTIONAL_MARKET_DAY_V1' else 'Proposed share change'),rows,portfolio=True)+
        '</div></div></details>')


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _table(headers, rows, *, portfolio=False) -> str:
    head = "".join(f"<th>{_esc(value)}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(value)}</td>" for value in row) + "</tr>"
        for row in rows)
    if not rows:
        body = f'<tr><td colspan="{len(headers)}">none</td></tr>'
    css = ' class="portfolio-table"' if portfolio else ''
    return f"<table{css}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _detail_sections(panel: Panel) -> str:
    if panel.row("shadow_verification") is not None:
        # The retained trial tables are broker-account evidence.  In reviewed
        # dual mode they are intentionally not shown beside certified shadow
        # performance, because visual proximity would imply equal authority.
        return ""
    latest = panel.trial_details or {}
    reconciliation = latest.get("reconciliation") or {}
    positions = reconciliation.get("positions") or {}
    target = reconciliation.get("target") or {}
    deltas = reconciliation.get("deltas") or {}
    marks = latest.get("marks") or {}
    position_rows = []
    for security_id in sorted(set(positions) | set(target)):
        mark = marks.get(security_id) or {}
        position_rows.append((security_id, mark.get("ticker", ""),
                              target.get(security_id, "0"),
                              positions.get(security_id, "0"),
                              deltas.get(security_id, "0"),
                              mark.get("close", "")))

    commands = latest.get("commands") or []
    command_rows = [
        (row.get("security_id", ""), row.get("side", ""),
         row.get("quantity", ""), row.get("state", ""),
         row.get("filled_quantity", ""),
         row.get("filled_average_price", ""), row.get("client_key", ""))
        for row in commands]
    fills = latest.get("fills") or []
    fill_rows = [(row.get("client_key", ""), row.get("quantity", ""),
                  row.get("price", ""), row.get("filled_at", ""),
                  row.get("broker_order_id", "")) for row in fills]

    cash = latest.get("cash") or {}
    cash_rows = [(row.get("classification", ""), row.get("amount", ""),
                  row.get("detail", ""), row.get("recorded_at", ""))
                 for row in (cash.get("rows") or [])]
    nav = latest.get("nav_attribution") or {}
    accounting = [
        ("external capital", cash.get("external", "")),
        ("internal strategy cash", cash.get("internal", "")),
        ("independent close NAV", nav.get("marked_nav", "")),
        ("unexplained residual", nav.get("unexplained", "")),
        ("financial tolerance", nav.get("tolerance", "")),
    ]

    corporate = (((latest.get("account_evidence") or {}).get("reconciliation")
                  or {}).get("corporate_actions") or {})
    corporate_rows = [(security_id, multiplier)
                      for security_id, multiplier in sorted(corporate.items())]
    paper_limitations = latest.get("paper_limitations") or {}
    for entitlement in paper_limitations.get("expected_dividends") or []:
        corporate_rows.append((
            f"{entitlement.get('security_id', '')} dividend entitlement",
            (f"{entitlement.get('shares', '')} {entitlement.get('ticker', '')}"
             f" x ${entitlement.get('per_share', '')}"
             f" = ${entitlement.get('amount', '')}; Alpaca paper unsupported;"
             " no compensation applied")))
    state_evidence = latest.get("state") or {}
    carry = state_evidence.get("terminal_carry_audit") or {}
    for security_id, evidence in sorted(carry.items()):
        corporate_rows.append((
            f"{security_id} terminal carry",
            json.dumps(evidence, sort_keys=True, separators=(",", ":"))))
    session_evidence = state_evidence.get("session_evidence") or {}
    if session_evidence:
        corporate_rows.append((
            "session terminal/accounting evidence",
            json.dumps(session_evidence, sort_keys=True,
                       separators=(",", ":"))))
    history_rows = []
    for row in panel.trial_history:
        perf = row.get("performance") or {}
        cash_view = row.get("cash") or {}
        cycle = row.get("cycle") or {}
        history_rows.append((
            row.get("session", ""), row.get("verdict", ""),
            cycle.get("state", ""), perf.get("ending_equity", ""),
            perf.get("daily_return", ""), perf.get("total_return", ""),
            cash_view.get("external", ""),
            ", ".join(row.get("reason_codes") or ())))

    sections = [
        ("Positions — target vs Alpaca", _table(
            ("Security", "Ticker", "Target", "Actual", "Delta", "Close"),
            position_rows)),
        ("Orders and commands", _table(
            ("Security", "Side", "Qty", "State", "Filled", "Avg price", "Client key"),
            command_rows) + _table(
                ("Fill key", "Qty", "Price", "Filled at", "Broker order"),
                fill_rows)),
        ("Cash and portfolio value", _table(("Fact", "Value"), accounting)
         + _table(("Class", "Amount", "Detail", "Recorded"), cash_rows)),
        ("Splits, dividends and company events", _table(
            ("Security", "Applied share multiplier"), corporate_rows)),
        ("Paper trading history", _table(
            ("Session", "Verdict", "Cycle", "Close equity", "Daily", "Total",
             "External", "Reasons"), history_rows)),
    ]
    return "".join(
        f"<details><summary>{_esc(title)}</summary>"
        f'<div class="detail-body">{content}</div></details>'
        for title, content in sections)


def deployment_progress_html(phase=None):
    return ('<p id="deployment-progress" role="status" aria-live="polite"'
            + ('>'+_esc(phase) if phase else ' hidden>') + '</p>')


def render(panel: Panel, *, refresh_seconds: int = REFRESH_SECONDS,
           refresh_pending: bool = False, compact: bool = False,
           server_time_ms: int | None = None) -> str:
    now = panel.now
    health = dashboard_health(panel)
    from sentinel.panel import delivery
    document_age = PRESENTATION_MAX_AGE_SECONDS
    worker = panel.row('shadow_worker')
    if worker is not None and worker.effective_status(now) == OK and worker.valid_until is not None:
        document_age = min(document_age, max(0, (worker.valid_until-now).total_seconds()))
    if health['valid_until'] is not None:
        health_until = datetime.fromisoformat(health['valid_until'])
        document_age = min(document_age, max(0, (health_until-now).total_seconds()))
    refresh_limit_ms = min(30, max(5, refresh_seconds)) * 1000
    operational = panel.operational
    if health['color'] in {'neutral', 'blue'}:
        headline_status = 'checking' if health['color'] == 'blue' else 'neutral'
        operational_headline = 'CHECKING CURRENT EVIDENCE — LAST VERIFIED VALUES ARE DATED'
    elif health['status'] == OK:
        headline_status = OK
        operational_headline = "SYSTEM HEALTH GREEN — NORMAL CURRENT OPERATION; PLAN READINESS IS SEPARATE"
    elif health['status'] == WARN:
        headline_status = WARN
        operational_headline = ('SYSTEM HEALTH AMBER — WAITING FOR ALPACA'
                                if current_activation_fee_wait(panel) is not None else
                                'SYSTEM HEALTH AMBER — CLOSING EVIDENCE REFRESHING'
                                if health.get('closing_refresh') else
                                'SYSTEM HEALTH AMBER — NEXT-OPEN PREPARATION IN PROGRESS'
                                if health.get('close_preparation_pending') else
                                'SYSTEM HEALTH AMBER — DEGRADED OR NEEDS REVIEW')
    else:
        headline_status = FAIL
        operational_headline = "SYSTEM HEALTH RED — FAILED OR UNREADABLE CHECK"
    errs = "".join(
        f'<div class="err">source unreadable — {_esc(e)}</div>'
        for e in panel.source_errors)
    details = _detail_sections(panel)
    shadow = panel.row("shadow_verification")
    rendered_rows = panel.rows
    historical_warning_keys = (frozenset(
        (health.get('trading_continuity') or {}).get('warning_keys') or ())
         if health['color'] in {'amber', 'green'} else frozenset())
    if shadow is not None:
        # The independent shadow verdict remains visible in its own row. The
        # current trading headline comes from the continuity projection.
        page_name = "Caesar's Palace"
        footer_authority = (
            "Strategy results come from the checked simulated portfolio. Alpaca paper holdings are shown separately.")
    else:
        trial = panel.row("trial_verification")
        trial_status = trial.effective_status(now) if trial is not None else FAIL
        trial_headline = (trial.value if trial is not None
                          else "TRIAL NOT VERIFIED — NO CERTIFICATE")
        trial_authoritative = trial_status == OK and operational == OK
        if not trial_authoritative:
            if trial_status == OK:
                trial_status = FAIL
                trial_headline = (
                    "TRIAL NOT VERIFIED — CURRENT OPERATIONAL CONDITION "
                    f"{operational.upper()}")
            rendered_rows = [
                (replace(
                    row,
                    value=(trial_headline if row.key == "trial_verification"
                           else row.value),
                    status=(FAIL if row.key == "trial_verification" else WARN),
                    detail=(
                        "UNVERIFIED · current operational authority is not fully OK; "
                        + row.detail.removeprefix("UNVERIFIED · ")))
                 if row.key in TRIAL_ROW_KEYS and row.status == OK else row)
                for row in panel.rows
            ]
        page_name = "Caesar's Palace"
        footer_authority = (
            "Paper account results are shown as checked or unverified.")
    stale_headline = "TRADING STATUS UNKNOWN — LAST KNOWN VALUES"
    display_color = health['color']
    if refresh_pending:
        if display_color == 'red':
            operational_headline = 'LAST KNOWN TRADING STOP — CHECKING FOR AN UPDATE'
        elif display_color == 'amber':
            operational_headline = 'LAST VERIFIED STATUS AMBER — CHECKING FOR AN UPDATE'
        else:
            display_color = 'blue'
            headline_status = 'checking'
            operational_headline = 'UPDATING STATUS — LAST KNOWN VALUES BELOW'
    rows = "".join(_row_html(r, now, refresh_pending=refresh_pending,
        current=delivery.row_current(panel, r), activation_pending=activation_wait_withdraws(panel, r),
        historical_warning=r.key in historical_warning_keys, live=panel.is_live_trading)
        for r in rendered_rows)
    overview = overview_html(panel, refresh_pending=refresh_pending)
    review_html = render_review(panel.operator_review,
        current=panel.observation_current and not refresh_pending)
    reasons = []
    refusal = None if refresh_pending else current_execution_refusal(panel)
    reason_rows = (sorted(rendered_rows, key=lambda row: row.key != 'automation_cycle')
                   if refusal else rendered_rows)
    for row in reason_rows:
        status = delivery.row_status(panel, row)
        primary = row.key == 'automation_cycle' and refusal is not None
        if primary or (status in {FAIL, UNKNOWN} and delivery.row_current(panel, row)
                       and not activation_wait_history(panel, row)):
            label, value, _ = describe(row, status, live=panel.is_live_trading)
            value = refusal if primary else _display_value(row, value)
            if row.key == 'trading_run' and not refresh_pending:
                counts = (order_summary(row.trading_run) if row.can_show_trading_run(now)
                          else 'Order counts unavailable.')
                if counts:
                    value += ' · ' + counts
            kind = (' class="review-warning"'
                    if row.key in historical_warning_keys or primary and status == WARN else '')
            reasons.append(f'<li{kind}><a href="#status-{_esc(row.key)}" '
                           'onclick="document.getElementById(\'system-details\').open=true">'
                           f'{_esc(label)}: {_esc(value)}</a></li>')
    history_only = health['color'] == 'green' and all(
        row.key in historical_warning_keys for row in rendered_rows
        if delivery.row_status(panel, row) in {FAIL, UNKNOWN}
        and delivery.row_current(panel, row))
    reason_label = 'Recorded history' if history_only else 'Needs attention'
    reason_html = ('<section class="status-reasons" aria-label="'+reason_label+'">'
                   '<strong>'+reason_label+'</strong><ul>'+''.join(reasons)+'</ul></section>'
                   if reasons else '')
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    generated = now.astimezone(timezone.utc).isoformat()
    compact_headline = health['label']
    opening_refresh = bool(health.get('opening_refresh')) and not refresh_pending
    closing_refresh = bool(health.get('closing_refresh')) and not refresh_pending
    heartbeat_label = ('Refreshing opening evidence · last-known cards keep their original times'
                       if opening_refresh else
                       'Refreshing closing evidence · last-known cards keep their original times'
                       if closing_refresh else 'DASHBOARD HEARTBEAT · UPDATED 0s AGO')
    if refresh_pending:
        compact_headline = {
            'red': 'Last known trading stop · checking for an update',
            'amber': 'Last verified status amber · checking for an update',
        }.get(display_color, 'Refreshing status · last known values')
    body = f"""<body data-generated-at="{_esc(generated)}"
             data-server-time="{'' if server_time_ms is None else server_time_ms}"
             data-health="{_esc(display_color)}"
             data-refresh-pending="{'true' if refresh_pending else 'false'}"
             data-opening-refresh="{str(opening_refresh).lower()}"
             data-closing-refresh="{str(closing_refresh).lower()}"
             data-observation-current="{str(delivery.display_current(panel) and not refresh_pending).lower()}"
             data-strict-observation-current="{str(panel.observation_current and not refresh_pending).lower()}"
             data-controller-version="{CONTROLLER_VERSION}"
             data-max-age-seconds="{document_age}">
<div class="wrap">
<header>
  <div class="brand"><img data-banner-src="/static/caesars-status-green.gif" class="unknown-sign" src="/static/caesars-status-green-still.gif" width="1086" height="362" alt="{_esc(page_name)}"><span class="brand-fallback" hidden>{_esc(page_name)}</span></div>
  <span id="operational-state" class="state {headline_status}" title="{_esc(operational_headline)}">{_esc(compact_headline)}</span>
  {reason_html}
  <span id="dashboard-heartbeat" class="heartbeat" role="status"
        aria-live="polite">{'Refreshing status · last known observation ' + _esc(stamp) if refresh_pending else _esc(heartbeat_label)}</span>
  {deployment_progress_html()}
</header>
{errs}
<div id="portfolio-overview">{overview}</div>
<details id="system-details" data-detail-key="system-details"><summary>System details</summary><div class="detail-body system-detail-body">
<section id="push-card" class="push-card" hidden aria-label="Notifications">
  <div class="label">Notifications</div>
  <div id="push-status" aria-live="polite">Checking this device…</div>
  <div class="push-actions">
    <button id="push-enable" type="button">Enable notifications</button>
    <button id="push-remove" class="secondary" type="button" hidden>Disable notifications</button>
  </div>
</section>
{rows}{details}
{review_html}
</div></details>
</div>
"""
    if compact:
        return (f'<!doctype html><html lang="en"><head><title>{_esc(page_name)}</title>'
                f'<link id="dashboard-stylesheet" rel="stylesheet" href="/static/{STYLE_ASSET}">'
                f'</head>{body}</body></html>')
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="{_esc(page_name)}">
<meta name="theme-color" content="#16111f">
<meta http-equiv="Cache-Control" content="no-store, max-age=0">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" sizes="180x180" href="/static/caesars-palace-180.png">
<title>{_esc(page_name)}</title>
<style id="dashboard-stylesheet" data-source-href="/static/{STYLE_ASSET}">{CSS}</style>
</head>{body}
<script>
// Negative authority only. This code can remove green before a network read;
// only the server can earn it again by returning a new complete document.
(function(){{
  // Receiving new HTML does not execute its controller. This identifies the
  // live controller independently of the version offered by the latest body.
  window.sentinelDashboardControllerVersion = "{CONTROLLER_VERSION}";
  var invalidated = false;
  {CURRENT_DOCUMENT_SCRIPT}
  {DOM_REFRESH_SCRIPT}
  var badge = document.getElementById("operational-state");
  var heartbeat = document.getElementById("dashboard-heartbeat");
  var preparation = document.getElementById("preparation-stage");
  var planReadiness = document.getElementById("plan-readiness");
  var generated = Date.parse(document.body.dataset.generatedAt);
  var budget = Number(document.body.dataset.maxAgeSeconds) * 1000;
  var sourceClock = window.sentinelDashboardClock;
  window.sentinelDashboardClock = null;
  if (!sourceClock || sourceClock.generation !== generated || sourceClock.budget !== budget){{
    var navigationAge = performance.now();
    var renderedAge = document.body.dataset.serverTime ?
      Number(document.body.dataset.serverTime) - generated : 0;
    sourceClock = {{age:renderedAge >= 0 ? renderedAge + navigationAge : NaN, tick:navigationAge}};
  }}
  var verifiedWarning = null;
  rememberWarning();
  var maximumBudget = {PRESENTATION_MAX_AGE_SECONDS * 1000};
  var maximumRefreshMs = {refresh_limit_ms};
  var earlyStarted = -Infinity;
  var earlyBoundary = NaN;
  var followedBoundary = false;
  var scheduledBoundary = null;
  var refreshDelayMs = refreshCadence(budget);
  var hasBeenVisible = document.visibilityState === "visible";
  var pageAway = !hasBeenVisible;
  var wentToBackground = false;
  var wentOffline = !navigator.onLine;
  var requests = dashboardRequests();
  var refreshDeferred = false;
  var refreshDelayed = document.body.dataset.refreshPending === "true";
  var readFailure = null;
  // Server health and browser freshness are separate. A server-side incident
  // never turns a sleeping phone into twenty new model-slot failures.
  var hardFailure = false;
  var ordinaryStarted = null;
  var ordinaryEligible = false;
  var ordinaryTimer = null;
  var ordinaryDue = nextRefreshDue();
  var resumeStarted = null;
  var resumeExhausted = false;
  var resumeTimer = null;
  var ageTimer;
  var refreshTimer;
  function setDeploymentProgress(text){{
    var phase = document.getElementById('deployment-progress');
    if (phase) {{ phase.textContent = text; phase.hidden = !text; }}
  }}
  function validBudget(value){{
    return Number.isFinite(value) && value > 0 && value <= maximumBudget;
  }}
  function refreshCadence(value){{
    var regular = validBudget(value) && value < maximumBudget ?
      Math.min(maximumRefreshMs, Math.max(5000, Math.floor(value / 2000) * 1000)) : maximumRefreshMs;
    scheduledBoundary = null;
    var boundary = generated + value;
    var remaining = value - evidenceAge();
    var currentRegion = document.body.dataset.observationCurrent === "false" &&
      document.querySelector('.row[data-current="true"]') !== null;
    if (!validBudget(value) || !(remaining > 0 && remaining <= regular) ||
        (document.body.dataset.observationCurrent !== "true" && !currentRegion) ||
        document.body.dataset.refreshPending !== "false"){{ return regular; }}
    if (Math.abs(boundary - earlyBoundary) <= 1){{
      if (followedBoundary){{ return regular; }}
      scheduledBoundary = "expiry";
      return Math.ceil(remaining);
    }}
    if (performance.now() - earlyStarted < 5000){{ return regular; }}
    scheduledBoundary = "early";
    return Math.max(1, Math.floor(remaining / 2));
  }}
  function nextRefreshDue(){{
    return performance.now() + refreshDelayMs;
  }}
  function evidenceAge(){{
    var elapsed = performance.now() - sourceClock.tick;
    return Number.isFinite(generated) && elapsed >= 0 ? sourceClock.age + elapsed : NaN;
  }}
  function armHeartbeat(){{
    clearTimeout(ageTimer);
    var elapsed = evidenceAge();
    var delay = Number.isFinite(elapsed) ? Math.max(1, 1000 - elapsed % 1000) : 1000;
    var remaining = budget - elapsed;
    if (validBudget(budget) && remaining > 0){{ delay = Math.min(delay, Math.ceil(remaining)); }}
    ageTimer = setTimeout(function heartbeatTick(){{ checkAge(); armHeartbeat(); }}, delay);
  }}
  function armRefresh(){{
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(function(){{ checkAge(); refreshDocument(); }}, refreshDelayMs);
  }}
  async function refreshDocument(){{
    if (!navigator.onLine){{ return; }}
    if (document.visibilityState !== "visible" || pageAway){{
      refreshDeferred = true;
      return;
    }}
    if (ordinaryStarted === null && resumeStarted === null && !hardFailure && performance.now() < ordinaryDue){{ return; }}
    var active = requests.begin();
    if (!active){{ return; }}
    refreshDeferred = false;
    if (ordinaryStarted === null){{
      ordinaryStarted = performance.now();
      // A scheduled boundary check owns transport only. It cannot extend proof.
      var boundaryDue = scheduledBoundary === "expiry" && ordinaryStarted >= ordinaryDue &&
        ordinaryStarted - ordinaryDue < 1000;
      ordinaryEligible = (originalCurrent() || boundaryDue) && !invalidated && !hardFailure;
      if (scheduledBoundary === "early"){{
        earlyStarted = performance.now(); earlyBoundary = generated + budget; followedBoundary = false;
      }} else if (scheduledBoundary === "expiry"){{ followedBoundary = true; }}
      scheduledBoundary = null;
      ordinaryTimer = setTimeout(function(){{
        if (resumeStarted === null && !originalCurrent()){{ invalidate(false); }}
      }}, 15000);
    }}
    var started = performance.now();
    var response;
    var responseStatus;
    var receivingBody = false;
    try {{
      var html = await dashboardDeadline(active, async function(){{
        response = await fetch(location.href, {{cache:"no-store", headers:{{
          "X-Sentinel-Refresh":"1",
          "X-Sentinel-Panel-Fragment":window.sentinelDashboardControllerVersion
        }}, signal:active.signal}});
        responseStatus = response.headers.get("X-Sentinel-Panel-Status");
        if (!sameDashboardOrigin(response) || !response.ok || !["CURRENT", "PARTIAL"].includes(responseStatus)){{
          throw new Error("Current dashboard is not ready");
        }}
        receivingBody = true;
        return response.text();
      }});
      receivingBody = false;
      if (!requests.owns(active) || document.visibilityState !== "visible" || pageAway){{ return; }}
      var next = currentDocument(html, responseStatus, response, started);
      clearTimeout(refreshTimer);
      clearTimeout(resumeTimer);
      clearTimeout(ordinaryTimer);
      if (next.body.dataset.controllerVersion !== window.sentinelDashboardControllerVersion){{
        if (!/^(?:[0-9a-f]{{64}}|[1-9][0-9]{{0,3}})$/.test(next.body.dataset.controllerVersion || "")){{
          throw new Error("Invalid dashboard controller handoff");
        }}
        clearTimeout(ageTimer);
        window.sentinelDashboardClock = next.sentinelClock;
        document.open(); document.write(html); document.close();
        return;
      }}
      reconcileDocument(next);
      readFailure = null;
      delete document.body.dataset.link;
      badge = document.getElementById('operational-state');
      heartbeat = document.getElementById('dashboard-heartbeat');
      preparation = document.getElementById('preparation-stage');
      planReadiness = document.getElementById('plan-readiness');
      generated = Date.parse(document.body.dataset.generatedAt);
      budget = Number(document.body.dataset.maxAgeSeconds) * 1000;
      sourceClock = next.sentinelClock;
      rememberWarning();
      if (verifiedWarning && document.body.dataset.health === "blue"){{
        showLastVerifiedStatus("checking for an update", "");
      }}
      refreshDelayMs = refreshCadence(budget);
      invalidated = false; hardFailure = false; refreshDelayed = false;
      ordinaryStarted = null; ordinaryEligible = false; ordinaryDue = nextRefreshDue();
      resumeStarted = null; resumeExhausted = false; wentToBackground = false;
      document.documentElement.classList.remove('not-current', 'checking-status', 'expired-status');
      armRefresh();
      checkAge();
      armHeartbeat();
    }} catch (_error) {{
      if (!requests.owns(active)){{ return; }}
      if (document.visibilityState !== "visible" || pageAway){{ refreshDeferred = true; return; }}
      readFailure = dashboardReadFailure(response, receivingBody);
      document.body.dataset.link = readFailure.kind;
      var transportDelay = readFailure.retryable;
      setDeploymentProgress(readFailure.progress || "");
      if (transportDelay && !invalidated && continuityCurrent()){{
        showResume();
      }} else if (transportDelay && !invalidated && originalCurrent()){{
        pendingRefresh();
      }} else {{
        invalidate(false, !transportDelay);
        heartbeat.textContent = readFailure.label + " · showing last known values";
      }}
      requests.retryAfter(refreshDocument, 5000);
    }} finally {{
      requests.finish(active);
    }}
  }}
  function originalCurrent(){{
    var age = evidenceAge();
    return document.body.dataset.refreshPending !== "true" &&
      Number.isFinite(age) && validBudget(budget) && age < budget && !clockReversed();
  }}
  function clockReversed(){{
    var now = performance.now();
    return (ordinaryStarted !== null && now < ordinaryStarted) ||
      (resumeStarted !== null && now < resumeStarted);
  }}
  function pendingRefresh(){{
    withdrawPreparation();
    refreshDelayed = true;
    heartbeat.textContent = (readFailure ? readFailure.label : "Refreshing status") + " · last known observation " +
      new Date(generated).toISOString();
  }}
  function resumeCurrent(){{
    var elapsed = performance.now() - resumeStarted;
    var current = resumeStarted !== null && elapsed >= 0 && elapsed < 15000;
    if (resumeStarted !== null && !current){{ resumeExhausted = true; }}
    return !resumeExhausted && current;
  }}
  function continuityCurrent(){{
    var elapsed = performance.now() - ordinaryStarted;
    return !hardFailure && navigator.onLine &&
      requests.pending() &&
      (resumeStarted !== null ? resumeCurrent() :
        ordinaryEligible && ordinaryStarted !== null && elapsed >= 0 && elapsed < 15000);
  }}
  function showResume(){{
    if (invalidated || hardFailure){{ return; }}
    if (originalCurrent()){{ pendingRefresh(); return; }}
    withdrawPreparation();
    refreshDelayed = true;
    document.documentElement.classList.add("checking-status");
    showLastVerifiedStatus("checking for an update", "REFRESHING STATUS — LAST KNOWN VALUES");
    heartbeat.textContent = (readFailure ? readFailure.label : "Refreshing status") + " · last known observation " +
      new Date(generated).toISOString();
  }}
  function resumeDocument(){{
    var age = evidenceAge();
    if (hardFailure || !navigator.onLine ||
        !Number.isFinite(age) || !validBudget(budget) || clockReversed()){{
      invalidate(true, true);
      return;
    }}
    if (resumeStarted === null){{
      var anchor = !wentToBackground && ordinaryEligible ? ordinaryStarted : performance.now();
      var elapsed = performance.now() - anchor;
      if (elapsed < 0 || elapsed >= 15000){{ invalidate(true); return; }}
      resumeStarted = anchor;
      resumeTimer = setTimeout(function(){{ resumeExhausted = true; invalidate(false); }}, 15000-elapsed);
    }}
    if (!resumeCurrent()){{ invalidate(true); return; }}
    if (invalidated){{
      invalidated = false;
      document.documentElement.classList.remove("not-current", "expired-status");
    }}
    showResume();
    refreshDocument();
  }}
  function invalidate(andReload, hard){{
    hardFailure = hardFailure || hard === true || clockReversed();
    var offline = !navigator.onLine;
    if (!invalidated || document.documentElement.classList.contains("not-current") !== offline){{
      withdrawPreparation();
      invalidated = true;
      document.documentElement.classList.remove("not-current", "checking-status", "expired-status");
      if (offline){{ document.documentElement.classList.add("not-current"); }}
      else {{ document.documentElement.classList.add("checking-status", "expired-status"); }}
      showLastVerifiedStatus(offline ? "offline" : "update unavailable", "{_esc(stale_headline)}");
      heartbeat.textContent = "DASHBOARD UPDATE UNAVAILABLE · LAST KNOWN OBSERVATION " +
        (Number.isFinite(generated) ? new Date(generated).toISOString() : "unknown");
    }}
    if (andReload){{ refreshDocument(); }}
  }}
  function showLastVerifiedStatus(message, unknown){{
    var color = verifiedWarning && verifiedWarning.color;
    var lastKnown = {{red:"LAST KNOWN TRADING STOP", amber:"LAST VERIFIED STATUS AMBER"}}[color];
    badge.className = lastKnown ? (color === "red" ? "state fail" : "state warn")
      : navigator.onLine ? "state checking" : "state neutral";
    badge.textContent = lastKnown ? lastKnown + " · " + verifiedWarning.stamp + " · " + message : unknown;
    badge.title = badge.textContent;
  }}
  function rememberWarning(){{
    var color = document.body.dataset.health;
    if (color === "green"){{ verifiedWarning = null; }}
    if ((color === "red" || color === "amber") && Number.isFinite(generated)){{
      verifiedWarning = {{color:color, stamp:new Date(generated).toISOString()}};
    }}
    if (color === "blue" && verifiedWarning){{
      document.body.dataset.lastWarning = verifiedWarning.color;
    }} else {{
      delete document.body.dataset.lastWarning;
    }}
  }}
  function withdrawPreparation(){{
    if (preparation){{ preparation.textContent = "Last known preparation stage · refresh required"; }}
    if (planReadiness){{ planReadiness.textContent = "Plan readiness not current · refreshing status"; }}
  }}
  function checkAge(){{
    updateMarketCountdown();
    var age = evidenceAge();
    if (!Number.isFinite(age) || !validBudget(budget) || clockReversed()){{
      invalidate(true, true);
    }} else if (document.visibilityState !== "visible" || pageAway){{
      return;
    }} else if (wentToBackground){{
      if (document.visibilityState === "visible"){{ resumeDocument(); }}
    }} else if (resumeStarted !== null){{
      if (!resumeCurrent()){{ invalidate(true); }}
      else if (age >= budget){{ showResume(); }}
    }} else if (age >= budget){{
      if (scheduledBoundary === "expiry"){{ refreshDocument(); }}
      if (!invalidated && continuityCurrent()){{ showResume(); }}
      else {{ invalidate(true); }}
    }} else if (!invalidated && !refreshDelayed){{
      var text = document.body.dataset.openingRefresh === "true"
        ? "Refreshing opening evidence · last-known cards keep their original times"
        : document.body.dataset.closingRefresh === "true"
        ? "Refreshing closing evidence · last-known cards keep their original times"
        : "DASHBOARD HEARTBEAT · UPDATED " + Math.floor(age / 1000) + "s AGO";
      if (heartbeat.textContent !== text){{ heartbeat.textContent = text; }}
    }}
  }}
  function updateMarketCountdown(){{
    var counter = document.getElementById('market-open-countdown');
    if (!counter){{ return; }}
    var card = counter.closest('.overview-card');
    var current = originalCurrent() && !invalidated && !refreshDelayed &&
      card && card.dataset.current === 'true';
    var end = Date.parse(counter.dataset.marketOpenAt);
    var value = current ? 'Market-open time unavailable' : 'Market-open time not current';
    if (current && Number.isFinite(end)){{
      var remaining = end - (generated + evidenceAge());
      var total = Math.max(0, Math.ceil(remaining/60000));
      var days = Math.floor(total/1440), hours = Math.floor(total%1440/60), minutes = total%60;
      var parts = [];
      [[days,'day'],[hours,'hour'],[minutes,'minute']].forEach(function(part){{
        if (part[0] || part[1] === 'minute'){{ parts.push(part[0]+' '+part[1]+(part[0] === 1 ? '' : 's')); }}
      }});
      value = remaining > 0 ? 'Market open in '+parts.join(' ') : 'Scheduled market open reached';
    }}
    if (counter.textContent !== value){{ counter.textContent = value; }}
  }}
  window.addEventListener("pageshow", function(event){{
    if (document.visibilityState !== "visible"){{ return; }}
    pageAway = false;
    if (event.persisted){{ wentToBackground = true; }}
    if (event.persisted || wentToBackground || !originalCurrent()){{ resumeDocument(); }}
    else {{ checkAge(); }}
    hasBeenVisible = true;
  }});
  function suspendDocument(){{
    wentToBackground = true;
    pageAway = true;
    requests.cancel();
    setDeploymentProgress("");
    if (Number.isFinite(generated)){{ showResume(); }}
  }}
  window.addEventListener("pagehide", suspendDocument);
  window.addEventListener("focus", function(){{
    if (document.visibilityState === "visible"){{
      pageAway = false;
      if (wentToBackground || resumeStarted !== null ||
          (!originalCurrent() && ordinaryEligible && ordinaryStarted !== null)){{ resumeDocument(); }}
      else if (!originalCurrent()){{ checkAge(); }}
      else if (refreshDeferred){{ refreshDocument(); }}
      hasBeenVisible = true;
    }}
  }});
  document.addEventListener("visibilitychange", function(){{
    pageAway = document.visibilityState !== "visible";
    if (document.visibilityState === "hidden" && hasBeenVisible){{
      suspendDocument();
    }} else if (document.visibilityState === "visible"){{
      if (wentToBackground || !originalCurrent()){{ resumeDocument(); }}
      else if (refreshDeferred){{ refreshDocument(); }}
      hasBeenVisible = true;
    }}
  }});
  window.addEventListener("online", function(){{
    if (wentOffline){{ invalidate(true); }}
  }});
  window.addEventListener("offline", function(){{
    wentOffline = true;
    requests.cancel();
    setDeploymentProgress("");
    invalidate(false, true);
  }});
  if (wentOffline){{ invalidate(false, true); }}
  armHeartbeat();
  armRefresh();
  if (document.body.dataset.refreshPending === "true"){{
    resumeDocument();
  }} else {{ checkAge(); }}
}})();
</script>
{REVIEW_SCRIPT}
<script defer src="/static/{DEVICE_ASSET}"></script>
</body></html>"""


__all__ = [
    "CSS", "PRESENTATION_MAX_AGE_SECONDS", "PUSH_SCRIPT", "REFRESH_SECONDS",
    "render",
]
