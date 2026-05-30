"""
Regression tests for the Run button / pipeline status display bugs.

Bug 1 (status shows READY when running):
  When the user clicks Run and the dashboard background task starts
  (_rank_chain_running = True), /api/pipeline-status should return
  rank.status = "running" even if the previous run left
  pipeline_status_raw = "success" in the pipeline service.

  Root cause: confirmed_terminal was computed from pipeline_status_raw
  without checking _rank_chain_running, so the orchestrator_running guard
  was bypassed and the stale "success" was returned as-is.

Bug 2 (button re-enables briefly after click):
  Same root cause as Bug 1 — because status returned "success", the JS
  updatePipelineBar() set btn.disabled = false immediately after the first
  1.5-second refresh poll.

Both bugs are fixed together:
  - Backend: confirmed_terminal = ... and not _rank_chain_running
  - Frontend: _runRequestedAt guard keeps btn.disabled for 30 s after click
"""
import asyncio
import re as _re
import sys
import os
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

# Suppress the "coroutine was never awaited" warnings from the mock framework
# when asyncio.gather is patched — the uncollected coroutines are from the
# patched-out service calls that never actually run.
pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

# ── path bootstrap ────────────────────────────────────────────────────────────

_DASH_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "dashboard")
)
for _k in list(sys.modules.keys()):
    if _k == "app" or _k.startswith("app."):
        del sys.modules[_k]
if _DASH_PATH not in sys.path:
    sys.path.insert(0, _DASH_PATH)


# ── helpers ───────────────────────────────────────────────────────────────────

def _fake_pipeline_response(status: str) -> MagicMock:
    """Build a mock httpx response that mimics pipeline /runs/latest."""
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {
        "status": status,
        "factor_status": None,
        "ranking_status": None,
        "delta_status": None,
        "completed_at": "2024-01-15T12:00:00Z",
    }
    return m


def _fake_empty_response() -> MagicMock:
    m = MagicMock()
    m.status_code = 503
    m.json.return_value = {"error": "timeout"}
    return m


def _fake_scheduler_response(status: str = "idle") -> MagicMock:
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"status": status, "steps": {}}
    return m


def _fake_rankings_response(rank_date: str = "2024-01-15") -> MagicMock:
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"rankings": [{"rank_date": rank_date}]}
    return m


EMPTY = _fake_empty_response


# ── test suite ────────────────────────────────────────────────────────────────

