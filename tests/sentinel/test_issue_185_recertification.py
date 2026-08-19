"""The #185 economic comparator must not turn unlike runs into a delta report."""
from __future__ import annotations

import copy

import pytest

from tools import wealth_core_liquidity_recertification as recert


def _env(run_id: str, *, equities=(100.0, 101.0, 99.0), shares=10):
    sessions = []
    for i, equity in enumerate(equities, 1):
        sessions.append({
            "session": f"2026-01-0{i}",
            "resolved_equity": equity,
            "intents": ([] if i != 2 else [{
                "security_id": "P:1", "ticker": "AAA",
                "operation": "OPEN_POSITION", "shares": shares,
            }]),
        })
    perf = {
        "ending_equity": equities[-1],
        "ending_wealth_multiple": equities[-1] / 100.0,
        "total_return": equities[-1] / 100.0 - 1.0,
        "cagr": 0.1,
        "maximum_drawdown": -0.02,
        "trade_count": 1,
        "gross_traded_notional": 1000.0,
        "gross_turnover": 1.0,
        "annualized_turnover": 10.0,
        "benchmark_cagr": 0.05,
        "excess_cagr": 0.05,
    }
    return {
        "schema": recert.ENVELOPE_SCHEMA,
        "run_id": run_id,
        "status": "success",
        "mode": "chain_rehearsal",
        "spec": {
            "start_date": "2026-01-01", "end_date": "2026-01-03",
            "starting_cash": 100.0, "config": {}, "eligibility": {},
            "change": {}, "retention_mode": "full",
        },
        "parity_hashes": {"normalized_input": run_id,
                          "final_state": run_id + "-final"},
        "summary": {
            "sessions": sessions,
            "performance": perf,
            "book_artifact": {"window": {"start": "2026-01-01",
                                            "end": "2026-01-03"},
                              "held": [{"security_id": "P:1", "shares": shares}],
                              "pending_terminal": []},
        },
    }


def test_identical_economics_and_results_compare_cleanly():
    before = _env("old")
    after = _env("new")
    # Parity hashes are expected to differ when the input domain changes; make
    # the strategy result itself identical so those two concepts stay separate.
    report = recert.compare(before, after)
    assert report["trade_intents"]["identical"] is True
    assert report["final_book"]["identical"] is True
    assert report["performance"]["cagr"]["delta"] == 0
    assert report["sharpe"]["delta"] == 0
    assert report["parity"]["changed_layers"] == ["final_state", "normalized_input"]


def test_share_change_is_reported_as_trade_and_book_difference():
    before = _env("old", shares=10)
    after = _env("new", shares=11)
    report = recert.compare(before, after)
    assert report["trade_intents"]["identical"] is False
    assert report["trade_intents"]["removed_count"] == 1
    assert report["trade_intents"]["added_count"] == 1
    assert report["final_book"]["identical"] is False


def test_different_strategy_economics_are_refused():
    before = _env("old")
    after = _env("new")
    after["spec"]["eligibility"] = {"min_adv20_dollars": 99}
    with pytest.raises(ValueError, match="identical economic specs"):
        recert.compare(before, after)


def test_missing_equity_refuses_sharpe_instead_of_interpolating():
    before = _env("old")
    after = _env("new")
    after["summary"]["sessions"][1]["resolved_equity"] = None
    with pytest.raises(ValueError, match="no resolved_equity"):
        recert.compare(before, after)


def test_retained_session_series_is_required_for_sharpe_and_trade_diff():
    before = _env("old")
    after = _env("new")
    del after["summary"]["sessions"]
    with pytest.raises(ValueError, match="summary.sessions"):
        recert.compare(before, after)


def test_sharpe_uses_explicit_zero_rf_sample_stdev_convention():
    env = _env("run", equities=(101.0, 99.0, 102.0))
    value = recert._sharpe(env)
    assert value["value"] is not None
    assert value["convention"] == "simple-session-returns/sample-stdev/rf=0/sqrt252"
    assert value["observations"] == 3
