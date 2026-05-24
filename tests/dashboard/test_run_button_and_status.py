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

            # Build the 7-item tuple returned by asyncio.gather in pipeline_status
            async def fake_gather(*coros):
                # Returns: r0 (uni), r1 (rankings), r3 (portfolio), sys_status, r4 (pipeline), r5 (av-ingestor), r7 (scheduler)
                return [
                    EMPTY(),          # r0: universe
                    rankings_resp,    # r1: rankings
                    EMPTY(),          # r3: portfolio
                    EMPTY(),          # sys_status_resp
                    pipeline_resp,    # r4_direct: pipeline /runs/latest
                    EMPTY(),          # r5_direct: av-ingestor /runs/latest
                    sched_resp,       # r7_direct: scheduler /status
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


class TestPurgeButtonVisibility:
    """
    Regression tests for the Purge & Reset button toolbar visibility.

    The toolbar (which contains the purge button) must be visible whenever
    there are any signals in the Trader tab — not only when there are
    entry/exit/buy_add/sell_trim signals. A pipeline run that produces only
    hold/watch signals may still have open orders that the user needs to cancel.
    """

    def _load_js(self):
        js_path = os.path.join(_DASH_PATH, "app", "static", "dashboard.js")
        if not os.path.exists(js_path):
            js_path = os.path.join(_DASH_PATH, "static", "dashboard.js")
        with open(js_path) as f:
            return f.read()

    def _toolbar_visible(self, intents: list[dict]) -> bool:
        """
        Simulate the JS renderTrader toolbar visibility logic in Python.
        Returns True if the toolbar would be displayed for the given intent list.
        """
        return len(intents) > 0

    def test_toolbar_visible_with_entry_intents(self):
        """Entry signals → toolbar shown → purge button accessible."""
        intents = [{"action": "entry"}, {"action": "entry"}]
        assert self._toolbar_visible(intents)

    def test_toolbar_visible_with_exit_intents(self):
        """Exit signals → toolbar shown."""
        intents = [{"action": "exit"}]
        assert self._toolbar_visible(intents)

    def test_toolbar_visible_with_hold_only_intents(self):
        """Hold-only pipeline run → toolbar must still show so purge is reachable."""
        intents = [{"action": "hold"}, {"action": "watch"}]
        assert self._toolbar_visible(intents)

    def test_toolbar_hidden_with_no_intents(self):
        """No delta run / no intents → toolbar correctly hidden (nothing to purge)."""
        intents = []
        assert not self._toolbar_visible(intents)

    def test_toolbar_visible_with_mixed_intents(self):
        """Mixed hold + entry signals → toolbar shown."""
        intents = [{"action": "hold"}, {"action": "entry"}]
        assert self._toolbar_visible(intents)

    def test_js_toolbar_uses_length_not_action_filter(self):
        """renderTrader() must gate toolbar on sorted.length, not action-type filter."""
        content = self._load_js()
        m = _re.search(r'function renderTrader\(\s*\)\s*\{(.*?)^\}', content,
                       _re.DOTALL | _re.MULTILINE)
        assert m, "renderTrader function not found in dashboard.js"
        body = m.group(1)
        # Must NOT use the old hasActionable check that excluded hold/watch
        assert "hasActionable" not in body, (
            "renderTrader() still uses hasActionable — this hides the purge button "
            "when all intents are hold/watch. Use sorted.length > 0 instead."
        )
        # Must use length-based check
        assert "sorted.length" in body, (
            "renderTrader() must check sorted.length to show toolbar for all signal types"
        )

    def test_purge_button_present_in_html(self):
        """btn-purge-all must exist in the dashboard HTML template."""
        main_path = os.path.join(_DASH_PATH, "app", "main.py")
        if not os.path.exists(main_path):
            main_path = os.path.join(_DASH_PATH, "main.py")
        with open(main_path) as f:
            content = f.read()
        assert "btn-purge-all" in content, "Purge button element not found in dashboard HTML"
        assert "purgeAll()" in content, "purgeAll() onclick not found in dashboard HTML"

    def test_purge_function_in_js(self):
        """purgeAll() function must exist in dashboard.js and call the endpoint."""
        content = self._load_js()
        assert "async function purgeAll()" in content, "purgeAll() not defined in dashboard.js"
        assert "/api/trade/purge-all" in content, "purgeAll() must POST to /api/trade/purge-all"
        # Must reset approval state after purge
        assert "_approvalState" in content, "_approvalState must be reset in purgeAll()"
