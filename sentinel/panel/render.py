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

The only JavaScript is a meta-refresh replacement: a timer that reloads the
page. It is deliberately not a fetch-and-patch, because a partial update that
fails silently leaves stale numbers on screen looking fresh — the exact class of
failure this panel exists to catch.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sentinel.panel.model import FAIL, OK, PENDING, UNKNOWN, WARN, Panel, Row

#: Refresh cadence. Long enough not to hammer the database from a phone left on
#: a desk, short enough that a stalled ingest is visible within a coffee.
REFRESH_SECONDS = 30

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
header{display:flex;align-items:baseline;gap:10px;margin:4px 2px 14px}
h1{font-size:17px;font-weight:650;letter-spacing:.02em;margin:0}
.state{
  margin-left:auto;font-size:12px;font-weight:650;letter-spacing:.06em;
  padding:4px 10px;border-radius:999px;text-transform:uppercase;
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


def render(panel: Panel, *, refresh_seconds: int = REFRESH_SECONDS) -> str:
    now = panel.now
    overall = panel.overall
    errs = "".join(
        f'<div class="err">source unreadable — {_esc(e)}</div>'
        for e in panel.source_errors)
    rows = "".join(_row_html(r, now) for r in panel.rows)
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>Sentinel</title>
<style>{CSS}</style>
</head><body>
<div class="wrap">
<header>
  <h1>SENTINEL</h1>
  <span class="state {overall}">{_esc(overall)}</span>
</header>
{errs}{rows}
<footer>
  as of {_esc(stamp)} · refreshes every {refresh_seconds}s<br>
  read-only · paper account · no performance figures shown here
</footer>
</div>
<script>
// A full reload, deliberately: a fetch-and-patch that fails silently leaves
// stale values on screen looking fresh, which is the failure this panel exists
// to catch. A reload either works or visibly does not.
setTimeout(function(){{ location.reload(); }}, {refresh_seconds * 1000});
</script>
</body></html>"""


__all__ = ["CSS", "REFRESH_SECONDS", "render"]
