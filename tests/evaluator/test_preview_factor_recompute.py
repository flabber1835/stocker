"""`preview_factor_recompute` — the tool that closed the `factor_construction` gap.

Before it, every cheap path the evaluator had (preview_ranking, config_replay)
RE-WEIGHTED factor scores that were already persisted. A change to how a factor is
COMPUTED therefore scored identically to the active config in both — silently,
with no error — and the only real evaluation was a multi-hour wind-tunnel run.

The tests that matter here are the ones about HONESTY of the answer rather than
its plumbing: that a contaminated baseline is surfaced rather than swallowed, that
a diff which doesn't touch factor_engine is called out as the waste it is, and
that a refusal from the pipeline reaches the model intact instead of becoming an
empty result it would read as "no effect".
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

import app.tools as t
from app.tools import BacktestBudget

STRAT = os.path.join(os.path.dirname(__file__), "..", "..",
                     "strategies", "quality_core_v1.yaml")


@pytest.fixture(autouse=True)
def _active_config(monkeypatch):
    monkeypatch.setattr(t, "STRATEGY_CONFIG_PATH", STRAT)


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class _Client:
    """Stand-in httpx.AsyncClient capturing the POST and returning a canned reply."""

    def __init__(self, resp, sink=None, boom=None):
        self._resp, self._sink, self._boom = resp, sink, boom

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **kw):
        if self._boom:
            raise self._boom
        if self._sink is not None:
            self._sink["url"] = url
            self._sink["body"] = json
        return self._resp


def _patch_http(monkeypatch, resp, sink=None, boom=None):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: _Client(resp, sink, boom))


def _payload(**over):
    base = {
        "score_date": "2026-07-31",
        "regime": "bull_calm",
        "n_tickers": 1800,
        "factor_engine_changed": True,
        "baseline_fidelity": 0.999,
        "active_ranking": [{"ticker": f"T{i:03d}", "rank": i + 1,
                            "composite_score": 1.0 - i / 100} for i in range(40)],
        "candidate_ranking": [{"ticker": f"T{i:03d}", "rank": 40 - i,
                               "composite_score": i / 100} for i in range(40)],
        "factor_coverage": {"momentum": {"active_non_null": 1800,
                                         "candidate_non_null": 1800}},
        "factor_rank_correlation": {"momentum": 0.61},
    }
    base.update(over)
    return base


def _run(args, monkeypatch, resp, budget=None, sink=None, boom=None):
    _patch_http(monkeypatch, resp, sink, boom)
    b = budget or BacktestBudget()
    return asyncio.run(t.preview_factor_recompute(args, budget=b)), b


# ── the answer it gives ───────────────────────────────────────────────────────

def test_it_returns_a_rank_diff_in_preview_rankings_shape(monkeypatch):
    """The evaluator asked for "the same output shape as preview_ranking" so it
    can read one format for both triage tools."""
    out, _ = _run({"config_changes": {"factor_engine.momentum_method": "residual_tstat"}},
                  monkeypatch, _Resp(200, _payload()))
    d = json.loads(out)
    for k in ("entered_top_n", "left_top_n", "biggest_movers", "rank_correlation",
              "membership_change_count", "top_n"):
        assert k in d, k
    assert d["score_date"] == "2026-07-31"
    assert d["factor_coverage"]["momentum"]["candidate_non_null"] == 1800


def test_the_whole_config_is_posted_not_the_diff(monkeypatch):
    """The pipeline validates a WHOLE StrategyConfig; sending the {path: value}
    diff would 400 on the far side."""
    sink = {}
    _run({"config_changes": {"factor_engine.volatility_window": 126}},
         monkeypatch, _Resp(200, _payload()), sink=sink)
    body = sink["body"]["config"]
    assert body["factor_engine"]["volatility_window"] == 126
    assert "strategy_id" in body and "portfolio_builder" in body


# ── honesty ───────────────────────────────────────────────────────────────────

def test_a_drifted_baseline_is_reported_as_contamination(monkeypatch):
    """The active side is RECOMPUTED, not read from `rankings`. If that recompute
    disagrees with what the chain actually persisted for the same date, every
    conclusion drawn off it is contaminated — and the model must be told, because
    the diff itself looks perfectly ordinary."""
    out, _ = _run({"config_changes": {"factor_engine.pe_pb_cap": 80}},
                  monkeypatch, _Resp(200, _payload(baseline_fidelity=0.71)))
    notes = " ".join(json.loads(out)["notes"])
    assert "contaminated" in notes and "0.71" in notes


def test_a_clean_baseline_carries_no_contamination_warning(monkeypatch):
    out, _ = _run({"config_changes": {"factor_engine.pe_pb_cap": 80}},
                  monkeypatch, _Resp(200, _payload(baseline_fidelity=0.999)))
    assert "contaminated" not in " ".join(json.loads(out)["notes"])


def test_a_weight_only_diff_is_called_out_as_waste(monkeypatch):
    """This tool costs a universe-scale recompute. A diff that does not touch
    factor_engine gets the identical answer from preview_ranking in ~1s, so
    spending a slot on it silently is a budget leak."""
    out, _ = _run({"config_changes": {"min_score_percentile": 0.05}},
                  monkeypatch, _Resp(200, _payload(factor_engine_changed=False)))
    assert "preview_ranking" in " ".join(json.loads(out)["notes"])


def test_it_never_claims_to_measure_returns(monkeypatch):
    """One date, no equity curve. This is why it registers no backtest_trial: a
    rank diff is not a performance estimate and must not deflate anyone's DSR."""
    out, _ = _run({"config_changes": {"factor_engine.momentum_method": "residual"}},
                  monkeypatch, _Resp(200, _payload()))
    d = json.loads(out)
    notes = " ".join(d["notes"]).lower()
    assert "no returns" in notes
    for forbidden in ("cagr", "sharpe", "total_return", "dsr", "pbo"):
        assert forbidden not in d, f"{forbidden} must not appear — it measures none of it"


