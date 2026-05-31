"""Regression test: stale vetter "running" must not flash "LLM ANALYSIS" at the
start of a fresh chain.

Bug: /api/pipeline-status reported vetter.status="running" straight from the
vetter's last-run row. At the start of a new chain that row is the PREVIOUS run
(possibly left non-terminal), so the status bar — which checks vetter before the
pipeline step — briefly painted "LLM ANALYSIS" while the chain was really on
fetch-data/factors.

Fix (scheduler-step-aware gate): when a chain is driving (scheduler chain running
or dashboard-supervised), only report vetter.status="running" once the scheduler's
"vet" step is actually running; otherwise suppress the stale value to "none".
When no chain is driving (manual /jobs/vet), the raw row is trusted as before.
"""
import asyncio
import os
import sys
import unittest.mock as mock

import pytest
import httpx

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

_DASH_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "dashboard")
)
for _k in list(sys.modules.keys()):
    if _k == "app" or _k.startswith("app."):
        del sys.modules[_k]
if _DASH_PATH not in sys.path:
    sys.path.insert(0, _DASH_PATH)


class _Resp:
    def __init__(self, data, code=200):
        self._data = data
        self.status_code = code

    def json(self):
        return self._data


def _empty():
    return _Resp({"error": "timeout"}, 503)


def _system_status_with_vetter(vetter_status: str) -> _Resp:
    # /system/status feeds r2 (vetter) and r6 (portfolio_builder) via _wrap().
    return _Resp({
        "vetter": {"status": vetter_status, "run_id": "v-prev",
                   "started_at": "2024-01-15T11:00:00Z"},
        "portfolio_builder": {"error": "unavailable"},
    })


def _scheduler(status: str, steps: dict) -> _Resp:
    return _Resp({"status": status, "steps": steps})


def _call_pipeline_status(*, sys_status, scheduler_resp, pipeline_resp=None,
                          rank_chain_running=False) -> dict:
    import app.main as dash
    dash._rank_chain_running = rank_chain_running
    pipeline_resp = pipeline_resp or _empty()

    async def fake_gather(*coros):
        return [
            _empty(),          # r0: universe
            _empty(),          # r1: rankings
            _empty(),          # r3: portfolio
            sys_status,        # sys_status_resp (feeds r2 vetter / r6)
            pipeline_resp,     # r4_direct: pipeline /runs/latest
            _empty(),          # r5_direct: av-ingestor
            scheduler_resp,    # r7_direct: scheduler /status
            _empty(),          # r8_direct: pipeline /runs/progress
        ]

    async def _run():
        with mock.patch("asyncio.gather", side_effect=fake_gather):
            return await dash.pipeline_status()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()
        dash._rank_chain_running = False


def test_stale_vetter_running_suppressed_before_vet_step():
    """Scheduler chain running, fetch-data in flight, stale vetter row = running →
    vetter.status must be suppressed (the flash bug)."""
    result = _call_pipeline_status(
        sys_status=_system_status_with_vetter("running"),
        scheduler_resp=_scheduler("running", {"fetch-data": "running", "vet": "idle"}),
    )
    assert result["vetter"]["status"] == "none", \
        f"stale vetter running should be suppressed pre-vet, got {result['vetter']['status']!r}"


def test_vetter_running_reported_when_vet_step_active():
    """Once the scheduler's vet step is actually running, report vetter running."""
    result = _call_pipeline_status(
        sys_status=_system_status_with_vetter("running"),
        scheduler_resp=_scheduler("running", {"pipeline": "done", "vet": "running"}),
    )
    assert result["vetter"]["status"] == "running"


def test_dashboard_supervised_chain_also_gates():
    """RUN button path: _rank_chain_running=True but scheduler not yet reporting
    'running' → stale vetter still suppressed."""
    result = _call_pipeline_status(
        sys_status=_system_status_with_vetter("running"),
        scheduler_resp=_scheduler("idle", {}),
        rank_chain_running=True,
    )
    assert result["vetter"]["status"] == "none"


def test_manual_vet_trusts_raw_when_no_chain_driving():
    """No chain driving (manual /jobs/vet): trust the raw running row."""
    result = _call_pipeline_status(
        sys_status=_system_status_with_vetter("running"),
        scheduler_resp=_scheduler("idle", {}),
        rank_chain_running=False,
    )
    assert result["vetter"]["status"] == "running"


def test_stale_vetter_success_suppressed_before_vet_step():
    """Scheduler-authoritative: a 'success' from the PREVIOUS chain's vetter run,
    while THIS chain is only on fetch-data (vet step idle), must read 'none' — not
    'success'. Showing success would be the same stale-row bug as the running flash.
    The vetter panel only reads success once the scheduler marks vet done."""
    result = _call_pipeline_status(
        sys_status=_system_status_with_vetter("success"),
        scheduler_resp=_scheduler("running", {"fetch-data": "running", "vet": "idle"}),
    )
    assert result["vetter"]["status"] == "none"


def test_vetter_success_when_scheduler_marks_vet_done():
    """Within the chain, once the scheduler marks vet 'done', vetter reads success."""
    result = _call_pipeline_status(
        sys_status=_system_status_with_vetter("success"),
        scheduler_resp=_scheduler("running",
                                  {"vet": "done", "portfolio-builder": "running"}),
    )
    assert result["vetter"]["status"] == "success"
