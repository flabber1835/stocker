#!/usr/bin/env bash
# wc-progress.sh — readable live status for a Wealth Core rehearsal.
#
#   scripts/wc-progress.sh            one snapshot
#   scripts/wc-progress.sh -w         refresh every 30s until the run ends
#   scripts/wc-progress.sh -w 10      ...every 10s
#
# Reads bt-engine's /wealth-core/progress and /wealth-core/runs/latest.
# BT_ENGINE_URL overrides the default host:port.
#
# WHY A SCRIPT RATHER THAN `curl | json.tool`: the raw payload nests the whole
# performance block one level down and prints ~30 keys, most of which are None
# for the first hour. The three that decide whether a run is worth reading —
# the settlement counters — live in the FINAL summary, not in progress, so a
# reader watching only the pretty CAGR is watching the wrong number. This
# prints the provisional caveat every time and surfaces the counters the
# moment they exist.
set -uo pipefail

URL="${BT_ENGINE_URL:-http://localhost:8031}"
WATCH=0; EVERY=30
if [ "${1:-}" = "-w" ] || [ "${1:-}" = "--watch" ]; then
    WATCH=1; [ -n "${2:-}" ] && EVERY="$2"
fi

render() {
    curl -s --max-time 10 "$URL/wealth-core/progress" -o /tmp/.wc_prog.json
    local rc=$?
    if [ $rc -ne 0 ]; then
        printf '\n  bt-engine unreachable at %s (curl rc=%s)\n\n' "$URL" "$rc"
        return 1
    fi
    curl -s --max-time 10 "$URL/wealth-core/runs/latest" -o /tmp/.wc_run.json
    python3 - "$URL" <<'PY'
import json, sys, datetime

C = {"b": "\033[1m", "d": "\033[2m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "x": "\033[0m"}

def load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}

prog, run = load("/tmp/.wc_prog.json"), load("/tmp/.wc_run.json")

def pct(v, nd=2):
    return "—" if v is None else f"{v * 100:.{nd}f}%"

def money(v):
    return "—" if v is None else f"${v:,.0f}"

def bar(p, w=44):
    if p is None:
        return "?" * w
    n = int(round(w * p / 100.0))
    return "█" * n + "·" * (w - n)

print()
print(f"{C['b']}  WEALTH CORE REHEARSAL{C['x']}   {C['d']}{sys.argv[1]}{C['x']}")
print(f"  {C['d']}{'─' * 62}{C['x']}")

status = (run or {}).get("status")
mode = (run or {}).get("mode")
if status:
    col = {"success": C["g"], "failed": C["r"], "running": C["c"]}.get(status, "")
    print(f"  status    {col}{C['b']}{str(status).upper()}{C['x']}"
          f"   {C['d']}mode={mode}{C['x']}")
    if (run or {}).get("error_message"):
        print(f"  {C['r']}error     {run['error_message']}{C['x']}")

# PHASES. A rehearsal is five steps and only ONE of them reports progress, so
# a bare percentage reaching 100% while the job keeps running reads as a stall.
# The bar is scoped to the phase it actually measures and the rest are listed.
done_sessions = prog.get("sessions_done") or 0
total_sessions = prog.get("sessions_total") or 0
chain_done = prog.get("running") and total_sessions and done_sessions >= total_sessions
terminal = status in ("success", "failed")

if terminal:
    phase = 5
elif chain_done:
    phase = 3          # bulk replay / parity / measurement, none of which report
elif prog.get("running"):
    phase = 2
else:
    phase = 1

PHASES = [
    (1, "corpus load + warm-up", "no progress reported"),
    (2, "chain pass", "session by session — the bar below"),
    (3, "bulk replay", "re-runs EVERY session again, reports nothing"),
    (4, "parity check", "raises on divergence"),
    (5, "measurement", "performance, after parity"),
]
if terminal:
    print(f"  {C['b']}PHASE 5/5{C['x']}  "
          f"{(C['g'] if status == 'success' else C['r'])}{C['b']}"
          f"all phases {'complete' if status == 'success' else 'ended — see error'}"
          f"{C['x']}")
else:
    print(f"  {C['b']}PHASE {phase}/5{C['x']}  "
          f"{C['c']}{C['b']}{PHASES[phase - 1][1]}{C['x']}")
for n, name, note in PHASES:
    if terminal:
        mark, col = "✓", C["d"]
    elif n < phase:
        mark, col = "✓", C["g"]
    elif n == phase:
        mark, col = "▶", C["c"]
    else:
        mark, col = " ", C["d"]
    print(f"    {col}{mark} {n}. {name:<22}{C['d']}{note}{C['x']}")

if not terminal:
    print(f"  {C['d']}{'─' * 62}{C['x']}")
if terminal:
    pass          # the phase list above already says everything
elif not prog.get("running"):
    print(f"  chain     {C['d']}{prog.get('detail', 'no snapshot yet')}{C['x']}")
    if status == "running":
        print(f"            {C['d']}phase 1 reports nothing — a silent stretch"
              f" here is normal{C['x']}")
else:
    pc = prog.get("pct")
    col = C["g"] if chain_done else C["c"]
    print(f"  chain     {col}{bar(pc)}{C['x']}  "
          f"{C['b']}{'—' if pc is None else f'{pc:.1f}%'}{C['x']}"
          f"   {C['d']}of the CHAIN PASS only{C['x']}")
    print(f"            {done_sessions} / {total_sessions}"
          f" sessions   {C['d']}at {prog.get('current_session')}{C['x']}")
    if chain_done and not terminal:
        print()
        print(f"  {C['y']}{C['b']}The chain pass is done; the run is NOT.{C['x']}")
        print(f"  {C['y']}Phase 3 replays all {total_sessions} sessions a second"
              f" time to prove the{C['x']}")
        print(f"  {C['y']}live path reproduces it, and emits no progress at all."
              f" Expect a{C['x']}")
        print(f"  {C['y']}silent stretch of roughly the time phase 2 just took."
              f"{C['x']}")

perf = (prog.get("performance") or {}) if prog.get("running") else \
       ((run or {}).get("summary") or {}).get("performance") or {}

if perf:
    final = not prog.get("running")
    print(f"  {C['d']}{'─' * 62}{C['x']}")
    tag = f"{C['g']}FINAL{C['x']}" if final else f"{C['y']}PROVISIONAL{C['x']}"
    print(f"  {C['b']}PERFORMANCE{C['x']}  {tag}")
    if not perf.get("evaluable"):
        print(f"    {C['y']}unevaluable — {perf.get('unevaluable_reason')}{C['x']}")
    rows = [
        ("equity", f"{money(perf.get('starting_equity'))} → "
                   f"{C['b']}{money(perf.get('ending_equity'))}{C['x']}"),
        ("total return", pct(perf.get("total_return"))),
        ("CAGR", (pct(perf.get("cagr")) +
                  (f"  {C['r']}{C['b']}EXTRAPOLATED{C['x']}"
                   f"{C['r']} from {perf.get('calendar_days')} days — "
                   f"not a result{C['x']}"
                   if perf.get("cagr_extrapolated") else ""))
                 if perf.get("cagr") is not None
                 else f"{C['d']}{perf.get('cagr_unavailable_reason') or '—'}{C['x']}"),
        ("max drawdown", pct(perf.get("maximum_drawdown")) +
                         (f"  {C['y']}(lower bound){C['x']}"
                          if perf.get("maximum_drawdown_is_lower_bound") else "")),
        ("trades", str(perf["trade_count"]) if perf.get("trade_count")
                   else (f"{C['d']}not counted while running — the progress"
                         f" snapshot carries no fills{C['x']}"
                         if not final else "0")),
    ]
    bt = perf.get("benchmark_ticker")
    if perf.get("benchmark_total_return") is not None:
        ex = perf.get("excess_total_return")
        col = C["g"] if (ex or 0) >= 0 else C["r"]
        rows.append((f"vs {bt}", f"{pct(perf.get('benchmark_total_return'))}"
                                 f"   {col}{'+' if (ex or 0) >= 0 else ''}"
                                 f"{pct(ex)}{C['x']}"))
    elif perf.get("benchmark_unavailable_reason"):
        rows.append((f"vs {bt or 'SPY'}",
                     f"{C['d']}{perf['benchmark_unavailable_reason']}{C['x']}"))
    for k, v in rows:
        print(f"    {k:<14}{v}")
    if perf.get("blocked_session_count"):
        print(f"    {C['y']}{perf['blocked_session_count']} blocked session(s) "
              f"excluded{C['x']}")
    if not final:
        print(f"    {C['d']}measured BEFORE the parity check — a run that later"
              f"\n    diverges shows healthy numbers and then publishes none{C['x']}")

summary = (run or {}).get("summary") or {}
counters = {k: v for k, v in summary.items()
            if k in ("exact_terminal_settlements", "market_exit_terminal_settlements",
                     "derived_last_mark_settlements", "orphan_zero_writeoffs",
                     "unresolved_terminal_events", "pending_terms_carried")}
if counters:
    print(f"  {C['d']}{'─' * 62}{C['x']}")
    print(f"  {C['b']}SETTLEMENT{C['x']}  {C['d']}read these BEFORE any"
          f" performance number{C['x']}")
    for k in ("exact_terminal_settlements", "market_exit_terminal_settlements",
              "derived_last_mark_settlements", "pending_terms_carried",
              "orphan_zero_writeoffs", "unresolved_terminal_events"):
        if k in counters:
            print(f"    {k:<34}{counters[k]}")
    derived = counters.get("derived_last_mark_settlements")
    unres = counters.get("unresolved_terminal_events")
    if derived == 0 and (unres or 0) > 0:
        print(f"    {C['r']}{C['b']}STOP{C['x']} {C['r']}derived=0 with "
              f"unresolved={unres}: the book is BLOCKING,\n         not settling. "
              f"The performance above is measuring the\n         wrong thing.{C['x']}")
    if (counters.get("orphan_zero_writeoffs") or 0) > 0 and derived == 0:
        print(f"    {C['r']}documented events may be reaching the C2 zero{C['x']}")

for k in ("trace_problems", "entries_without_a_price", "peak_book_size"):
    if k in summary:
        v = summary[k]
        bad = (k == "trace_problems" and v) or \
              (k == "entries_without_a_price" and v) or \
              (k == "peak_book_size" and v not in (None, 25))
        col = C["r"] if bad else C["g"]
        print(f"    {k:<34}{col}{v if not isinstance(v, list) else len(v)}{C['x']}")

prov = summary.get("provenance") or {}
if prov:
    ss, ws = prov.get("split_source"), prov.get("warmup_sessions")
    print(f"  {C['d']}{'─' * 62}{C['x']}")
    print(f"    split_source                      "
          f"{C['g'] if ss == 'actions' else C['r']}{ss}{C['x']}")
    print(f"    warmup_sessions                   "
          f"{C['g'] if ws == 126 else C['r']}{ws}{C['x']}")
print()
PY
}

if [ "$WATCH" = "1" ]; then
    while true; do
        clear; render
        st=$(curl -s --max-time 10 "$URL/wealth-core/runs/latest" \
             | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
        case "$st" in success|failed) echo "  run is terminal — stopping watch"; break;; esac
        sleep "$EVERY"
    done
else
    render
fi