# ── refusals must reach the model intact ──────────────────────────────────────

def test_a_pipeline_refusal_is_relayed_not_swallowed(monkeypatch):
    """A 422 that came back as an empty result would read as "the change does
    nothing" — the most expensive possible misreading."""
    out, _ = _run({"config_changes": {"universe.min_price": 25.0}},
                  monkeypatch,
                  _Resp(422, {"detail": "cannot model a `universe.*` change; "
                                        "score it in the wind tunnel"}))
    assert out.startswith("preview refused (HTTP 422)")
    assert "wind tunnel" in out


def test_an_unreachable_pipeline_is_an_error_not_an_empty_diff(monkeypatch):
    out, _ = _run({"config_changes": {"factor_engine.pe_pb_cap": 80}},
                  monkeypatch, _Resp(200, _payload()),
                  boom=RuntimeError("connect timeout"))
    assert out.startswith("error: could not reach the pipeline")


def test_an_invalid_candidate_config_refunds_the_slot(monkeypatch):
    """The recompute never ran, so charging for it would burn a scarce budget on
    a typo."""
    b = BacktestBudget()
    out, b = _run({"config_changes": {"factor_engine.momentum_method": "not_a_method"}},
                  monkeypatch, _Resp(200, _payload()), budget=b)
    assert "INVALID" in out
    assert b.factor_preview_used == 0


# ── budget ────────────────────────────────────────────────────────────────────

def test_the_budget_is_separate_from_preview_ranking_and_exhausts(monkeypatch):
    b = BacktestBudget()
    b.factor_preview_limit = 2
    args = {"config_changes": {"factor_engine.pe_pb_cap": 80}}
    for _ in range(2):
        out, b = _run(args, monkeypatch, _Resp(200, _payload()), budget=b)
        assert not out.startswith("FACTOR-PREVIEW BUDGET")
    out, b = _run(args, monkeypatch, _Resp(200, _payload()), budget=b)
    assert out.startswith("FACTOR-PREVIEW BUDGET EXHAUSTED")
    assert b.preview_used == 0, "it must not consume preview_ranking's budget"


def test_default_budget_sits_between_backtests_and_rank_previews():
    """Equal to MAX_BACKTESTS would defeat the purpose (a triage budget as scarce
    as the thing it saves buys nothing); equal to MAX_PREVIEWS would ignore that
    this one costs a universe-scale recompute."""
    b = BacktestBudget()
    assert b.limit < b.factor_preview_limit < b.preview_limit


def test_it_is_dispatched(monkeypatch):
    _patch_http(monkeypatch, _Resp(200, _payload()))
    out = asyncio.run(t.execute_tool("preview_factor_recompute",
                                     {"config_changes": {"factor_engine.pe_pb_cap": 80}},
                                     engine=None, budget=BacktestBudget()))
    assert "biggest_movers" in out
