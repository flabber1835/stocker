"""Health-record invariants (pure) + per-step trace-file gating.

The consolidated per-run blob carries computed invariant checks so an LLM/operator
can verify health without re-deriving math. These tests pin the bug-class detectors
(config skew, count non-reconciliation, capacity overflow, all-null factor, restart
orphan, step failure) and that the legacy per-step files are OFF by default.
"""
import os

import pytest

from stock_strategy_shared.health_record import compute_invariants


def _healthy_chain():
    h = "cfg123"
    return {
        "ingest":    {"status": "success"},
        "factor":    {"status": "success", "config_hash": h, "error_message": None},
        "ranking":   {"status": "success", "config_hash": h, "universe_count": 100,
                      "ranked_count": 90, "dropped_count": 10, "error_message": None},
        "vetter":    {"status": "success"},
        "portfolio": {"status": "success", "config_hash": h, "selected_count": 30},
        "delta":     {"status": "success", "config_hash": h, "max_positions": 35},
    }


def _by_check(inv):
    return {i["check"]: i for i in inv}


def test_healthy_run_all_invariants_pass():
    inv = compute_invariants(_healthy_chain(),
                             coverage={"momentum": 0.02, "quality": 0.10},
                             rank_stats={"composite_min": 0.0, "composite_max": 1.0})
    assert all(i["pass"] for i in inv), [i for i in inv if not i["pass"]]


def test_config_skew_detected():
    c = _healthy_chain(); c["portfolio"]["config_hash"] = "DIFFERENT"
    inv = _by_check(compute_invariants(c, {}, {}))
    assert inv["config_hash_consistent"]["pass"] is False


def test_count_non_reconciliation_detected():
    c = _healthy_chain(); c["ranking"]["ranked_count"] = 80   # 80 != 100 - 10
    inv = _by_check(compute_invariants(c, {}, {}))
    assert inv["rank_count_reconciles"]["pass"] is False


def test_capacity_overflow_detected():
    c = _healthy_chain(); c["portfolio"]["selected_count"] = 40   # > max 35
    inv = _by_check(compute_invariants(c, {}, {}))
    assert inv["selected_within_cap"]["pass"] is False


def test_all_null_factor_flagged():
    inv = _by_check(compute_invariants(_healthy_chain(),
                                       coverage={"momentum": 0.99}, rank_stats={}))
    chk = inv["factor_coverage_momentum"]
    assert chk["pass"] is False and chk["severity"] == "warn"


def test_restart_orphan_in_success_chain_flagged():
    c = _healthy_chain()
    c["factor"]["error_message"] = "RESTART_ABORTED: container restarted mid-run"
    inv = _by_check(compute_invariants(c, {}, {}))
    assert inv["factor_no_restart_abort"]["pass"] is False


def test_failed_step_detected():
    c = _healthy_chain(); c["delta"]["status"] = "failed"
    inv = _by_check(compute_invariants(c, {}, {}))
    assert inv["delta_status_success"]["pass"] is False


def test_missing_steps_are_skipped_not_failed():
    # a chain with no vetter row (e.g. cold start) must not invent a failure for it
    c = _healthy_chain(); c["vetter"] = None
    inv = _by_check(compute_invariants(c, {}, {}))
    assert "vetter_status_success" not in inv


# ── per-step trace files OFF by default ────────────────────────────────────────
@pytest.mark.asyncio
async def test_step_trace_files_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("WRITE_STEP_TRACE_FILES", raising=False)
    from stock_strategy_shared import tracing
    from datetime import datetime, timezone
    # flag off → early return before touching the engine; no traces/ dir created
    await tracing.write_trace_file(None, str(tmp_path), "tid", "rid", "job", "success",
                                   datetime.now(timezone.utc), "svc")
    assert not (tmp_path / "traces").exists()