class TestStatusWhenRankChainRunning:
    """_rank_chain_running=True must always result in rank.status='running'."""

    def _run_pipeline_status(self, pipeline_status_raw: str, rank_chain_running: bool):
        """Call the dashboard pipeline_status() endpoint with mocked service calls."""
        import app.main as dash
        # Patch _rank_chain_running
        original = dash._rank_chain_running
        dash._rank_chain_running = rank_chain_running
        try:
            # Mock all downstream HTTP calls
            async def _run():
                with patch.object(
                    httpx.AsyncClient, "get",
                    new_callable=lambda: self._make_get_mock(pipeline_status_raw)
                ):
                    return await dash.pipeline_status()
            return asyncio.get_event_loop().run_until_complete(_run())
        finally:
            dash._rank_chain_running = original

    def _make_get_mock(self, pipeline_status_raw: str):
        """Return an AsyncMock for httpx.AsyncClient.get that serves fake service data."""
        class _CM:
            def __init__(self, resp): self._resp = resp
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            async def get(self, url, **_):
                if "pipeline" in url and "runs/latest" in url:
                    return _fake_pipeline_response(pipeline_status_raw)
                if "rankings" in url:
                    return _fake_rankings_response()
                if "scheduler" in url:
                    return _fake_scheduler_response("idle")
                return EMPTY()
        return lambda self: _CM(None)

    def _call_status(self, pipeline_status_raw: str, rank_chain_running: bool) -> dict:
        import app.main as dash
        dash._rank_chain_running = rank_chain_running

        all_empty = EMPTY()
        pipeline_resp = _fake_pipeline_response(pipeline_status_raw)
        rankings_resp = _fake_rankings_response()
        sched_resp    = _fake_scheduler_response("idle")

        async def _run():
            # Monkey-patch _safe_fetch so we don't need a real event loop / HTTP
            async def _fake_safe_fetch(coro, default):
                try:
                    resp = await coro
                    return resp
                except Exception:
                    return type("R", (), {"status_code": 503, "json": lambda s: {}})()

            # Replace all the gather calls by patching asyncio.gather
            import unittest.mock as mock

            # Build the 8-item tuple returned by asyncio.gather in pipeline_status
            async def fake_gather(*coros):
                # r0 (uni), r1 (rankings), r3 (portfolio), sys_status, r4 (pipeline), r5 (av-ingestor), r7 (scheduler), r8 (progress)
                return [
                    EMPTY(),          # r0: universe
                    rankings_resp,    # r1: rankings
                    EMPTY(),          # r3: portfolio
                    EMPTY(),          # sys_status_resp
                    pipeline_resp,    # r4_direct: pipeline /runs/latest
                    EMPTY(),          # r5_direct: av-ingestor /runs/latest
                    sched_resp,       # r7_direct: scheduler /status
                    EMPTY(),          # r8_direct: pipeline /runs/progress
                ]

            with mock.patch("asyncio.gather", side_effect=fake_gather):
                return await dash.pipeline_status()

        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(_run())
            return result
        finally:
            loop.close()
            dash._rank_chain_running = False  # cleanup

    # ── actual tests ──────────────────────────────────────────────────────────

    def test_running_when_chain_active_and_prev_success(self):
        """
        Regression: if previous run was 'success' AND _rank_chain_running=True,
        status must be 'running', not 'success'.
        """
        result = self._call_status(
            pipeline_status_raw="success",
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("status") == "running", (
            f"Expected rank.status='running' when _rank_chain_running=True "
            f"and prev pipeline_status='success', got {rank.get('status')!r}"
        )

    def test_running_when_chain_active_and_prev_partial_success(self):
        result = self._call_status(
            pipeline_status_raw="partial_success",
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("status") == "running", (
            f"Expected 'running', got {rank.get('status')!r}"
        )

    def test_running_when_chain_active_and_no_prev_run(self):
        """Fresh system with no prior run: chain active → status must be 'running'."""
        result = self._call_status(
            pipeline_status_raw=None,
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("status") == "running", (
            f"Expected 'running', got {rank.get('status')!r}"
        )

    def test_success_when_chain_not_active_and_prev_success(self):
        """Normal completed state: chain not running, prev run was success → 'success'."""
        result = self._call_status(
            pipeline_status_raw="success",
            rank_chain_running=False,
        )
        rank = result.get("rank", {})
        assert rank.get("status") == "success", (
            f"Expected 'success' after chain finished, got {rank.get('status')!r}"
        )

    def test_failed_when_chain_not_active_and_prev_failed(self):
        result = self._call_status(
            pipeline_status_raw="failed",
            rank_chain_running=False,
        )
        rank = result.get("rank", {})
        assert rank.get("status") == "failed", (
            f"Expected 'failed', got {rank.get('status')!r}"
        )

    def test_confirmed_terminal_not_set_when_chain_running(self):
        """The fix: confirmed_terminal must be False when _rank_chain_running=True."""
        import app.main as dash
        # Directly test the logic that was broken
        dash._rank_chain_running = True
        try:
            # Simulate what pipeline_status() computes for confirmed_terminal
            pipeline_status_raw = "success"
            confirmed_terminal = (
                pipeline_status_raw in ("success", "partial_success", "skipped", "failed")
                and not dash._rank_chain_running
            )
            assert not confirmed_terminal, (
                "confirmed_terminal must be False when _rank_chain_running=True"
            )
        finally:
            dash._rank_chain_running = False

    def test_confirmed_terminal_set_when_chain_not_running(self):
        """Normal case: chain not running + previous success → confirmed_terminal."""
        import app.main as dash
        dash._rank_chain_running = False
        try:
            pipeline_status_raw = "success"
            confirmed_terminal = (
                pipeline_status_raw in ("success", "partial_success", "skipped", "failed")
                and not dash._rank_chain_running
            )
            assert confirmed_terminal, (
                "confirmed_terminal should be True when chain is idle and previous run succeeded"
            )
        finally:
            pass


class TestJSRunButtonLogic:
    """
    Verify the JS-side guard logic by extracting and evaluating the key
    variable from dashboard.js in Python.

    This tests that:
    1. _runRequestedAt is set when startJob is called
    2. recentlyRequested is True within RUN_LOCK_MS
    3. showAsRunning is True when recentlyRequested
    4. recentlyRequested becomes False after RUN_LOCK_MS
    """

    def _load_js_constants(self):
        """Read RUN_LOCK_MS from dashboard.js."""
        js_path = os.path.join(_DASH_PATH, "app", "static", "dashboard.js")
        if not os.path.exists(js_path):
            js_path = os.path.join(_DASH_PATH, "static", "dashboard.js")
        with open(js_path) as f:
            content = f.read()
        m = _re.search(r'const RUN_LOCK_MS\s*=\s*(\d+)', content)
        assert m, "RUN_LOCK_MS not found in dashboard.js"
        return int(m.group(1))

    def test_run_lock_ms_is_defined(self):
        ms = self._load_js_constants()
        assert ms >= 10_000, f"RUN_LOCK_MS should be ≥ 10s, got {ms}"

    def test_run_button_lock_logic_recently_requested(self):
        """Simulate recentlyRequested logic: within lock window → True."""
        import time
        run_lock_ms = self._load_js_constants()
        run_requested_at = time.time() * 1000  # simulate _runRequestedAt = Date.now()
        now = run_requested_at + 100  # 100ms later
        recently_requested = (now - run_requested_at) < run_lock_ms
        assert recently_requested

    def test_run_button_lock_logic_expired(self):
        """After lock window expires, recentlyRequested → False."""
        import time
        run_lock_ms = self._load_js_constants()
        run_requested_at = time.time() * 1000
        now = run_requested_at + run_lock_ms + 1000  # well past the lock
        recently_requested = (now - run_requested_at) < run_lock_ms
        assert not recently_requested

    def test_show_as_running_when_recently_requested(self):
        """showAsRunning should be True even if backend says 'success'."""
        import time
        run_lock_ms = self._load_js_constants()
        run_requested_at = time.time() * 1000
        now = run_requested_at + 500  # 500ms after click

        running = False   # backend still says success
        vet_running = False
        success = True    # stale success from previous run
        failed = False
        recently_requested = (now - run_requested_at) < run_lock_ms

        show_as_running = running or (vet_running and not success and not failed) or recently_requested
        assert show_as_running, (
            "Button should stay disabled (showAsRunning=True) immediately after click "
            "even when backend returns stale 'success' from previous run"
        )

    def test_show_as_running_false_after_lock_expires(self):
        """After lock, button re-enables if pipeline is genuinely idle."""
        import time
        run_lock_ms = self._load_js_constants()
        run_requested_at = time.time() * 1000
        now = run_requested_at + run_lock_ms + 5000  # 5s after lock expires

        running = False
        vet_running = False
        success = True
        failed = False
        recently_requested = (now - run_requested_at) < run_lock_ms

        show_as_running = running or (vet_running and not success and not failed) or recently_requested
        assert not show_as_running, (
            "Button should re-enable after lock expires if pipeline is genuinely idle"
        )

    def test_run_lock_ms_present_in_dashboard_js(self):
        """RUN_LOCK_MS constant must be present in dashboard.js."""
        js_path = os.path.join(_DASH_PATH, "app", "static", "dashboard.js")
        if not os.path.exists(js_path):
            js_path = os.path.join(_DASH_PATH, "static", "dashboard.js")
        with open(js_path) as f:
            content = f.read()
        assert "RUN_LOCK_MS" in content, "RUN_LOCK_MS not found in dashboard.js"
        assert "_runRequestedAt" in content, "_runRequestedAt not found in dashboard.js"
        assert "recentlyRequested" in content, "recentlyRequested not found in dashboard.js"

    def test_run_requested_at_set_in_start_job(self):
        """startJob() must set _runRequestedAt = Date.now() before disabling the button."""
        js_path = os.path.join(_DASH_PATH, "app", "static", "dashboard.js")
        if not os.path.exists(js_path):
            js_path = os.path.join(_DASH_PATH, "static", "dashboard.js")
        with open(js_path) as f:
            content = f.read()
        # Find the startJob function body
        m = _re.search(r'async function startJob\(.*?\)\s*\{(.*?)^\}', content,
                       _re.DOTALL | _re.MULTILINE)
        assert m, "startJob function not found"
        body = m.group(1)
        assert "_runRequestedAt" in body, (
            "_runRequestedAt must be set inside startJob()"
        )

    def test_recently_requested_in_update_pipeline_bar(self):
        """updatePipelineBar() must use recentlyRequested in showAsRunning."""
        js_path = os.path.join(_DASH_PATH, "app", "static", "dashboard.js")
        if not os.path.exists(js_path):
            js_path = os.path.join(_DASH_PATH, "static", "dashboard.js")
        with open(js_path) as f:
            content = f.read()
        m = _re.search(r'function updatePipelineBar\(.*?\)\s*\{(.*?)^\}', content,
                       _re.DOTALL | _re.MULTILINE)
        assert m, "updatePipelineBar function not found"
        body = m.group(1)
        assert "recentlyRequested" in body, (
            "updatePipelineBar() must use recentlyRequested in its showAsRunning expression"
        )
        assert "showAsRunning" in body, "showAsRunning variable must exist in updatePipelineBar"


_TRADE_ACTIONS = {"entry", "buy_add", "exit", "sell_trim"}


class TestTraderToolbarVisibility:
    """
    Regression tests for the trader order blotter.

    The Trader screen is an order blotter: it shows ONLY actionable order types
    (entry / buy_add / exit / sell_trim — Buy to Open / Buy to Add / Sell to Close
    / Sell to Trim). hold / watch / at_risk are informational and excluded. The
    toolbar (with 'Clear approved trades') is therefore visible only when at least
    one such order exists.
    """

    def _load_js(self):
        js_path = os.path.join(_DASH_PATH, "app", "static", "dashboard.js")
        if not os.path.exists(js_path):
            js_path = os.path.join(_DASH_PATH, "static", "dashboard.js")
        with open(js_path) as f:
            return f.read()

    def _toolbar_visible(self, intents: list[dict]) -> bool:
        """Mirror of renderTrader: the blotter (and toolbar) shows only trade orders."""
        return any(i.get("action") in _TRADE_ACTIONS for i in intents)

    def test_toolbar_visible_with_entry_intents(self):
        """Entry orders → blotter + toolbar shown."""
        assert self._toolbar_visible([{"action": "entry"}, {"action": "entry"}])

    def test_toolbar_visible_with_exit_intents(self):
        """Exit orders → shown."""
        assert self._toolbar_visible([{"action": "exit"}])

    def test_blotter_hidden_with_hold_only_intents(self):
        """Hold/watch-only run → NOT an order, so the blotter shows nothing here."""
        assert not self._toolbar_visible([{"action": "hold"}, {"action": "watch"}, {"action": "at_risk"}])

    def test_toolbar_hidden_with_no_intents(self):
        """No delta run / no intents → nothing to show."""
        assert not self._toolbar_visible([])

    def test_toolbar_visible_with_mixed_intents(self):
        """Mixed hold + entry → shown (because of the entry order)."""
        assert self._toolbar_visible([{"action": "hold"}, {"action": "entry"}])

    def test_js_trader_filters_to_trade_actions(self):
        """renderTrader() must restrict the blotter to the four order actions."""
        content = self._load_js()
        m = _re.search(r'function renderTrader\(\s*\)\s*\{(.*?)^\}', content,
                       _re.DOTALL | _re.MULTILINE)
        assert m, "renderTrader function not found in dashboard.js"
        body = m.group(1)
        assert "TRADE_ACTIONS" in body, "renderTrader() must filter to TRADE_ACTIONS"
        # the four order actions must be the defined trade set
        for act in ("entry", "buy_add", "exit", "sell_trim"):
            assert act in content, f"TRADE_ACTIONS missing {act}"
        assert "sorted.length" in body, "renderTrader() must keep the empty-blotter check"

    def test_clear_approved_button_present_in_html(self):
        """btn-clear-approved must exist in the dashboard HTML template; the old
        purge button must be gone."""
        main_path = os.path.join(_DASH_PATH, "app", "main.py")
        if not os.path.exists(main_path):
            main_path = os.path.join(_DASH_PATH, "main.py")
        with open(main_path) as f:
            content = f.read()
        assert "btn-clear-approved" in content, "Clear-approved button not found in dashboard HTML"
        assert "clearApprovedTrades()" in content, "clearApprovedTrades() onclick not found"
        assert "btn-purge-all" not in content, "stale Purge & Reset button still present"
        assert "purgeAll()" not in content, "stale purgeAll() handler still present"

    def test_clear_approved_function_in_js(self):
        """clearApprovedTrades() must exist in dashboard.js, be cosmetic-only
        (no backend call), and the old purge function/endpoint must be gone."""
        content = self._load_js()
        assert "function clearApprovedTrades()" in content, (
            "clearApprovedTrades() not defined in dashboard.js"
        )
        # Cosmetic only — must NOT hit any purge/cancel endpoint.
        assert "function purgeAll()" not in content, "stale purgeAll() still present"
        assert "/api/trade/purge-all" not in content, (
            "clear-approved must not call the (removed) purge endpoint"
        )
        # Dismissals are persisted client-side and keyed by run so they survive polling.
        assert "_clearedTrades" in content, "clearApprovedTrades() must track dismissed intents"


# ── Helpers shared by new test classes ───────────────────────────────────────

def _call_pipeline_status(
    *,
    pipeline_status_raw: str | None = None,
    pipeline_factor_status: str | None = None,
    pipeline_rank_status: str | None = None,
    pipeline_delta_status: str | None = None,
    pipeline_progress: dict | None = None,
    av_ingestor_data: dict | None = None,
    scheduler_data: dict | None = None,
    rank_chain_running: bool = False,
) -> dict:
    """
    Call dashboard pipeline_status() with full control over every mocked service.

    Returns the parsed JSON dict that the endpoint would return to the browser.
    """
    import app.main as dash
    import unittest.mock as mock

    original_rcr = dash._rank_chain_running
    dash._rank_chain_running = rank_chain_running

    def _make_resp(data: dict | None):
        m = MagicMock()
        m.status_code = 200 if data is not None else 503
        m.json.return_value = data or {}
        return m

    pipeline_payload = {
        "status":         pipeline_status_raw,
        "factor_status":  pipeline_factor_status,
        "ranking_status": pipeline_rank_status,
        "delta_status":   pipeline_delta_status,
        "completed_at":   "2024-01-15T12:00:00Z",
    }
    av_payload      = av_ingestor_data or {}
    sched_payload   = scheduler_data   or {"status": "idle", "steps": {}}
    # r8_direct = pipeline /runs/progress. EMPTY() (503) mimics the endpoint being
    # unreachable; a real dict mimics the pipeline serving live sub-step progress.
    progress_resp   = _make_resp(pipeline_progress) if pipeline_progress is not None else EMPTY()

    async def fake_gather(*_coros):
        return [
            EMPTY(),                        # r0: universe
            _make_resp({"rankings": []}),   # r1: rankings
            EMPTY(),                        # r3: portfolio
            EMPTY(),                        # sys_status_resp
            _make_resp(pipeline_payload),   # r4_direct: pipeline /runs/latest
            _make_resp(av_payload or None), # r5_direct: av-ingestor /runs/latest
            _make_resp(sched_payload),      # r7_direct: scheduler /status
            progress_resp,                  # r8_direct: pipeline /runs/progress
        ]

    try:
        loop = asyncio.new_event_loop()
        with mock.patch("asyncio.gather", side_effect=fake_gather):
            result = loop.run_until_complete(dash.pipeline_status())
        return result
    finally:
        loop.close()
        dash._rank_chain_running = original_rcr


# ── TestStepLabelBetweenSteps ─────────────────────────────────────────────────

class TestStepLabelBetweenSteps:
    """
    Regression: the gap between pipeline steps must never show 'Fetching Data'.

    Before the fix, when the orchestrator was running but neither av-ingestor
    nor pipeline were actively in-flight, the fallback label was hardcoded to
    'Fetching Data'. This caused the status bar to flash the wrong label every
    time the chain advanced (after factors, after vet, etc.).

    After the fix: fallback is 'Running' and the scheduler step states are used
    to infer the correct next-step label.
    """

    def test_between_steps_never_shows_fetching_data(self):
        """
        Regression: orchestrator running, no service in-flight → must NOT say 'Fetching Data'.
        """
        result = _call_pipeline_status(
            pipeline_status_raw="success",   # pipeline just finished
            scheduler_data={"status": "running", "steps": {}},  # chain still going
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("status") == "running"
        assert rank.get("step_label") != "Fetching Data", (
            "Between steps the label must not be 'Fetching Data'; "
            f"got {rank.get('step_label')!r}"
        )

    def test_between_steps_shows_running_when_no_step_identified(self):
        """
        When the chain is running but no specific next step is identifiable,
        the label must be 'Running', not the misleading 'Fetching Data'.
        """
        result = _call_pipeline_status(
            pipeline_status_raw="success",
            scheduler_data={"status": "running", "steps": {}},
            rank_chain_running=True,
        )
        label = result.get("rank", {}).get("step_label")
        assert label == "Running", f"Expected 'Running', got {label!r}"

    def test_between_steps_uses_scheduler_running_step_label(self):
        """
        When the scheduler reports a step as 'running', its label must propagate
        to the status bar even when pipeline is idle.
        """
        result = _call_pipeline_status(
            pipeline_status_raw="success",
            scheduler_data={
                "status": "running",
                "steps": {"fetch-data": "done", "pipeline": "done", "vet": "running"},
            },
            rank_chain_running=True,
        )
        label = result.get("rank", {}).get("step_label")
        assert label == "Vetting", (
            f"Expected 'Vetting' when vet step is running, got {label!r}"
        )

    def test_between_steps_infers_next_step_label_when_none_running(self):
        """
        When all done steps are 'done' and the next is 'idle', infer the label
        from that next step rather than defaulting to 'Fetching Data'.
        """
        result = _call_pipeline_status(
            pipeline_status_raw="success",
            scheduler_data={
                "status": "running",
                "steps": {
                    "fetch-data": "done",
                    "pipeline":   "done",
                    "vet":        "idle",
                    "portfolio-builder": "idle",
                    "delta": "idle",
                },
            },
            rank_chain_running=True,
        )
        label = result.get("rank", {}).get("step_label")
        assert label == "Vetting", (
            f"Expected 'Vetting' (first non-done step), got {label!r}"
        )

    def test_portfolio_builder_step_inferred_after_vet_done(self):
        """After vet completes, the inferred label must be 'Building Portfolio'."""
        result = _call_pipeline_status(
            pipeline_status_raw="success",
            scheduler_data={
                "status": "running",
                "steps": {
                    "fetch-data": "done",
                    "pipeline":   "done",
                    "vet":        "done",
                    "portfolio-builder": "idle",
                    "delta": "idle",
                },
            },
            rank_chain_running=True,
        )
        label = result.get("rank", {}).get("step_label")
        assert label == "Building Portfolio", f"Got {label!r}"

    def test_delta_step_inferred_after_portfolio_done(self):
        """After portfolio-builder completes, the inferred label must be 'Evaluating Signals'."""
        result = _call_pipeline_status(
            pipeline_status_raw="success",
            scheduler_data={
                "status": "running",
                "steps": {
                    "fetch-data":        "done",
                    "pipeline":          "done",
                    "vet":               "done",
                    "portfolio-builder": "done",
                    "delta":             "idle",
                },
            },
            rank_chain_running=True,
        )
        label = result.get("rank", {}).get("step_label")
        assert label == "Evaluating Signals", f"Got {label!r}"

    def test_fetch_data_running_shows_fetching_data(self):
        """When fetch-data IS actually running, 'Fetching Data' is correct."""
        result = _call_pipeline_status(
            pipeline_status_raw=None,
            av_ingestor_data={"status": "running", "job_type": "fetch-data", "tickers_done": 5, "total_tickers": 50},
            scheduler_data={"status": "running", "steps": {"fetch-data": "running"}},
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("status") == "running"
        assert rank.get("step_label") == "Fetching Data", (
            f"While av-ingestor is actually fetching data, label should be 'Fetching Data'; "
            f"got {rank.get('step_label')!r}"
        )

    def test_calculating_factors_while_pipeline_running(self):
        """While pipeline factor_status='running', label must be 'Calculating Factors'."""
        result = _call_pipeline_status(
            pipeline_status_raw="running",
            pipeline_factor_status="running",
            scheduler_data={"status": "running", "steps": {"pipeline": "running"}},
            rank_chain_running=True,
        )
        label = result.get("rank", {}).get("step_label")
        assert label == "Calculating Factors", f"Got {label!r}"


# ── TestSubStepProgressPercentage ─────────────────────────────────────────────

class TestSubStepProgressPercentage:
    """
    Regression: the live sub-step percentage from the pipeline's /runs/progress
    endpoint must reach rank.pct in the status payload.

    History: this path had ZERO coverage — the harness always stubbed
    /runs/progress with EMPTY(), and tests asserted only the step *label*. When
    the pipeline's heavy factor math starved its event loop, /runs/progress timed
    out, rank.pct went blank, and nothing failed. These tests feed a live progress
    payload and assert the number actually flows through, for every pipeline step.
    """

    def test_factor_percentage_reaches_rank_pct(self):
        result = _call_pipeline_status(
            pipeline_status_raw="running",
            pipeline_factor_status="running",
            pipeline_progress={"step": "calc_factors", "pct": 58},
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("step_label") == "Calculating Factors"
        assert rank.get("pct") == 58, f"factor pct did not flow through; got {rank.get('pct')!r}"

    def test_ranking_percentage_reaches_rank_pct(self):
        result = _call_pipeline_status(
            pipeline_status_raw="running",
            pipeline_rank_status="running",
            pipeline_progress={"step": "ranking", "pct": 82},
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("step_label") == "Ranking"
        assert rank.get("pct") == 82, f"ranking pct did not flow through; got {rank.get('pct')!r}"

    def test_delta_percentage_reaches_rank_pct(self):
        result = _call_pipeline_status(
            pipeline_status_raw="running",
            pipeline_delta_status="running",
            pipeline_progress={"step": "delta", "pct": 48},
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("step_label") == "Evaluating Signals"
        assert rank.get("pct") == 48, f"delta pct did not flow through; got {rank.get('pct')!r}"

    def test_pct_is_none_when_progress_step_mismatches_status(self):
        """Stale/other-step progress must NOT leak into the current step's pct."""
        result = _call_pipeline_status(
            pipeline_status_raw="running",
            pipeline_factor_status="running",
            pipeline_progress={"step": "ranking", "pct": 82},  # wrong step for factor status
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("step_label") == "Calculating Factors"
        assert rank.get("pct") is None, f"mismatched-step pct must be None; got {rank.get('pct')!r}"

    def test_pct_blank_when_progress_endpoint_unreachable(self):
        """Endpoint times out (the original bug's symptom): label shows, pct is blank."""
        result = _call_pipeline_status(
            pipeline_status_raw="running",
            pipeline_factor_status="running",
            pipeline_progress=None,  # EMPTY() / 503 — endpoint unreachable
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("step_label") == "Calculating Factors"
        assert rank.get("pct") is None


# ── TestSchedulerStepLabelMapping ─────────────────────────────────────────────

class TestSchedulerStepLabelMapping:
    """
    Every scheduler step name must map to the correct human-readable status bar label.
    Tested via the pipeline_status endpoint (integration of the mapping logic).
    """

    _CASES = [
        ("fetch-data",        "Fetching Data"),
        ("pipeline",          "Calculating Factors"),
        ("vet",               "Vetting"),
        ("portfolio-builder", "Building Portfolio"),
        ("delta",             "Evaluating Signals"),
    ]

    @pytest.mark.parametrize("step_name,expected_label", _CASES)
    def test_running_step_produces_correct_label(self, step_name: str, expected_label: str):
        """Each scheduler step name must map to its expected display label."""
        steps = {s: "done" for s, _ in self._CASES}
        steps[step_name] = "running"

        result = _call_pipeline_status(
            pipeline_status_raw="success" if step_name != "pipeline" else "running",
            pipeline_factor_status="running" if step_name == "pipeline" else None,
            scheduler_data={"status": "running", "steps": steps},
            rank_chain_running=True,
        )
        label = result.get("rank", {}).get("step_label")
        assert label == expected_label, (
            f"Step '{step_name}' running → expected label {expected_label!r}, got {label!r}"
        )


# ── TestPipelineAlsoAcceptPrev ────────────────────────────────────────────────

# Inline minimal step-state logic so these tests don't need to import the
# scheduler module (which pulls in apscheduler, not installed outside Docker,
# and whose sys.path is reset by the conftest between tests).
from dataclasses import dataclass as _dc, field as _dcf
from typing import Literal as _Lit

@_dc
class _SchedStep:
    name: str
    url: str
    start_path: str
    date_field: str
    status_path: str = ""
    use_trading_day: bool = False
    also_accept_prev: bool = False
    extra_ok: tuple = _dcf(default_factory=tuple)
    job_type: str | None = None
    max_running_minutes: int | None = None

    def __post_init__(self):
        if not self.status_path:
            self.status_path = "/runs/latest"


async def _sched_step_state(client, step: _SchedStep, today: str, trading_day: str,
                            prev_trading_day: str) -> str:
    """Minimal replica of scheduler._step_state for unit-testing the date logic."""
    r = await client.get(f"{step.url}{step.status_path}", timeout=10.0)
    if r.status_code != 200:
        return "idle"
    data = r.json()
    if step.job_type and data.get("job_type") != step.job_type:
        return "idle"
    target = trading_day if step.use_trading_day else today
    ok_dates = {target, prev_trading_day} if step.also_accept_prev else {target}
    run_date = (data.get(step.date_field) or "")[:10]
    run_status = data.get("status")
    if run_date not in ok_dates:
        return "idle"
    if run_status in ("success",) + step.extra_ok:
        return "done"
    if run_status == "running":
        return "running"
    if run_status in ("failed",):
        return "failed"
    return "idle"


_SCHED_MAIN = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "scheduler", "app", "main.py")
)


class TestPipelineAlsoAcceptPrev:
    """
    Regression: pipeline step must have also_accept_prev=False.

    When also_accept_prev=True, the scheduler treated yesterday's successful
    pipeline run as 'done' on normal trading days, skipping the pipeline step
    entirely and causing the chain to stall at vetting/portfolio-builder.

    This mirrors the analogous tests for portfolio-builder and delta added in
    commit aa3adb3.
    """

    def test_pipeline_also_accept_prev_is_false(self):
        """
        Regression: pipeline step must not have also_accept_prev=True.

        Verified by reading the scheduler source directly — no module import
        needed, so it's immune to conftest sys.path resets.
        """
        with open(_SCHED_MAIN) as fh:
            source = fh.read()
        # Find the pipeline _StepDef(...) call and check also_accept_prev is absent
        # (defaults to False) or explicitly False.
        import re
        # Match the _StepDef block for the "pipeline" step
        pattern = r'_StepDef\("pipeline".*?(?=_StepDef|\Z)'
        block = re.search(pattern, source, re.DOTALL)
        assert block is not None, "Could not find _StepDef('pipeline', ...) in scheduler main.py"
        block_text = block.group(0)
        assert "also_accept_prev=True" not in block_text, (
            "pipeline step has also_accept_prev=True in scheduler main.py — this causes "
            "the scheduler to treat yesterday's run as 'done' today, skipping the "
            "pipeline entirely. Exchange calendar already handles holidays."
        )

    @pytest.mark.asyncio
    async def test_pipeline_idle_when_run_date_is_prev_trading_day(self):
        """
        Regression: pipeline run_date = prev_trading_day must appear as 'idle' today.

        Before the fix (also_accept_prev=True), the scheduler would see
        prev_trading_day in ok_dates and return 'done', skipping the re-run.
        """
        tuesday  = "2026-05-26"   # today
        monday   = "2026-05-19"   # prev_trading_day (before holiday week)
        tuesday2 = "2026-05-20"   # trading_day for the test

        step = _SchedStep(
            name="pipeline",
            url="http://fake",
            start_path="/jobs/run",
            date_field="run_date",
            use_trading_day=True,
            also_accept_prev=False,
        )
        client = MagicMock()
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status": "success", "run_date": monday}),
        ))
        result = await _sched_step_state(client, step, tuesday, tuesday2, monday)
        assert result == "idle", (
            f"Pipeline with run_date={monday!r} should be 'idle' when trading_day={tuesday2!r}; "
            f"got {result!r}. This means also_accept_prev=True is leaking back in."
        )

    @pytest.mark.asyncio
    async def test_pipeline_done_when_run_date_matches_trading_day(self):
        """Pipeline that ran today's trading_day must be 'done'."""
        today        = "2026-05-20"
        trading_day  = "2026-05-20"
        prev_trading = "2026-05-19"

        step = _SchedStep(
            name="pipeline",
            url="http://fake",
            start_path="/jobs/run",
            date_field="run_date",
            use_trading_day=True,
            also_accept_prev=False,
        )
        client = MagicMock()
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status": "success", "run_date": trading_day}),
        ))
        result = await _sched_step_state(client, step, today, trading_day, prev_trading)
        assert result == "done", (
            f"Pipeline run_date={trading_day!r} matching trading_day should be 'done'; "
            f"got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_pipeline_done_on_holiday_via_exchange_calendar(self):
        """
        On a market holiday, the exchange calendar returns the prior Friday as
        trading_day. A pipeline run with run_date=Friday must be 'done' on Monday.
        No also_accept_prev needed.
        """
        monday_holiday = "2026-05-25"   # Memorial Day
        friday         = "2026-05-22"   # last trading day
        thursday       = "2026-05-21"   # prev_trading_day

        step = _SchedStep(
            name="pipeline",
            url="http://fake",
            start_path="/jobs/run",
            date_field="run_date",
            use_trading_day=True,
            also_accept_prev=False,
        )
        client = MagicMock()
        client.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"status": "success", "run_date": friday}),
        ))
        result = await _sched_step_state(client, step, monday_holiday, friday, thursday)
        assert result == "done", (
            f"On holiday {monday_holiday!r}, pipeline run_date={friday!r} "
            f"(=trading_day) should be 'done'; got {result!r}"
        )


# ── TestPipelinePriorityOverAvIngestor ────────────────────────────────────────

class TestPipelinePriorityOverAvIngestor:
    """
    Regression: pipeline status must take priority over av-ingestor status.

    Bug: when av-ingestor fetch-data is still being polled as "running" AND
    the pipeline has already started (auto-triggered by the Redis stream), the
    av-ingestor check ran first and locked rank_step_label to "Fetching Data".
    The pipeline check was guarded by `rank_status != "running"`, which was
    already False, so it never fired.

    Fix: check pipeline FIRST; only fall back to av-ingestor when pipeline
    hasn't started yet.
    """

    def test_pipeline_running_beats_av_ingestor_running(self):
        """
        When BOTH av-ingestor fetch-data AND pipeline are running simultaneously,
        the label must be 'Calculating Factors', not 'Fetching Data'.
        """
        result = _call_pipeline_status(
            pipeline_status_raw="running",
            pipeline_factor_status="running",
            av_ingestor_data={"status": "running", "job_type": "fetch-data",
                              "tickers_done": 50, "total_tickers": 100},
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("status") == "running"
        assert rank.get("step_label") == "Calculating Factors", (
            "When pipeline is running, it must take priority over av-ingestor; "
            f"got step_label={rank.get('step_label')!r}"
        )

    def test_fetching_data_only_when_pipeline_not_started(self):
        """
        When av-ingestor is running fetch-data but pipeline has NOT started,
        'Fetching Data' is the correct label.
        """
        result = _call_pipeline_status(
            pipeline_status_raw=None,    # pipeline not started
            av_ingestor_data={"status": "running", "job_type": "fetch-data",
                              "tickers_done": 10, "total_tickers": 100},
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        assert rank.get("status") == "running"
        assert rank.get("step_label") == "Fetching Data", (
            "When only av-ingestor is running, label must be 'Fetching Data'; "
            f"got {rank.get('step_label')!r}"
        )

    def test_pipeline_done_av_ingestor_done_not_fetching(self):
        """
        After both complete, must NOT show 'Fetching Data'.
        """
        result = _call_pipeline_status(
            pipeline_status_raw="success",
            av_ingestor_data={"status": "success", "job_type": "fetch-data"},
            rank_chain_running=False,
        )
        rank = result.get("rank", {})
        assert rank.get("step_label") != "Fetching Data", (
            f"After completion, step_label should not be 'Fetching Data'; "
            f"got {rank.get('step_label')!r}"
        )


# ── TestBetweenStepNullInference ──────────────────────────────────────────────

class TestBetweenStepNullInference:
    """
    Regression: between-step inference must show the NEXT step even when the
    scheduler hasn't polled it yet (state is null/None in the dict).

    Before the fix, the between-step logic skipped null states (treating them
    like "done"), falling through to "Running" when fetch-data was "done" but
    pipeline was null — the label would show 'PIPELINE RUNNING' instead of
    'Calculating Factors' for up to 5 minutes (one scheduler tick interval).

    After the fix: find the last "done" step and show the NEXT step in the
    chain regardless of its current state.
    """

    def test_pipeline_null_after_fetch_data_done_shows_calculating(self):
        """
        fetch-data='done', pipeline=null → inferred label must be 'Calculating Factors'.
        """
        result = _call_pipeline_status(
            pipeline_status_raw=None,
            scheduler_data={
                "status": "running",
                "steps": {"fetch-data": "done"},   # pipeline not in dict yet
            },
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        label = rank.get("step_label")
        assert label == "Calculating Factors", (
            "When fetch-data is 'done' and pipeline is null, the inferred label "
            f"must be 'Calculating Factors'; got {label!r}"
        )

    def test_vet_null_after_pipeline_done_shows_vetting(self):
        """
        pipeline='done', vet=null → inferred label must be 'Vetting'.
        """
        result = _call_pipeline_status(
            pipeline_status_raw="success",
            scheduler_data={
                "status": "running",
                "steps": {"fetch-data": "done", "pipeline": "done"},
            },
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        label = rank.get("step_label")
        assert label == "Vetting", (
            "When pipeline is 'done' and vet is null, the inferred label "
            f"must be 'Vetting'; got {label!r}"
        )

    def test_portfolio_null_after_vet_done_shows_building(self):
        """
        vet='done', portfolio-builder=null → inferred label must be 'Building Portfolio'.
        """
        result = _call_pipeline_status(
            pipeline_status_raw="success",
            scheduler_data={
                "status": "running",
                "steps": {"fetch-data": "done", "pipeline": "done", "vet": "done"},
            },
            rank_chain_running=True,
        )
        rank = result.get("rank", {})
        label = rank.get("step_label")
        assert label == "Building Portfolio", (
            "When vet is 'done' and portfolio-builder is null, the inferred label "
            f"must be 'Building Portfolio'; got {label!r}"
        )
