"""The panel's HTML. PURE: takes a `Panel`, returns a string.

ONE PAGE, NO TABS, NO FINANCIAL ACTIONS. The Stocker dashboard had eight tabs
and a trade-approval button; this replaces all of it. Read-only means there is
no control on this page that could ever submit, approve or liquidate — not
disabled, ABSENT. The only buttons manage this browser's notification delivery
capability and are isolated behind the narrow subscription router.

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
from zoneinfo import ZoneInfo

from sentinel.panel.presentation import describe, CASINO_CSS
from sentinel.panel.overview import OVERVIEW_CSS, overview_html

from sentinel.panel.model import (
    FAIL, OK, PENDING, TRIAL_ROW_KEYS, UNKNOWN, WARN, Panel, Row)

#: Refresh cadence. Long enough not to hammer the database from a phone left on
#: a desk, short enough that a stalled ingest is visible within a coffee.
REFRESH_SECONDS = 30
PRESENTATION_MAX_AGE_SECONDS = 45

_DOT = {OK: "●", WARN: "▲", FAIL: "■", PENDING: "○", UNKNOWN: "?"}


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


CSS = """
:root{
  --bg:#f6f7f9; --card:#ffffff; --ink:#11161d; --muted:#5d6773; --line:#e3e7ec;
  --ok:#1a7f4b; --warn:#9a6400; --fail:#b3261e; --pending:#6b7480;
  --okbg:#e8f5ee; --warnbg:#fdf3e0; --failbg:#fdeceb; --pendingbg:#eef1f4;
  --shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.10);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0e1116; --card:#161a21; --ink:#e8edf3; --muted:#98a2b0; --line:#252b34;
    --ok:#5ed39a; --warn:#e8b45f; --fail:#ff7b72; --pending:#7d8794;
    --okbg:#12261c; --warnbg:#2a2113; --failbg:#2c1615; --pendingbg:#1b2028;
    --shadow:0 1px 2px rgba(0,0,0,.4);
  }
}
:root[data-theme="dark"]{
  --bg:#0e1116; --card:#161a21; --ink:#e8edf3; --muted:#98a2b0; --line:#252b34;
  --ok:#5ed39a; --warn:#e8b45f; --fail:#ff7b72; --pending:#7d8794;
  --okbg:#12261c; --warnbg:#2a2113; --failbg:#2c1615; --pendingbg:#1b2028;
  --shadow:0 1px 2px rgba(0,0,0,.4);
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.45 ui-sans-serif,-apple-system,BlinkMacSystemFont,"SF Pro Text",
       "Segoe UI",Roboto,sans-serif;
  -webkit-text-size-adjust:100%;
  padding:max(16px,env(safe-area-inset-top))
          max(16px,env(safe-area-inset-right))
          max(24px,env(safe-area-inset-bottom))
          max(16px,env(safe-area-inset-left));
}
.wrap{max-width:560px;margin:0 auto}
header{display:block;margin:4px 2px 14px}
h1{font-size:17px;font-weight:650;letter-spacing:.02em;margin:0}
.brand{display:flex;align-items:center;gap:10px}
.brand img{width:42px;height:42px;border-radius:10px;flex:0 0 auto}
.state{
  display:inline-block;margin-top:8px;font-size:12px;font-weight:650;letter-spacing:.06em;
  padding:4px 10px;border-radius:999px;text-transform:uppercase;
  overflow-wrap:anywhere;
}
.state.ok{background:var(--okbg);color:var(--ok)}
.state.warn{background:var(--warnbg);color:var(--warn)}
.state.fail{background:var(--failbg);color:var(--fail)}
.state.pending{background:var(--pendingbg);color:var(--pending)}
.state.unknown{background:var(--failbg);color:var(--fail)}
.heartbeat{
  display:block;margin-top:7px;color:var(--muted);font-size:12px;
  font-variant-numeric:tabular-nums;letter-spacing:.03em;
}
.heartbeat::before{content:"●";color:var(--ok);margin-right:7px}
.not-current .heartbeat{color:var(--fail);font-weight:650}
.not-current .heartbeat::before{color:var(--fail)}
.err{
  background:var(--failbg);color:var(--fail);border-radius:12px;
  padding:12px 14px;margin-bottom:12px;font-size:13px;
}
.row{
  background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:13px 15px;margin-bottom:10px;box-shadow:var(--shadow);
  display:grid;grid-template-columns:18px 1fr;gap:2px 11px;
}
.dot{grid-row:1/span 3;font-size:13px;line-height:1.5;text-align:center}
.dot.ok{color:var(--ok)} .dot.warn{color:var(--warn)}
.dot.fail{color:var(--fail)} .dot.pending{color:var(--pending)}
.dot.unknown{color:var(--fail)}
.label{
  font-size:11px;font-weight:600;letter-spacing:.10em;text-transform:uppercase;
  color:var(--muted);
}
.value{
  font-size:17px;font-weight:600;line-height:1.3;
  font-variant-numeric:tabular-nums;overflow-wrap:anywhere;
}
.row.fail .value{color:var(--fail)}
.detail{font-size:13px;color:var(--muted);overflow-wrap:anywhere}
.age{font-size:11px;color:var(--muted);margin-top:3px}
.age.stale{color:var(--warn);font-weight:600}
footer{
  margin-top:16px;text-align:center;font-size:11px;color:var(--muted);
  line-height:1.7;
}
footer code{font-size:11px}
details{
  background:var(--card);border:1px solid var(--line);border-radius:14px;
  margin:10px 0;box-shadow:var(--shadow);overflow:hidden;
}
summary{cursor:pointer;padding:13px 15px;font-weight:650;list-style-position:inside}
.detail-body{padding:0 15px 14px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}
th,td{padding:7px 6px;text-align:left;border-top:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;letter-spacing:.04em}
.portfolio-table{min-width:650px;table-layout:auto;overflow-wrap:normal}
.portfolio-table th,.portfolio-table td{white-space:nowrap;word-break:normal}
.not-current .row.ok{border-color:var(--fail)}
.not-current .dot.ok{color:var(--fail)}
.refreshing-status .row.ok{border-color:var(--warn)}
.refreshing-status .dot.ok,.refreshing-status .heartbeat{color:var(--warn)}
.refreshing-status .heartbeat::before{color:var(--warn)}
.refreshing-status .row.ok .value::before{content:"LAST KNOWN · ";color:var(--warn)}
.push-card{
  background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:13px 15px;margin:10px 0;box-shadow:var(--shadow);
}
.push-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
button{
  appearance:none;border:1px solid var(--line);border-radius:10px;
  background:var(--ink);color:var(--card);font:inherit;font-weight:650;
  min-height:44px;padding:9px 13px;cursor:pointer;
}
button.secondary{background:transparent;color:var(--ink)}
button[hidden]{display:none}
#push-status{font-size:13px;color:var(--muted);overflow-wrap:anywhere}
@media (max-width:360px){
  body{font-size:14px}.row{padding:12px}.value{font-size:16px}
}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""


