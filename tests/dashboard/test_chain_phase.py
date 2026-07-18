"""Exhaustive tests for derive_scheduler_phase — the single authoritative mapping
from the scheduler's chain state to the UI panels.

Each test pins one of the symptoms from the "scheduler is the single FRESH source"
redesign:
  - delta running ⇒ rank shows "Delta Eval" running (not stale, not "Evaluating Signals")
  - vet running ⇒ vetter running (label "Vetter", never "LLM ANALYSIS")
  - fetch-data running ⇒ fetch % IS computed from av-ingestor progress (the gap the
    old override dropped)
  - vet/portfolio phases ⇒ rank reads success (pipeline done), countdown not blocked
  - per-step done/running follows the scheduler step map exactly
"""
import re
from pathlib import Path

from app.chain_phase import derive_scheduler_phase, SCHED_LABEL_MAP

_MAIN_SRC = (Path(__file__).resolve().parents[2]
             / "services" / "dashboard" / "app" / "main.py").read_text()


def test_confirmed_terminal_suppressed_while_any_chain_is_running():
    """Audit finding D3: at the first polls of a CRON chain the scheduler is
    running but its steps map is empty (authoritative override skipped) while
    pipeline /runs/latest still shows the PRIOR run's success — the bar briefly
    claimed the previous cycle was complete. confirmed_terminal must require
    BOTH supervisors idle (dashboard run-now AND scheduler cron)."""
    m = re.search(r"confirmed_terminal = \((.*?)\n    \)", _MAIN_SRC, re.S)
    assert m, "confirmed_terminal assignment not found"
    cond = m.group(1)
    assert "not _rank_chain_running" in cond
    assert "not scheduler_chain_running" in cond


def _steps(**kw):
    return kw


# ── fetch-data: the % fix ─────────────────────────────────────────────────────

def test_fetch_data_computes_percent_from_av_progress():
    p = derive_scheduler_phase(
        steps=_steps(**{"fetch-data": "running"}),
        current_step="fetch-data",
        av_tickers_done=4346, av_total_tickers=6495,
    )
    assert p["rank_status"] == "running"
    assert p["rank_step_label"] == "Fetching Data"
    assert p["rank_pct"] == 67   # round(4346/6495*100)


def test_fetch_data_no_total_yields_no_percent_not_crash():
    p = derive_scheduler_phase(
        steps=_steps(**{"fetch-data": "running"}),
        current_step="fetch-data",
        av_tickers_done=None, av_total_tickers=None,
    )
    assert p["rank_status"] == "running"
    assert p["rank_pct"] is None


# ── delta: relabel + running ──────────────────────────────────────────────────

def test_standalone_delta_step_is_delta_eval_running():
    p = derive_scheduler_phase(
        steps=_steps(**{"fetch-data": "done", "pipeline": "done", "vet": "done",
                        "portfolio-builder": "done", "delta": "running"}),
        current_step="delta",
        rank_date="2026-06-01",
    )
    assert p["rank_status"] == "running"
    assert p["rank_step_label"] == "Delta Eval"
    assert p["rank_step"] == "delta"


def test_pipeline_substep_delta_is_delta_eval():
    p = derive_scheduler_phase(
        steps=_steps(**{"fetch-data": "done", "pipeline": "running"}),
        current_step="pipeline",
        pipeline_delta_status="running",
        pipeline_live_step="delta", pipeline_live_pct=42,
    )
    assert p["rank_step_label"] == "Delta Eval"
    assert p["rank_pct"] == 42


def test_no_old_evaluating_signals_label_anywhere():
    # The string "Evaluating Signals" must not appear in any produced label.
    for cur, extra in [("delta", {}), ("pipeline", {"pipeline_delta_status": "running"})]:
        p = derive_scheduler_phase(steps={"pipeline": "running"}, current_step=cur, **extra)
        assert p["rank_step_label"] != "Evaluating Signals"


# ── pipeline sub-steps ────────────────────────────────────────────────────────

def test_pipeline_ranking_substep():
    p = derive_scheduler_phase(
        steps=_steps(**{"pipeline": "running"}), current_step="pipeline",
        pipeline_rank_status="running", pipeline_live_step="ranking", pipeline_live_pct=88,
    )
    assert p["rank_step_label"] == "Ranking"
    assert p["rank_pct"] == 88


def test_pipeline_factors_substep_default():
    p = derive_scheduler_phase(
        steps=_steps(**{"pipeline": "running"}), current_step="pipeline",
        pipeline_live_step="calc_factors", pipeline_live_pct=10,
    )
    assert p["rank_step_label"] == "Calculating Factors"
    assert p["rank_pct"] == 10


# ── vet phase: label is "Vetter", and rank reads success ──────────────────────

def test_vet_phase_vetter_running_rank_success():
    p = derive_scheduler_phase(
        steps=_steps(**{"fetch-data": "done", "pipeline": "done", "vet": "running"}),
        current_step="vet",
        rank_date="2026-06-01",
    )
    assert p["vetter_status"] == "running"
    assert p["rank_status"] == "success"   # pipeline produced rankings; rank not "running"
    assert p["portfolio_status"] == "none"


def test_vet_label_is_vetter_not_llm():
    assert SCHED_LABEL_MAP["vet"] == "Vetter"
    assert SCHED_LABEL_MAP["delta"] == "Delta Eval"
    assert "LLM" not in SCHED_LABEL_MAP["vet"]


# ── portfolio-builder phase ───────────────────────────────────────────────────

def test_portfolio_phase_running():
    p = derive_scheduler_phase(
        steps=_steps(**{"fetch-data": "done", "pipeline": "done", "vet": "done",
                        "portfolio-builder": "running"}),
        current_step="portfolio-builder",
        rank_date="2026-06-01",
    )
    assert p["portfolio_status"] == "running"
    assert p["vetter_status"] == "success"   # vet marked done
    assert p["rank_status"] == "success"


# ── step map followed exactly (no stale prior-run leakage) ────────────────────

def test_done_steps_report_success_running_only_for_current():
    steps = {"fetch-data": "done", "pipeline": "done", "vet": "done",
             "portfolio-builder": "done", "delta": "running"}
    p = derive_scheduler_phase(steps=steps, current_step="delta", rank_date="2026-06-01")
    assert p["vetter_status"] == "success"
    assert p["portfolio_status"] == "success"
    assert p["rank_status"] == "running"   # delta is rank-owned


def test_fetch_running_vet_not_yet_seen_is_none_not_success():
    # Early chain: only fetch-data running; vet/portfolio not yet in the map.
    p = derive_scheduler_phase(
        steps=_steps(**{"fetch-data": "running"}), current_step="fetch-data",
        av_tickers_done=1, av_total_tickers=100,
    )
    assert p["vetter_status"] == "none"
    assert p["portfolio_status"] == "none"
