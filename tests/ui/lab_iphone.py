#!/usr/bin/env python3
"""Playwright layout check for the Lab tab on an iPhone X.

The dashboard is used from a phone, and the Lab tab is the densest screen in it
(a running experiment's live stats, the weekly-cap strip, a schedule list and a
6-column leaderboard table). Wide tables are exactly what breaks a 375px
viewport: the usual failure is the PAGE scrolling sideways, which drags the
sticky bars and bottom nav off-screen and makes every other tab feel broken too.

This serves the REAL html/css/js from the repo (no running stack) with
/api/bt/status stubbed, drives the Lab tab at 375x812 DPR3, and asserts the
layout properties that actually matter on a phone:

  * the page body never scrolls horizontally (wide content scrolls in its own box)
  * nothing overflows the viewport width
  * the bottom nav and sticky filter bar stay visible and on-screen
  * text stays legible (no sub-10px font)
  * tap targets meet a usable minimum
  * the leaderboard is reachable by scrolling ITS container, not the page

Run standalone:  python tests/ui/lab_iphone.py [--headed] [--shots DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phone_audit import IPHONE_X, TabSpec, run   # noqa: E402

# A deliberately DEMANDING payload: long hypothesis text, a full leaderboard,
# long config diffs — the shapes most likely to blow out a narrow viewport.
# /api/bt/status answers {"status": <status.json>, "sweep": <latest_sweep.json>}
# — the Lab reads coverage/experiments from d.status, NOT from the top level.
# Getting this wrong renders the "no artifacts yet" fallback, which passes
# every layout check while showing none of the real screen; the
# variant-content assertion in audit_lab is what catches that.
def _ago(minutes: int) -> str:
    """Timestamps must be relative to the BROWSER's clock or every rendered age
    is nonsense (a hardcoded one produced '-746m ago' and hid a real bug)."""
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


BT_STATUS_INNER = {
    "generated_at": _ago(4),
    "scheduler": {"last_tick": _ago(3), "last_topup": _ago(600),
                  "last_sweep_fire": None, "last_export": _ago(900),
                  "notes": ["experiment fired (full_config) sweep 9f2c1a44 "
                            "tune 2023-07-25→2025-07-25 validate 2025-07-25→2026-07-25",
                            "no promotion for 2f1c9a03: tune CAGR edge -0.0042 "
                            "< margin +0.0100"]},
    "sweep_latest": {"status": "success", "n_done": 27, "n_configs": 27,
                     "tune_start": "2023-07-25", "tune_end": "2025-07-25",
                     "validate_start": "2025-07-25", "validate_end": "2026-07-25",
                     "error_message": None},
    "coverage": {"go": True, "prices": {"rows": 35009761, "tickers": 17781,
                                        "date_min": "2004-01-02", "date_max": "2026-07-24"},
                 "fundamentals": {"rows": 488689}, "earliest_viable_start": "2005-01-03"},
    "coverage_as_of": _ago(5),
    "experiments": {
        "running": None,
        "queued": [
            {"kind": "full_config",
             "hypothesis": "concentrating to 17 names raises expected compounded return "
                           "because cap_blocked candidates have outperformed selected "
                           "ones for three consecutive weeks"},
            {"kind": "full_config", "hypothesis": "tighter knife limit cuts the drawdown tail"},
        ],
        "schedule": [
            {"when": "2026-07-25T22:00", "kind": "full_config",
             "thesis": "concentrating to 17 names raises expected compounded return",
             "note": None},
            {"when": "2026-07-26T22:00", "kind": "full_config",
             "thesis": "tighter knife limit cuts the drawdown tail",
             "note": "after weekly cap resets"},
        ],
        "recent": [
            {"kind": "baseline", "status": "success", "hypothesis": "BASELINE: active config",
             "cagr": 0.1421, "promotion": None, "completed_at": _ago(1200)},
            {"kind": "full_config", "status": "success",
             "hypothesis": "momentum 0.42 -> 0.55 with earnings_surprise at 0.12",
             "cagr": 0.1180,
             "promotion": "edge does NOT survive validation: out-of-sample CAGR -0.0300 "
                          "vs baseline (tol 0.0000)",
             "completed_at": _ago(2600)},
        ],
        "next_fire_local": "2026-07-25T22:00-04:00",
        "fired_this_week": 0,
        "baselines_this_week": 3,
        "week_cap": 5,
        "window_years": 3,
        "validate_months": 12,
        "last_promotion": None,
        "promotion_applied": None,
    },
}

SWEEP = {
    "sweep_id": "9f2c1a44-0000-4000-8000-000000000000",
    "status": "success", "generated_at": _ago(1500),
    "n_configs": 27,
    "leaderboard": [
        {"config_idx": i,
         "config_diff": {"static_factor_weights.momentum": 0.30 + i * 0.01,
                         "portfolio_builder.max_positions": 20 + i},
         "oos_sharpe": 1.05 - i * 0.03, "is_sharpe": 1.4 - i * 0.02,
         "oos_return": 0.19 - i * 0.01, "oos_max_drawdown": -0.22 - i * 0.005,
         "overfit_gap": 0.35 + i * 0.05}
        for i in range(15)
    ],
}

BT_STATUS = {"status": BT_STATUS_INNER, "sweep": SWEEP}

# CLOCK SKEW: the NAS writes the timestamps, the PHONE renders the ages. A NAS
# clock a little ahead used to print "-746m ago", which reads as a dead bridge.
BT_STATUS_SKEWED = json.loads(json.dumps(BT_STATUS))
BT_STATUS_SKEWED["status"]["generated_at"] = _ago(-45)
BT_STATUS_SKEWED["status"]["coverage_as_of"] = _ago(-45)
BT_STATUS_SKEWED["status"]["scheduler"]["last_tick"] = _ago(-45)

# A running experiment — the wider variant (live stat tiles + progress).
BT_STATUS_RUNNING = json.loads(json.dumps(BT_STATUS))
BT_STATUS_RUNNING["status"]["experiments"]["running"] = {
    "kind": "full_config",
    "hypothesis": "concentrating to 17 names raises expected compounded return",
    "fired_at": _ago(95),
    "windows": {"tune_start": "2023-07-25", "tune_end": "2025-07-25",
                "validate_start": "2025-07-25", "validate_end": "2026-07-25"},
    "progress_pct": 42,
    "live": {"phase": "tune", "as_of": "2024-11-08", "equity": 137421.55, "total_return": 0.3742,
             "annualized_return": 0.1638, "max_drawdown": -0.2413,
             "benchmark_total_return": 0.2510, "n_trades": 418, "n_positions": 17},
}


SPEC = TabSpec(
    name="lab", nav_id="nav-lab", screen_id="screen-lab",
    ready_selector="#lab-body", header_id="lab-sub", body_selector="#lab-body",
    expects={
        "idle": ["none running", "candidates fired this week", "baseline"],
        "running": ["running", "thesis:"],
        "clock-skew": ["none running", "just now"],
        # the machine's state, not the lane's bookkeeping
        "engine-busy": ["engine BUSY", "manual", "42%", "CAGR",
                        # must NOT contradict itself with "none running"
                        "lane idle (engine busy above)"],
    },
    extra=[lambda page, c, label: audit_leaderboard(page, c) if label == "idle" else None],
)


def audit_leaderboard(page, c):
    """The 6-column leaderboard is the widest thing on the screen: it must
    scroll inside its OWN container, never widen the page."""
    info = page.evaluate(
        """() => { const t = document.querySelector('#screen-lab .lab-tbl');
             if (!t) return null;
             let box = t.parentElement, scroller = null;
             while (box && box !== document.body) {
               const s = getComputedStyle(box);
               if (['auto','scroll'].includes(s.overflowX)) { scroller = box; break; }
               box = box.parentElement;
             }
             return {tableW: t.scrollWidth,
                     canScroll: scroller ? scroller.scrollWidth > scroller.clientWidth + 1 : false,
                     hasScroller: !!scroller,
                     scrollerCls: scroller ? String(scroller.className).slice(0,40) : null}; }""")
    c.check(info is not None, "[leaderboard] table rendered")
    if not info:
        return
    if info["tableW"] > IPHONE_X["width"]:
        c.check(info["hasScroller"] and info["canScroll"],
                f"[leaderboard] wide table ({info['tableW']}px) scrolls inside its own "
                f"container ({info['scrollerCls']}), not the page")
    else:
        c.check(True, f"[leaderboard] table fits the viewport ({info['tableW']}px)")


# A sweep the LANE did not start: bt-engine pegged while the strip used to say
# "none running". It must render the same bar + live tiles a lane run gets.
BT_STATUS_FOREIGN = json.loads(json.dumps(BT_STATUS))
BT_STATUS_FOREIGN["status"]["experiments"]["engine_busy"] = {
    "sweep_id": "manual-1234-5678-9abc", "n_configs": 1, "n_done": 0,
    "progress_pct": 42, "started_at": _ago(20), "owned_by_lane": False,
    "live": {"phase": "tune", "as_of": "2024-11-08", "total_return": 0.3742,
             "annualized_return": 0.1638, "max_drawdown": -0.2413,
             "benchmark_total_return": 0.2510, "n_trades": 418, "n_positions": 17},
}

VARIANTS = [
    ("idle", {"/api/bt/status": BT_STATUS}),
    ("engine-busy", {"/api/bt/status": BT_STATUS_FOREIGN}),
    ("running", {"/api/bt/status": BT_STATUS_RUNNING}),
    ("clock-skew", {"/api/bt/status": BT_STATUS_SKEWED}),
]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--shots", type=Path, default=None)
    a = ap.parse_args()
    sys.exit(run(SPEC, VARIANTS, headed=a.headed, shots=a.shots))
