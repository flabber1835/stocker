"""Regression test: the pipeline step label must not flip-flop Factors<->Ranking.

Bug: the pipeline writes factor_status/ranking_status (Postgres columns) and the
live /runs/progress step at slightly different moments. During the factors->ranking
handoff a single poll can observe BOTH factor_status="running" and
ranking_status="running". Factors-first precedence then re-painted "Calculating
Factors" on that poll, so across polls the label alternated Factors<->Ranking.

Fix (coherence guard): steps only advance (factors -> ranking -> delta), so when
several sub-statuses read "running" the FURTHEST-ALONG one is the true state. Check
delta, then ranking, then factors.
"""
import asyncio
import os
import sys
import unittest.mock as mock

import pytest
import httpx  # noqa: F401 (import parity with sibling tests)

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


def _pipeline(factor, ranking, delta=None, live_step=None, live_pct=None) -> _Resp:
    return _Resp({
        "status": "running",
        "factor_status": factor,
        "ranking_status": ranking,
        "delta_status": delta,
        "completed_at": None,
    })


def _progress(step=None, pct=None) -> _Resp:
    return _Resp({"step": step, "pct": pct})


def _call(pipeline_resp, progress_resp=None) -> dict:
    import app.main as dash
    dash._rank_chain_running = False
    progress_resp = progress_resp or _empty()

    async def fake_gather(*coros):
        return [
            _empty(),         # r0 universe
            _empty(),         # r1 rankings
            _empty(),         # r3 portfolio
            _empty(),         # sys_status
            pipeline_resp,    # r4 pipeline /runs/latest
            _empty(),         # r5 av-ingestor
            _Resp({"status": "idle", "steps": {}}),  # r7 scheduler
            progress_resp,    # r8 pipeline /runs/progress
        ]

    async def _run():
        with mock.patch("asyncio.gather", side_effect=fake_gather):
            return await dash.pipeline_status()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def test_both_factor_and_ranking_running_shows_ranking():
    """The handoff race: both columns running -> furthest-along (Ranking) wins."""
    result = _call(_pipeline(factor="running", ranking="running"))
    assert result["rank"]["step_label"] == "Ranking", \
        f"expected Ranking when both running, got {result['rank']['step_label']!r}"


def test_only_factors_running_shows_factors():
    result = _call(_pipeline(factor="running", ranking=None))
    assert result["rank"]["step_label"] == "Calculating Factors"


def test_only_ranking_running_shows_ranking():
    result = _call(_pipeline(factor="done", ranking="running"))
    assert result["rank"]["step_label"] == "Ranking"


def test_ranking_and_delta_running_shows_delta():
    result = _call(_pipeline(factor="done", ranking="running", delta="running"))
    assert result["rank"]["step_label"] == "Delta Eval"


def test_pct_attached_to_matching_live_step():
    """pct only attaches when the live progress step matches the chosen label."""
    result = _call(
        _pipeline(factor="running", ranking="running"),
        _progress(step="ranking", pct=42),
    )
    assert result["rank"]["step_label"] == "Ranking"
    assert result["rank"]["pct"] == 42


def test_ranking_success_but_run_not_terminal_stays_ranking():
    """Window (2): the pipeline commits ranking_status='success' BEFORE the run's
    status flips to 'success' (separate transactions). A poll then sees status=
    'running' with BOTH sub-statuses 'success' and NEITHER 'running'. The label must
    NOT regress to 'Calculating Factors' — it should stay 'Ranking' until terminal.
    This is the residual flip-flop the monotonic guard fixes."""
    result = _call(_pipeline(factor="success", ranking="success"))
    assert result["rank"]["step_label"] == "Ranking", (
        "ranking-done→terminal window must stay Ranking, not flip back to Factors; "
        f"got {result['rank']['step_label']!r}"
    )


def test_factors_success_ranking_not_started_shows_factors():
    """Symmetric check: factors done but ranking not yet recorded → still Factors
    (we've reached factors, not ranking). Monotonic, no false jump to Ranking."""
    result = _call(_pipeline(factor="success", ranking=None))
    assert result["rank"]["step_label"] == "Calculating Factors"
