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

from sentinel.panel.presentation import describe, dashboard_health
from sentinel.panel.overview import overview_html
from sentinel.panel.styles import CSS

from sentinel.panel.model import (
    FAIL, OK, PENDING, TRIAL_ROW_KEYS,
    UNKNOWN, WARN, Panel, Row)

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
    if not row.can_show_paper_plan(now):
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


def _local_paper_guide(panel: Panel) -> str:
    if not panel.local_paper_mode:
        return ''
    backup = panel.row('backup_restore')
    if backup is not None and backup.value == 'DISABLED BY OWNER':
        detail = ('Backup creation, restore drills and backup verification are disabled '
                  'by owner instruction.')
    else:
        detail = ('Backup and restore readiness has its own current evidence check below. '
                  'Owner PAPER mode alone does not prove a usable backup or restore.')
    return ('<p>Owner-authorized local PAPER operation is active. '
            + detail + '</p>')


def render(panel: Panel, *, refresh_seconds: int = REFRESH_SECONDS,
           refresh_pending: bool = False) -> str:
    now = panel.now
    health = dashboard_health(panel)
    document_age = PRESENTATION_MAX_AGE_SECONDS
    worker = panel.row('shadow_worker')
    if worker is not None and worker.effective_status(now) == OK and worker.valid_until is not None:
        document_age = min(document_age, max(0, (worker.valid_until-now).total_seconds()))
    if health['valid_until'] is not None:
        health_until = datetime.fromisoformat(health['valid_until'])
        document_age = min(document_age, max(0, (health_until-now).total_seconds()))
    if document_age < PRESENTATION_MAX_AGE_SECONDS:
        refresh_seconds = min(refresh_seconds, max(5, int(document_age/2)))
    overall = panel.overall
    operational = panel.operational
    if health['status'] == OK:
        headline_status = OK
        operational_headline = "SYSTEM HEALTH GREEN — NORMAL CURRENT OPERATION; PLAN READINESS IS SEPARATE"
    elif health['status'] == WARN:
        headline_status = WARN
        operational_headline = "SYSTEM HEALTH AMBER — DEGRADED OR NEEDS REVIEW"
    else:
        headline_status = FAIL
        operational_headline = "SYSTEM HEALTH RED — FAILED OR UNREADABLE CHECK"
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
    stale_headline = "OPERATIONAL RED — STATUS NOT CURRENT"
    if refresh_pending:
        headline_status = FAIL if health['status'] == FAIL else WARN
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
    compact_headline = health['label']
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
<style>{CSS}</style>
</head><body data-generated-at="{_esc(generated)}"
             data-refresh-pending="{'true' if refresh_pending else 'false'}"
             data-max-age-seconds="{document_age}">
<div class="wrap">
<header>
  <div class="brand"><img src="/static/caesars-palace-512.png" alt="{_esc(page_name)}"></div>
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
  {_local_paper_guide(panel)}
  <p>The main health colour is green for healthy normal work or scheduled waiting, amber for degraded operation or review, and red for a failed or unreadable check. Plan readiness is shown separately. Detailed check colours retain their own evidence verdicts; green health does not certify portfolio values or grant trading permission.</p>
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
  <details class="technical" data-detail-key="technical-status"><summary>Technical status</summary>Dashboard system health: {_esc(health['status'])} · strict operational readiness: {_esc(operational)} · all recorded check verdicts: {_esc(overall)}. Health, plan readiness and detailed checks are separate facts; each keeps its original evidence time. The attention list above identifies each failing check; an aggregate alone does not diagnose a stopped worker.</details>
</footer>
</div>
<script>
// Negative authority only. This code can remove green before a network read;
// only the server can earn it again by returning a new complete document.
(function(){{
  var invalidated = false;
  var badge = document.getElementById("operational-state");
  var heartbeat = document.getElementById("dashboard-heartbeat");
  var preparation = document.getElementById("preparation-stage");
  var planReadiness = document.getElementById("plan-readiness");
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
    withdrawPreparation();
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
    withdrawPreparation();
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
      withdrawPreparation();
      invalidated = true;
      document.documentElement.classList.remove("refreshing-status");
      document.documentElement.classList.add("not-current");
      badge.className = "state fail";
      badge.textContent = "{_esc(stale_headline)}";
      heartbeat.textContent = "DASHBOARD HEARTBEAT LOST · STATUS STALE";
    }}
    if (andReload){{ refreshDocument(); }}
  }}
  function withdrawPreparation(){{
    if (preparation){{ preparation.textContent = "Last known preparation stage · refresh required"; }}
    if (planReadiness){{ planReadiness.textContent = "Plan readiness not current · refreshing status"; }}
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
