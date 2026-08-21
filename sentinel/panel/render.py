"""The panel's HTML. PURE: takes a `Panel`, returns a string.

ONE PAGE, NO TABS, NO SCRIPTS THAT DO ANYTHING. The Stocker dashboard had eight
tabs and a trade-approval button; this replaces all of it. Read-only means there
is no control on this page that could ever submit, approve or liquidate — not
disabled, ABSENT. A button that is merely disabled is one CSS bug away from
being a button.

MOBILE FIRST, and specifically for a phone held in one hand at 22:47 wondering
whether the seed is still alive. The layout is a single column at every width;
there is no breakpoint at which content moves, because the failure mode of a
responsive dashboard is that the thing you needed was in the column that
collapsed.

JavaScript has negative authority only: it invalidates an old DOM before a full
reload. It never computes or promotes a financial verdict.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

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
  padding:max(16px,env(safe-area-inset-top)) 16px
          max(24px,env(safe-area-inset-bottom));
}
.wrap{max-width:560px;margin:0 auto}
header{display:block;margin:4px 2px 14px}
h1{font-size:17px;font-weight:650;letter-spacing:.02em;margin:0}
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
.not-current .row.ok{border-color:var(--fail)}
"""


def _row_html(r: Row, now: datetime) -> str:
    st = r.effective_status(now)
    stale = r.is_stale(now)
    age = _ago(r.staleness(now))
    age_html = ""
    if age:
        cls = "age stale" if stale else "age"
        suffix = " · STALE" if stale else ""
        age_html = f'<div class="{cls}">{_esc(age)}{suffix}</div>'
    return (
        f'<div class="row {st}" data-key="{_esc(r.key)}" data-status="{st}">'
        f'<div class="dot {st}">{_DOT.get(st, "?")}</div>'
        f'<div class="label">{_esc(r.label)}</div>'
        f'<div class="value">{_esc(r.value)}</div>'
        f'<div class="detail">{_esc(r.detail)}{age_html}</div>'
        f"</div>"
    )


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _table(headers, rows) -> str:
    head = "".join(f"<th>{_esc(value)}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(value)}</td>" for value in row) + "</tr>"
        for row in rows)
    if not rows:
        body = f'<tr><td colspan="{len(headers)}">none</td></tr>'
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _detail_sections(panel: Panel) -> str:
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
        ("Cash and NAV attribution", _table(("Fact", "Value"), accounting)
         + _table(("Class", "Amount", "Detail", "Recorded"), cash_rows)),
        ("Corporate actions and terminals", _table(
            ("Security", "Applied share multiplier"), corporate_rows)),
        ("Trial session history", _table(
            ("Session", "Verdict", "Cycle", "Close equity", "Daily", "Total",
             "External", "Reasons"), history_rows)),
    ]
    return "".join(
        f"<details><summary>{_esc(title)}</summary>"
        f'<div class="detail-body">{content}</div></details>'
        for title, content in sections)


def render(panel: Panel, *, refresh_seconds: int = REFRESH_SECONDS) -> str:
    now = panel.now
    overall = panel.overall
    operational = panel.operational
    errs = "".join(
        f'<div class="err">source unreadable — {_esc(e)}</div>'
        for e in panel.source_errors)
    details = _detail_sections(panel)
    trial = panel.row("trial_verification")
    trial_status = trial.effective_status(now) if trial is not None else FAIL
    trial_headline = (trial.value if trial is not None
                      else "TRIAL NOT VERIFIED — NO CERTIFICATE")
    trial_authoritative = trial_status == OK and operational == OK
    rendered_rows = panel.rows
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
    rows = "".join(_row_html(r, now) for r in rendered_rows)
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    generated = now.astimezone(timezone.utc).isoformat()
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Sentinel Trial">
<meta http-equiv="Cache-Control" content="no-store, max-age=0">
<title>Sentinel Trial</title>
<style>{CSS}</style>
</head><body data-generated-at="{_esc(generated)}"
             data-max-age-seconds="{PRESENTATION_MAX_AGE_SECONDS}">
<div class="wrap">
<header>
  <h1>SENTINEL TRIAL</h1>
  <span id="trial-state" class="state {trial_status}">{_esc(trial_headline)}</span>
</header>
{errs}{rows}{details}
<footer>
  as of {_esc(stamp)} · refreshes every {refresh_seconds}s<br>
  read-only · paper account · performance is explicitly verified or unverified<br>
  operational condition: {_esc(operational)} · all-row condition: {_esc(overall)}
</footer>
</div>
<script>
// Negative authority only. This code can remove green before a network read;
// only the server can earn it again by returning a new complete document.
(function(){{
  var invalidated = false;
  var badge = document.getElementById("trial-state");
  var generated = Date.parse(document.body.dataset.generatedAt);
  var budget = Number(document.body.dataset.maxAgeSeconds) * 1000;
  function invalidate(andReload){{
    if (!invalidated){{
      invalidated = true;
      document.documentElement.classList.add("not-current");
      badge.className = "state fail";
      badge.textContent = "TRIAL NOT VERIFIED — NOT CURRENT";
    }}
    if (andReload && navigator.onLine){{ location.reload(); }}
  }}
  function checkAge(){{
    var age = Date.now() - generated;
    if (!Number.isFinite(age) || age > budget || age < -5000){{
      invalidate(true);
    }}
  }}
  window.addEventListener("pageshow", function(event){{
    if (event.persisted){{ invalidate(true); }} else {{ checkAge(); }}
  }});
  document.addEventListener("visibilitychange", function(){{
    if (document.visibilityState === "visible"){{ invalidate(true); }}
  }});
  window.addEventListener("online", function(){{ invalidate(true); }});
  window.addEventListener("offline", function(){{ invalidate(false); }});
  setInterval(checkAge, 1000);
  setTimeout(function(){{ invalidate(true); }}, {refresh_seconds * 1000});
}})();
</script>
</body></html>"""


__all__ = ["CSS", "PRESENTATION_MAX_AGE_SECONDS", "REFRESH_SECONDS", "render"]
