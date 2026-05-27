"""
Dashboard UI intent catalog.

Each Intent codifies what the user SHOULD see when the system is in a given
state. Tests load a scenario (which configures the mock API), drive the
dashboard to a panel, then assert the visible UI matches `must_show`,
`must_hide`, `must_contain_text`, and `must_not_contain_text`.

Intents are organized by panel and by state, derived from the system design:

  • Screener panel
      INTENT: Show ranked tickers when ranking data exists.
      INTENT: Make the system state legible — a "READY" badge with empty
              rankings is a CONTRADICTION (the user's complaint).

  • Trader panel
      INTENT: Show pending signals with approve/reject controls.
      INTENT: Submitted signals must NOT show checkboxes or approve buttons.
              Their state is "done"; only Purge & Reset is offered.
      INTENT: The toolbar (Purge & Reset) must always be reachable whenever
              any signals exist — even all-submitted, all-hold, etc.

  • Portfolio panel
      INTENT: When Alpaca is not connected, say so explicitly. Don't show
              an empty positions table without explanation.

  • Pipeline run lifecycle
      INTENT: When RUN is clicked, the button must stay disabled until the
              pipeline reaches a terminal state OR 30 s elapse.
      INTENT: The status badge must reflect what is actively happening,
              not stale state from a previous run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Mock API scenarios ────────────────────────────────────────────────────────
# Each scenario is a dict of endpoint → response payload.
# Endpoints used by the dashboard:
#   /api/pipeline-status    — top status bar
#   /api/rankings/with-overlays?limit=150 — screener table
#   /api/delta/latest       — trader table
#   /api/live-portfolio     — portfolio panel
#   /api/orders/recent      — portfolio recent orders


def _empty_rankings():
    return {"rankings": [], "run": None, "regime": None}


def _full_rankings():
    return {
        "rankings": [
            {"rank": 1, "ticker": "AAPL", "name": "Apple Inc.", "composite_score": 0.92,
             "percentile": 99.5, "factor_scores": {"momentum": 1.5, "quality": 1.2},
             "rank_date": "2026-05-24", "regime": "bull_calm"},
            {"rank": 2, "ticker": "MSFT", "name": "Microsoft Corp.", "composite_score": 0.88,
             "percentile": 99.0, "factor_scores": {"momentum": 1.2, "quality": 1.4},
             "rank_date": "2026-05-24", "regime": "bull_calm"},
            {"rank": 3, "ticker": "NVDA", "name": "NVIDIA Corp.", "composite_score": 0.85,
             "percentile": 98.5, "factor_scores": {"momentum": 1.8, "quality": 0.9},
             "rank_date": "2026-05-24", "regime": "bull_calm"},
        ],
        "run": {"run_id": "r1", "run_date": "2026-05-24", "regime": "bull_calm"},
        "regime": {"current_regime": "bull_calm", "spy_price": 580.5},
    }


def _intent(id_: str, ticker: str, action: str, *, order_status=None,
            order_deferred_until=None, rejected_at=None, vetter_excluded=False,
            rank=1, score=0.9):
    return {
        "id": id_, "ticker": ticker, "action": action, "rank": rank,
        "composite_score": score, "rejected_at": rejected_at,
        "order_status": order_status, "order_error_message": None,
        "order_deferred_until": order_deferred_until,
        "vetter_excluded": vetter_excluded, "vetter_confidence": None,
        "vetter_risk_type": None, "vetter_reason": None,
        "reason": "test", "confirmation_days_met": True,
        "current_weight": 0, "actual_weight": None, "weight_drift": None,
        "positive_catalyst": False, "positive_reason": None,
    }


def _delta_run(entries=0, exits=0, holds=0, watches=0):
    return {
        "run_id": "dr1", "status": "success", "run_date": "2026-05-24",
        "entries_count": entries, "exits_count": exits,
        "holds_count": holds, "watches_count": watches,
        "at_risk_count": 0, "buy_add_count": 0, "sell_trim_count": 0,
    }


def _pipeline_status(rank_status="success", rank_date="2026-05-24"):
    return {
        "rank": {"status": rank_status, "date": rank_date,
                 "step_label": None, "pct": None},
        "vetter": {"status": "idle", "progress": None},
        "portfolio": {"status": "idle"},
        "universe": {"status": "idle"},
    }


SCENARIOS = {
    # ── Cold boot: pipeline has never run ────────────────────────────────────
    "cold_boot": {
        "/api/pipeline-status": {
            "rank": {"status": "idle", "date": None, "step_label": None, "pct": None},
            "vetter": {"status": "idle"}, "portfolio": {"status": "idle"},
            "universe": {"status": "idle"},
        },
        "/api/rankings/with-overlays": _empty_rankings(),
        "/api/delta/latest": {"run": None, "intents": []},
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },

    # ── Ready + populated: the happy path ────────────────────────────────────
    "ready_with_data": {
        "/api/pipeline-status": _pipeline_status(),
        "/api/rankings/with-overlays": _full_rankings(),
        "/api/delta/latest": {
            "run": _delta_run(entries=2, exits=1, holds=5),
            "intents": [
                _intent("i1", "AAPL", "entry", rank=1, score=0.92),
                _intent("i2", "MSFT", "entry", rank=2, score=0.88),
                _intent("i3", "NVDA", "exit", rank=15, score=0.41),
                _intent("i4", "GOOG", "hold", rank=5, score=0.78),
            ],
        },
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },

    # ── User's reported scenario: all entries are already submitted ──────────
    "all_submitted": {
        "/api/pipeline-status": _pipeline_status(),
        "/api/rankings/with-overlays": _full_rankings(),
        "/api/delta/latest": {
            "run": _delta_run(entries=2),
            "intents": [
                _intent("s1", "B",    "entry", rank=1, score=0.799, order_status="submitted"),
                _intent("s2", "AGNC", "entry", rank=2, score=0.797, order_status="submitted"),
            ],
        },
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },

    # ── OPG-window deferred: auto-approval landed in the 16:00–19:00 ET dead
    #    zone, orders are parked until the worker resubmits at 19:00 ET. The
    #    trader UI must show that they're queued, not failed.
    "all_deferred": {
        "/api/pipeline-status": _pipeline_status(),
        "/api/rankings/with-overlays": _full_rankings(),
        "/api/delta/latest": {
            "run": _delta_run(entries=2),
            "intents": [
                _intent("d1", "B",    "entry", rank=1, score=0.799,
                        order_status="deferred",
                        order_deferred_until="2026-05-27T23:00:00+00:00"),
                _intent("d2", "AGNC", "entry", rank=2, score=0.797,
                        order_status="deferred",
                        order_deferred_until="2026-05-27T23:00:00+00:00"),
            ],
        },
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },

    # ── Hold-only signals (pipeline ran but no buy/sell action needed) ───────
    "hold_only": {
        "/api/pipeline-status": _pipeline_status(),
        "/api/rankings/with-overlays": _full_rankings(),
        "/api/delta/latest": {
            "run": _delta_run(holds=4),
            "intents": [
                _intent("h1", "AAPL", "hold"),
                _intent("h2", "MSFT", "hold"),
                _intent("h3", "NVDA", "watch"),
                _intent("h4", "TSLA", "at_risk"),
            ],
        },
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },

    # ── Pipeline running RIGHT NOW ───────────────────────────────────────────
    "pipeline_running": {
        "/api/pipeline-status": {
            "rank": {"status": "running", "date": None,
                     "step_label": "Calculating Factors", "pct": 30},
            "vetter": {"status": "idle"}, "portfolio": {"status": "idle"},
            "universe": {"status": "idle"},
        },
        "/api/rankings/with-overlays": _full_rankings(),  # previous data still available
        "/api/delta/latest": {"run": None, "intents": []},
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },

    # ── Pipeline failed ──────────────────────────────────────────────────────
    "pipeline_failed": {
        "/api/pipeline-status": {
            "rank": {"status": "failed", "date": "2026-05-24",
                     "step_label": None, "pct": None,
                     "error_message": "DB connection lost"},
            "vetter": {"status": "idle"}, "portfolio": {"status": "idle"},
            "universe": {"status": "idle"},
        },
        "/api/rankings/with-overlays": _empty_rankings(),
        "/api/delta/latest": {"run": None, "intents": []},
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },

    # ── Mix of pending and submitted intents ─────────────────────────────────
    "mixed_pending_and_submitted": {
        "/api/pipeline-status": _pipeline_status(),
        "/api/rankings/with-overlays": _full_rankings(),
        "/api/delta/latest": {
            "run": _delta_run(entries=2),
            "intents": [
                _intent("p1", "AAPL", "entry", rank=1),
                _intent("p2", "MSFT", "entry", rank=2, order_status="submitted"),
                _intent("p3", "NVDA", "exit",  rank=15),
            ],
        },
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },

    # ── All intents rejected (after Purge & Reset) ───────────────────────────
    "all_rejected": {
        "/api/pipeline-status": _pipeline_status(),
        "/api/rankings/with-overlays": _full_rankings(),
        "/api/delta/latest": {
            "run": _delta_run(entries=2),
            "intents": [
                _intent("r1", "AAPL", "entry", rejected_at="2026-05-24T10:00:00Z"),
                _intent("r2", "MSFT", "entry", rejected_at="2026-05-24T10:00:00Z"),
            ],
        },
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },

    # ── Portfolio connected to Alpaca ────────────────────────────────────────
    "portfolio_connected": {
        "/api/pipeline-status": _pipeline_status(),
        "/api/rankings/with-overlays": _full_rankings(),
        "/api/delta/latest": {"run": _delta_run(), "intents": []},
        "/api/live-portfolio": {
            "connected": True,
            "sync": {"synced_at": "2026-05-24T22:30:00Z"},
            "account": {"portfolio_value": 100000, "buying_power": 25000,
                        "cash": 25000, "unrealized_pl": 500},
            "positions": [
                {"ticker": "AAPL", "qty": 50, "market_value": 9500,
                 "current_price": 190, "weight": 0.095,
                 "unrealized_pl": 250, "unrealized_plpc": 0.027, "day_pl": 50},
            ],
        },
        "/api/orders/recent": [],
    },

    # ── REGRESSION: user's exact bug — pipeline previously succeeded but
    # ── rankings API returns no data (DB cleared / migration mismatch /
    # ── transient 503). The current UI shows "READY" + "No ranking data"
    # ── which is a contradiction the user explicitly called out. ─────────────
    "ready_status_but_no_rankings": {
        "/api/pipeline-status": _pipeline_status(rank_status="success",
                                                  rank_date="2026-05-22"),
        "/api/rankings/with-overlays": _empty_rankings(),  # returns 503
        "/api/delta/latest": {"run": None, "intents": []},
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },

    # ── Vetter-excluded entries ──────────────────────────────────────────────
    "vetter_excluded": {
        "/api/pipeline-status": _pipeline_status(),
        "/api/rankings/with-overlays": _full_rankings(),
        "/api/delta/latest": {
            "run": _delta_run(entries=2),
            "intents": [
                _intent("v1", "PARR", "entry", vetter_excluded=True, rank=1),
                _intent("v2", "AAPL", "entry", rank=2),
            ],
        },
        "/api/live-portfolio": {"connected": False, "sync": {}},
        "/api/orders/recent": [],
    },
}


# ── Intent assertions ─────────────────────────────────────────────────────────

@dataclass
class Intent:
    """One intent — what UI state we expect for a given scenario+panel."""
    name: str
    scenario: str
    panel: str  # 'screener' | 'trader' | 'portfolio'
    description: str
    must_show: list[str] = field(default_factory=list)         # CSS selectors visible
    must_hide: list[str] = field(default_factory=list)         # CSS selectors hidden
    must_contain_text: list[str] = field(default_factory=list)
    must_not_contain_text: list[str] = field(default_factory=list)
    must_be_disabled: list[str] = field(default_factory=list)
    must_be_enabled: list[str] = field(default_factory=list)
    custom_check: Any = None  # callable(page) -> (ok, msg)


INTENTS: list[Intent] = [

    # ──────────────────────────────────────────────────────────────────────────
    # COLD BOOT — pipeline has never run
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="cold_boot_status_says_no_data_not_ready",
        scenario="cold_boot",
        panel="screener",
        description="When pipeline has never run, status must NOT say READY — "
                    "that's a contradiction. Should say IDLE/NO DATA.",
        must_not_contain_text=["READY"],
    ),

    Intent(
        name="cold_boot_screener_says_no_data_not_loading_forever",
        scenario="cold_boot",
        panel="screener",
        description="Screener must show a clear empty-state message, not "
                    "spin forever on 'Loading…'.",
        must_contain_text=["No ranking data"],
        must_not_contain_text=["Loading rankings…"],
    ),

    Intent(
        name="cold_boot_trader_says_no_signals",
        scenario="cold_boot",
        panel="trader",
        description="Trader with no intents shows clear empty state.",
        must_contain_text=["No signals"],
        must_hide=["#trader-toolbar"],  # nothing to purge
    ),

    Intent(
        name="cold_boot_portfolio_says_not_connected",
        scenario="cold_boot",
        panel="portfolio",
        description="Portfolio shows 'Not connected' message when Alpaca off.",
        must_contain_text=["Not connected"],
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # READY WITH DATA — happy path
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="ready_status_when_data_loaded",
        scenario="ready_with_data",
        panel="screener",
        description="Status badge says READY when rankings exist.",
        must_contain_text=["READY"],
    ),

    Intent(
        name="ready_screener_shows_tickers",
        scenario="ready_with_data",
        panel="screener",
        description="Screener table shows ranked tickers, not 'No data'.",
        must_contain_text=["AAPL", "MSFT", "NVDA"],
        must_not_contain_text=["No ranking data", "Loading"],
    ),

    Intent(
        name="ready_trader_shows_toolbar_with_pending",
        scenario="ready_with_data",
        panel="trader",
        description="Trader toolbar (with Purge button) is visible when signals exist.",
        must_show=["#trader-toolbar", "#btn-purge-all", "#btn-approve-sel"],
        must_contain_text=["AAPL", "MSFT", "NVDA"],
    ),

    Intent(
        name="ready_trader_shows_approve_buttons_for_pending",
        scenario="ready_with_data",
        panel="trader",
        description="Each pending entry/exit row has an approve (▶) and reject (✕) button.",
        custom_check=lambda page: _check_count(
            page, ".btn-sm-approve", expected=3,
            why="3 pending entries/exits should each have an approve button"
        ),
    ),

    Intent(
        name="ready_trader_pending_rows_have_checkboxes",
        scenario="ready_with_data",
        panel="trader",
        description="Pending entry/exit rows have selection checkboxes.",
        custom_check=lambda page: _check_count(
            page, ".trade-chk", expected=3,
            why="3 pending entry/exit rows should each have a checkbox"
        ),
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # ALL SUBMITTED — the user's reported scenario
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="submitted_trader_no_checkboxes",
        scenario="all_submitted",
        panel="trader",
        description="Submitted signals must NOT show selection checkboxes — "
                    "you can't re-approve an already-submitted order.",
        custom_check=lambda page: _check_count(
            page, ".trade-chk", expected=0,
            why="submitted signals must not be selectable for re-approval"
        ),
    ),

    Intent(
        name="submitted_trader_no_row_action_buttons",
        scenario="all_submitted",
        panel="trader",
        description="Submitted rows must NOT show ▶ approve / ✕ reject buttons.",
        custom_check=lambda page: _check_count(
            page, ".btn-sm-approve", expected=0,
            why="submitted rows should have no approve button"
        ),
    ),

    Intent(
        name="submitted_trader_toolbar_visible_with_purge",
        scenario="all_submitted",
        panel="trader",
        description="Toolbar with Purge & Reset MUST be visible even when all "
                    "signals are submitted (user needs to cancel + restart).",
        must_show=["#trader-toolbar", "#btn-purge-all"],
    ),

    Intent(
        name="submitted_trader_approve_selected_disabled",
        scenario="all_submitted",
        panel="trader",
        description="Approve Selected button is disabled when nothing approvable.",
        must_be_disabled=["#btn-approve-sel"],
    ),

    Intent(
        name="submitted_trader_status_says_submitted",
        scenario="all_submitted",
        panel="trader",
        description="Submitted rows show '✓ Submitted' status (capitalised for clarity).",
        must_contain_text=["Submitted"],
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # OPG-WINDOW DEFERRED — orders parked for the worker to retry at 19:00 ET
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="deferred_trader_status_says_queued",
        scenario="all_deferred",
        panel="trader",
        description="Deferred rows show 'Queued' (not 'Submitted' and not an error).",
        must_contain_text=["Queued"],
        must_not_contain_text=["Submitted", "Failed", "Error"],
    ),

    Intent(
        name="deferred_trader_no_approve_button",
        scenario="all_deferred",
        panel="trader",
        description="A deferred order is already in-flight — no approve button "
                    "(no duplicate submission while the worker holds the row).",
        must_be_disabled=["#btn-approve-sel"],
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # HOLD-ONLY — pipeline ran but no trades needed
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="hold_only_toolbar_still_visible",
        scenario="hold_only",
        panel="trader",
        description="Even when all signals are hold/watch, the Purge button "
                    "must be reachable (open orders from previous run may exist).",
        must_show=["#trader-toolbar", "#btn-purge-all"],
    ),

    Intent(
        name="hold_only_no_approve_buttons",
        scenario="hold_only",
        panel="trader",
        description="Hold signals don't need approval — no approve buttons shown.",
        custom_check=lambda page: _check_count(
            page, ".btn-sm-approve", expected=0,
            why="hold/watch/at_risk signals are not actionable"
        ),
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # REGRESSION: user's reported "READY + No ranking data" contradiction
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="no_contradictory_ready_with_empty_rankings",
        scenario="ready_status_but_no_rankings",
        panel="screener",
        description="When the pipeline status says READY but the rankings API "
                    "returns no data, the UI must NOT show 'READY' next to "
                    "'No ranking data' — that's an incoherent state. Either "
                    "the status should reflect the missing data, or the table "
                    "should explain why (stale / clearing / re-run needed).",
        custom_check=lambda page: _check_no_ready_empty_contradiction(page),
    ),

    Intent(
        name="empty_rankings_message_is_actionable",
        scenario="ready_status_but_no_rankings",
        panel="screener",
        description="When rankings are empty, the empty-state message must "
                    "tell the user what to do — not just say 'No ranking data'.",
        must_contain_text=["RUN"],  # must mention the RUN action somewhere
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # PIPELINE RUNNING — mid-execution
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="running_status_not_ready",
        scenario="pipeline_running",
        panel="screener",
        description="When pipeline is running, status must NOT say READY.",
        must_not_contain_text=["READY"],
    ),

    Intent(
        name="running_status_indicates_active_work",
        scenario="pipeline_running",
        panel="screener",
        description="Status must indicate something is happening "
                    "(e.g. CALCULATING, FETCHING, PROCESSING).",
        custom_check=lambda page: _check_status_indicates_running(page),
    ),

    Intent(
        name="running_run_button_disabled",
        scenario="pipeline_running",
        panel="screener",
        description="RUN button disabled while pipeline is running.",
        must_be_disabled=["#run-btn"],
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # PIPELINE FAILED
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="failed_status_shows_failed",
        scenario="pipeline_failed",
        panel="screener",
        description="Status must clearly say FAILED.",
        must_contain_text=["FAILED"],
    ),

    Intent(
        name="failed_run_button_enabled_to_retry",
        scenario="pipeline_failed",
        panel="screener",
        description="RUN button is enabled after a failure so user can retry.",
        must_be_enabled=["#run-btn"],
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # MIXED PENDING+SUBMITTED
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="mixed_only_pending_have_checkboxes",
        scenario="mixed_pending_and_submitted",
        panel="trader",
        description="Only the 2 pending rows have checkboxes; the 1 submitted does not.",
        custom_check=lambda page: _check_count(
            page, ".trade-chk", expected=2,
            why="of 3 rows (2 pending, 1 submitted), only pending get checkboxes"
        ),
    ),

    Intent(
        name="mixed_only_pending_have_approve_buttons",
        scenario="mixed_pending_and_submitted",
        panel="trader",
        description="Only pending rows have ▶ approve buttons.",
        custom_check=lambda page: _check_count(
            page, ".btn-sm-approve", expected=2,
            why="of 3 rows, only the 2 pending should have approve buttons"
        ),
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # ALL REJECTED — after Purge & Reset
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="rejected_status_shows_rejected",
        scenario="all_rejected",
        panel="trader",
        description="Rejected rows show 'Rejected' status.",
        must_contain_text=["Rejected"],
    ),

    Intent(
        name="rejected_no_approve_buttons",
        scenario="all_rejected",
        panel="trader",
        description="Rejected rows don't get approve buttons.",
        custom_check=lambda page: _check_count(
            page, ".btn-sm-approve", expected=0,
            why="rejected intents cannot be re-approved"
        ),
    ),

    Intent(
        name="rejected_toolbar_still_shows",
        scenario="all_rejected",
        panel="trader",
        description="Toolbar still visible so user can see the state and re-run.",
        must_show=["#trader-toolbar"],
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # PORTFOLIO CONNECTED
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="portfolio_connected_shows_positions",
        scenario="portfolio_connected",
        panel="portfolio",
        description="Connected Alpaca shows actual positions table.",
        must_contain_text=["AAPL", "Connected"],
        must_not_contain_text=["Not connected"],
    ),

    # ──────────────────────────────────────────────────────────────────────────
    # VETTER EXCLUDED
    # ──────────────────────────────────────────────────────────────────────────

    Intent(
        name="vetter_excluded_blocks_approval",
        scenario="vetter_excluded",
        panel="trader",
        description="Vetter-excluded entry must NOT have an approve button.",
        custom_check=lambda page: _check_count(
            page, ".btn-sm-approve", expected=1,
            why="1 of 2 entries is vetter-excluded — only 1 approve button"
        ),
    ),

    Intent(
        name="vetter_excluded_shows_warning",
        scenario="vetter_excluded",
        panel="trader",
        description="Vetter-excluded entry shows a 'Vetter blocked' warning.",
        must_contain_text=["Vetter blocked"],
    ),
]


# ── Custom-check helpers ──────────────────────────────────────────────────────

def _check_count(page, selector: str, expected: int, why: str) -> tuple[bool, str]:
    """Return (ok, message) — ok if page has exactly `expected` instances of selector."""
    actual = page.locator(selector).count()
    if actual == expected:
        return True, f"  ✓ {selector}: {actual} (expected {expected})"
    return False, f"  ✗ {selector}: got {actual}, expected {expected} — {why}"


def _check_status_indicates_running(page) -> tuple[bool, str]:
    """Status badge text must contain a 'work happening' word."""
    text = (page.locator("#sb-text").inner_text() or "").upper()
    work_words = ["RUNNING", "FETCHING", "CALCULATING", "RANKING",
                  "EVALUATING", "PROCESSING", "BUILDING", "ANALYSIS"]
    if any(w in text for w in work_words):
        return True, f"  ✓ status badge says: {text!r}"
    return False, f"  ✗ status badge {text!r} doesn't indicate active work"


def _check_no_ready_empty_contradiction(page) -> tuple[bool, str]:
    """
    Codifies the user's complaint: if the status badge says READY, the
    rankings table must not say 'No ranking data' simultaneously.
    """
    status = (page.locator("#sb-text").inner_text() or "").upper().strip()
    rbody  = page.locator("#r-body").inner_text() or ""
    says_ready = status == "READY"
    says_empty = "No ranking data" in rbody
    if says_ready and says_empty:
        return False, (
            f"  ✗ status='READY' AND rankings table says 'No ranking data' — "
            f"this is the exact contradiction the user reported"
        )
    return True, f"  ✓ no contradiction (status={status!r}, rankings empty={says_empty})"