PUSH_SCRIPT = r"""
(function(){
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
        var response = await fetch("/push/tests/" + encodeURIComponent(receipt.alert_id), {
          credentials: "same-origin", cache: "no-store"
        });
        if (!response.ok) { throw new Error("status unavailable"); }
        receipt = await response.json();
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
        var config = await fetch("/push/config", {cache: "no-store"}).then(function(response) {
          if (!response.ok) { throw new Error("Push configuration is unavailable."); }
          return response.json();
        });
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: decode(config.applicationServerKey)
        });
      }
      var body = sub.toJSON();
      body.test_id = crypto.randomUUID();
      var response = await fetch("/push/subscriptions", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
      });
      if (!response.ok) { throw new Error("Subscription could not be saved."); }
      var receipt = await response.json();
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
        var response = await fetch("/push/subscriptions/remove", {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({endpoint: sub.endpoint})
        });
        if (!response.ok) { throw new Error("Subscription removal could not be saved."); }
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


def _row_html(r: Row, now: datetime, *, refresh_pending: bool = False) -> str:
    st = r.effective_status(now)
    label, value, explanation = describe(r, st)
    # Retained HTML is presentation only. Mutating an OK required-current row
    # to WARN would make the authority classifier invent a failure.
    display_status = WARN if refresh_pending and st == OK else st
    detail = r.detail
    if refresh_pending:
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
        f'<div class="row {display_status}" id="status-{_esc(r.key)}" data-key="{_esc(r.key)}" data-status="{display_status}">'
        f'<div class="dot {display_status}">{_DOT.get(display_status, "?")}</div>'
        f'<div class="label">{_esc(label)}</div>'
        f'<div class="value">{_esc(value)}</div>'
        f'<div class="detail">{_esc(explanation)}{age_html}</div>'
        + _holdings_html(r, now) + _paper_plan_html(r, now) +
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
    if plan is None or row.effective_status(now) != 'ok':
        return ''
    def number(value):
        return 'Unavailable' if value is None else format(value,'f')
    rows = [(leg.ticker,leg.action,number(leg.current_quantity),
             '$'+number(leg.opening_dollars)+' budget' if leg.opening_dollars else number(leg.target_quantity),
             'Sized at execution' if leg.opening_dollars else number(leg.change_quantity)) for leg in plan.legs]
    opened = plan.execute_at.astimezone(ZoneInfo('America/Los_Angeles'))
    observed = (plan.observation_at.astimezone(ZoneInfo('America/Los_Angeles')).strftime(
        '%Y-%m-%d at %I:%M:%S %p Pacific') if plan.observation_at else 'Unavailable')
    return ('<details class="technical" data-detail-key="next-paper-plan"><summary>View planned trades</summary>'
        '<div class="detail-body"><p>Trading date: '+_esc(plan.effective_session)+
        ' · scheduled '+_esc(opened.strftime('%I:%M %p Pacific'))+'. Decision close: '+_esc(plan.decision_session)+
        '. These are saved targets, not orders or fills. Final orders depend on the selected execution policy, '
        'corporate actions, and fresh account and funding checks. Targets show shares, or a dollar budget '
        'sized when execution begins.</p>'
        '<p>Recorded broker shares as of '+_esc(observed)+
        '. These estimates use that dated snapshot; they are not current broker holdings. No orders have been submitted by this view.</p><div style="overflow-x:auto">'+
        _table(('Ticker','Proposed action','Recorded shares','Target','Proposed share change'),rows,portfolio=True)+
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


def render(panel: Panel, *, refresh_seconds: int = REFRESH_SECONDS,
           refresh_pending: bool = False) -> str:
    now = panel.now
    document_age = PRESENTATION_MAX_AGE_SECONDS
    worker = panel.row('shadow_worker')
    if worker is not None and worker.effective_status(now) == OK and worker.valid_until is not None:
        document_age = min(document_age, max(0, (worker.valid_until-now).total_seconds()))
        refresh_seconds = min(refresh_seconds, max(1, int(document_age)-15))
    overall = panel.overall
    operational = panel.operational
    if operational == OK:
        headline_status = OK
        operational_headline = "OPERATIONAL GREEN — HEALTHY AND CURRENT"
    elif operational in {WARN, PENDING}:
        headline_status = WARN
        operational_headline = "OPERATIONAL AMBER — NO ACTION REQUIRED YET"
    else:
        headline_status = FAIL
        operational_headline = "OPERATIONAL RED — OPERATOR ACTION REQUIRED"
    errs = "".join(
        f'<div class="err">source unreadable — {_esc(e)}</div>'
        for e in panel.source_errors)
    details = _detail_sections(panel)
    shadow = panel.row("shadow_verification")
    rendered_rows = panel.rows
    if shadow is not None:
        # A PAPER mismatch makes the overall operation red, but it must never
        # relabel an independently current shadow result.  The green shadow row
        # remains visible directly below the red operational badge.
        shadow_status = shadow.effective_status(now)
        if overall in {FAIL, UNKNOWN}:
            trial_status = FAIL
            trial_headline = "OPERATIONAL RED — REVIEW REQUIRED"
        elif overall == WARN:
            trial_status = WARN
            trial_headline = "OPERATIONAL AMBER — PAPER EVIDENCE PENDING"
        elif shadow_status == OK:
            trial_status = OK
            trial_headline = "SHADOW VERIFIED · PAPER MONITORED"
        else:
            trial_status = FAIL
            trial_headline = shadow.value
        page_name = "Caesar's Palace"
        page_heading = "CAESAR'S PALACE"
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
        page_heading = "CAESAR'S PALACE"
        footer_authority = (
            "Paper account results are shown as checked or unverified.")
    stale_headline = "OPERATIONAL RED — STATUS NOT CURRENT"
    if refresh_pending:
        headline_status = FAIL if operational in {FAIL, UNKNOWN} else WARN
        operational_headline = 'UPDATING STATUS — LAST KNOWN VALUES BELOW'
    rows = "".join(_row_html(r, now, refresh_pending=refresh_pending) for r in rendered_rows)
    overview = overview_html(panel, refresh_pending=refresh_pending)
    reasons = []
    for row in rendered_rows:
        status = row.effective_status(now)
        if status in {FAIL, UNKNOWN}:
            label, value, _ = describe(row, status)
            reasons.append(f'<li><a href="#status-{_esc(row.key)}" '
                           'onclick="document.getElementById(\'system-details\').open=true">'
                           f'{_esc(label)}: {_esc(value)}</a></li>')
    reason_html = ('<section class="status-reasons" aria-label="Checks needing attention">'
                   '<strong>Needs attention</strong><ul>'+''.join(reasons)+'</ul></section>'
                   if reasons else '')
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    generated = now.astimezone(timezone.utc).isoformat()
    compact_headline = ({OK: 'System ready', WARN: 'System waiting', FAIL: 'Needs attention'}
                        .get(headline_status, 'Status unavailable'))
    if refresh_pending:
        compact_headline = 'Refreshing status · last known values'
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="{_esc(page_name)}">
<meta name="theme-color" content="#b3261e">
<meta http-equiv="Cache-Control" content="no-store, max-age=0">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" sizes="180x180" href="/static/caesars-palace-180.png">
<title>{_esc(page_name)}</title>
<style>{CSS}{CASINO_CSS}{OVERVIEW_CSS}</style>
</head><body data-generated-at="{_esc(generated)}"
             data-refresh-pending="{'true' if refresh_pending else 'false'}"
             data-max-age-seconds="{document_age}">
<div class="wrap">
<header>
  <div class="brand"><img src="/static/caesars-palace-192.png" alt="">
    <h1>{_esc(page_heading)}</h1></div>
  <p class="brand-subtitle">Sentinel · PAPER</p>
  <span id="operational-state" class="state {headline_status}" title="{_esc(operational_headline)}">{_esc(compact_headline)}</span>
  {reason_html}
  <span id="dashboard-heartbeat" class="heartbeat" role="status"
        aria-live="polite">{'Refreshing status · last known observation ' + _esc(stamp) if refresh_pending else 'DASHBOARD HEARTBEAT · UPDATED 0s AGO'}</span>
</header>
{errs}
<div id="portfolio-overview">{overview}</div>
<details id="system-details" data-detail-key="system-details"><summary>System details</summary><div class="detail-body system-detail-body">
<details class="mode-guide" data-detail-key="mode-guide"><summary>What am I looking at?</summary><div class="detail-body">
  <p><strong>Your strategy, at a glance.</strong> Wealth Core records the unscaled stock-selection book. The controller’s simulated strategy value combines its Core allocation, Treasury-bill sleeve and transaction costs. The Alpaca paper account has its own recorded holdings and value.</p>
  <p>Alpaca supplies daily prices, corporate actions and listed-asset information. OpenFIGI classifies eligible equity instruments. Formation simulates earlier sessions to build the model book; daily updates carry it forward. A simulated portfolio check does not mean paper orders have been placed.</p>
  {'<p>Owner-authorized local PAPER operation is active. PR release certification is suspended. Backup creation, restore drills and backup verification are disabled by owner instruction.</p>' if panel.local_paper_mode else ''}
  <p>Green means the check passed. Amber means waiting or review needed. Red means a failed or unreadable check. Open technical details for the precise reason.</p>
</div></details>
<section id="push-card" class="push-card" hidden aria-label="Notifications">
  <div class="label">Notifications</div>
  <div id="push-status" aria-live="polite">Checking this device…</div>
  <div class="push-actions">
    <button id="push-enable" type="button">Enable notifications</button>
    <button id="push-remove" class="secondary" type="button" hidden>Disable notifications</button>
  </div>
</section>
{rows}{details}
</div></details>
<footer>
  as of {_esc(stamp)} · refreshes every {refresh_seconds}s<br>
  This page shows status; it cannot place trades.<br>
  {_esc(footer_authority)}<br>
  <details class="technical" data-detail-key="technical-status"><summary>Technical status</summary>Current operational checks: {_esc(operational)} · all displayed checks, including notifications and unverified results: {_esc(overall)}. The attention list above identifies each failing check; this aggregate alone does not diagnose a stopped worker.</details>
</footer>
</div>
<script>
// Negative authority only. This code can remove green before a network read;
// only the server can earn it again by returning a new complete document.
(function(){{
  var invalidated = false;
  var badge = document.getElementById("operational-state");
  var heartbeat = document.getElementById("dashboard-heartbeat");
  var generated = Date.parse(document.body.dataset.generatedAt);
  var budget = Number(document.body.dataset.maxAgeSeconds) * 1000;
  var maximumBudget = {PRESENTATION_MAX_AGE_SECONDS * 1000};
  var hasBeenVisible = document.visibilityState === "visible";
  var wentToBackground = false;
  var wentOffline = !navigator.onLine;
  var refreshing = false;
  var refreshDelayed = document.body.dataset.refreshPending === "true";
  var knownFailure = badge.className === "state fail" || badge.className === "state unknown";
  var retryTimer = null;
  var resumeStarted = null;
  var resumeTimer = null;
  var ageTimer;
  var refreshTimer;
  function validBudget(value){{
    return Number.isFinite(value) && value > 0 && value <= maximumBudget;
  }}
  async function refreshDocument(){{
    if (refreshing || retryTimer !== null || !navigator.onLine){{ return; }}
    refreshing = true;
    var controller = new AbortController();
    var deadline = setTimeout(function(){{ controller.abort(); }}, 15000);
    var transportDelay = true;
    try {{
      var response = await fetch(location.href, {{cache:"no-store", signal:controller.signal}});
      transportDelay = response.status === 503 || response.headers.get("X-Sentinel-Panel-Status") === "LAST_KNOWN";
      if (!response.ok || response.headers.get("X-Sentinel-Panel-Status") !== "CURRENT"){{
        throw new Error("Current dashboard is not ready");
      }}
      var html = await response.text();
      var next = new DOMParser().parseFromString(html, "text/html");
      var nextAge = Date.now() - Date.parse(next.body.dataset.generatedAt);
      var nextBudget = Number(next.body.dataset.maxAgeSeconds) * 1000;
      if (!next.getElementById("operational-state") ||
          next.body.dataset.refreshPending !== "false" ||
          !Number.isFinite(nextAge) || !validBudget(nextBudget) || nextAge < -5000 ||
          nextAge > nextBudget){{
        throw new Error("Dashboard response is incomplete");
      }}
      clearInterval(ageTimer);
      clearTimeout(refreshTimer);
      clearTimeout(resumeTimer);
      clearTimeout(deadline);
      var scroll = window.scrollY;
      var expanded = Array.from(document.querySelectorAll('details[data-detail-key][open]'))
        .map(function(item){{ return item.dataset.detailKey; }});
      var focused = document.activeElement && document.activeElement.closest
        ? document.activeElement.closest('details[data-detail-key]') : null;
      var focusKey = focused ? focused.dataset.detailKey : null;
      document.open();
      document.write(html);
      document.close();
      document.querySelectorAll('details[data-detail-key]').forEach(function(item){{
        item.open = expanded.includes(item.dataset.detailKey);
        if (focusKey && item.dataset.detailKey === focusKey){{
          item.querySelector('summary').focus({{preventScroll:true}});
        }}
      }});
      window.scrollTo(0, scroll);
    }} catch (_error) {{
      if (transportDelay && !invalidated && resumeCurrent()){{
        showResume();
      }} else if (transportDelay && !invalidated && originalCurrent()){{
        pendingRefresh();
      }} else {{
        invalidate(false);
        heartbeat.textContent = "Refreshing status · showing last known values";
      }}
      retryTimer = setTimeout(function(){{ retryTimer = null; refreshDocument(); }}, 5000);
    }} finally {{
      clearTimeout(deadline);
      refreshing = false;
    }}
  }}
  function originalCurrent(){{
    var age = Date.now() - generated;
    return Number.isFinite(age) && validBudget(budget) && age >= -5000 && age <= budget;
  }}
  function pendingRefresh(){{
    refreshDelayed = true;
    if (!knownFailure){{
      badge.className = "state warn";
      badge.textContent = "STATUS REFRESHING — ORIGINAL CHECK TIMES RETAINED";
    }}
    heartbeat.textContent = "Refreshing status · last known observation " +
      new Date(generated).toISOString();
  }}
  function resumeCurrent(){{
    var elapsed = Date.now() - resumeStarted;
    return resumeStarted !== null && elapsed >= 0 && elapsed < 15000;
  }}
  function showResume(){{
    if (invalidated || knownFailure){{ return; }}
    refreshDelayed = true;
    document.documentElement.classList.add("refreshing-status");
    badge.className = "state warn";
    badge.textContent = "REFRESHING STATUS — LAST KNOWN VALUES";
    heartbeat.textContent = "Refreshing status · checking connection · last known observation " +
      new Date(generated).toISOString();
  }}
  function resumeDocument(){{
    var age = Date.now() - generated;
    if (invalidated || knownFailure || !navigator.onLine ||
        !Number.isFinite(age) || !validBudget(budget) || age < -5000){{
      invalidate(true);
      return;
    }}
    if (resumeStarted === null){{
      resumeStarted = Date.now();
      resumeTimer = setTimeout(function(){{ invalidate(false); }}, 15000);
    }}
    if (!resumeCurrent()){{ invalidate(true); return; }}
    showResume();
    refreshDocument();
  }}
  function invalidate(andReload){{
    if (!invalidated){{
      invalidated = true;
      document.documentElement.classList.remove("refreshing-status");
      document.documentElement.classList.add("not-current");
      badge.className = "state fail";
      badge.textContent = "{_esc(stale_headline)}";
      heartbeat.textContent = "DASHBOARD HEARTBEAT LOST · STATUS STALE";
    }}
    if (andReload){{ refreshDocument(); }}
  }}
  function checkAge(){{
    var age = Date.now() - generated;
    if (!Number.isFinite(age) || !validBudget(budget) || age < -5000){{
      invalidate(true);
    }} else if (wentToBackground){{
      if (document.visibilityState === "visible"){{ resumeDocument(); }}
    }} else if (resumeStarted !== null){{
      if (!resumeCurrent()){{ invalidate(true); }}
    }} else if (age > budget){{
      invalidate(true);
    }} else if (!invalidated && !refreshDelayed){{
      heartbeat.textContent = "DASHBOARD HEARTBEAT · UPDATED " +
        Math.max(0, Math.floor(age / 1000)) + "s AGO";
    }}
  }}
  window.addEventListener("pageshow", function(event){{
    if (event.persisted){{ resumeDocument(); }} else {{ checkAge(); }}
  }});
  document.addEventListener("visibilitychange", function(){{
    if (document.visibilityState === "hidden" && hasBeenVisible){{
      wentToBackground = true;
      if (Number.isFinite(generated)){{ showResume(); }}
    }} else if (document.visibilityState === "visible"){{
      if (wentToBackground){{ resumeDocument(); }}
      hasBeenVisible = true;
    }}
  }});
  window.addEventListener("online", function(){{
    if (wentOffline){{ invalidate(true); }}
  }});
  window.addEventListener("offline", function(){{
    wentOffline = true;
    invalidate(false);
  }});
  if (wentOffline){{ invalidate(false); }}
  ageTimer = setInterval(checkAge, 1000);
  refreshTimer = setTimeout(function(){{ checkAge(); refreshDocument(); }}, {refresh_seconds * 1000});
  if (document.body.dataset.refreshPending === "true"){{
    resumeDocument();
  }} else {{ checkAge(); }}
}})();
</script>
<script>{PUSH_SCRIPT}</script>
</body></html>"""


__all__ = [
    "CSS", "PRESENTATION_MAX_AGE_SECONDS", "PUSH_SCRIPT", "REFRESH_SECONDS",
    "render",
]
