"""Pure mapping from the scheduler's authoritative chain state to UI fields.

The scheduler is the single source of truth for chain progress (see
docs/architecture.md "scheduler is the single, FRESH source of chain-progress
truth"). When it is reachable, /api/pipeline-status renders THIS mapping verbatim
instead of re-deriving phase from a blend of racing per-service rows.

Pure (no I/O) so every phase/label/percent rule is unit-testable in isolation —
which is where the symptom family (stale "Delta Eval", missing fetch %, wrong
vetter label) is pinned.
"""
from __future__ import annotations

from typing import Optional

STEP_ORDER = ["fetch-data", "pipeline", "vet", "portfolio-builder", "delta"]

# Labels shown for each phase. "Vetter" (not "LLM ANALYSIS"): the vet step runs
# even in drawdown-only mode with the LLM disabled, so an LLM label is misleading.
# "Delta Eval" (not "Evaluating Signals").
LABEL_FETCH = "Fetching Data"
LABEL_FACTORS = "Calculating Factors"
LABEL_RANKING = "Ranking"
LABEL_DELTA = "Delta Eval"
LABEL_VET = "Vetter"
LABEL_BUILD = "Building Portfolio"

SCHED_LABEL_MAP = {
    "fetch-data": LABEL_FETCH,
    "pipeline": LABEL_FACTORS,
    "vet": LABEL_VET,
    "portfolio-builder": LABEL_BUILD,
    "delta": LABEL_DELTA,
}


def derive_scheduler_phase(
    *,
    steps: dict,
    current_step: Optional[str],
    pipeline_factor_status: Optional[str] = None,
    pipeline_rank_status: Optional[str] = None,
    pipeline_delta_status: Optional[str] = None,
    pipeline_live_step: Optional[str] = None,
    pipeline_live_pct: Optional[int] = None,
    av_tickers_done: Optional[int] = None,
    av_total_tickers: Optional[int] = None,
    rank_date: Optional[str] = None,
) -> dict:
    """Map the scheduler's (fresh) step map + current step to the UI's rank/vetter/
    portfolio panels. `current_step` is the scheduler's authoritative current step
    (None when the chain isn't running — caller falls back to per-service inference).

    Returns rank_status/rank_step/rank_step_label/rank_pct + vetter_status +
    portfolio_status. The rank panel spans fetch-data, pipeline (factors/ranking),
    and the standalone delta step; vet and portfolio-builder follow the step map
    exactly so a stale prior-run row can never claim running/success early.
    """
    def _done(name: str) -> bool:
        return steps.get(name) == "done"

    rank_status: str
    rank_step = rank_step_label = None
    rank_pct = None
    cur = current_step

    if cur in ("fetch-data", "pipeline", "delta"):
        rank_status = "running"
        if cur == "fetch-data":
            rank_step, rank_step_label = "fetch_data", LABEL_FETCH
            # FIX: the prior override dropped the fetch %. Compute it from av-ingestor
            # progress so the bar fills during the (long) after-close fetch.
            if av_total_tickers and av_total_tickers > 0:
                rank_pct = round((av_tickers_done or 0) / av_total_tickers * 100)
        elif cur == "pipeline":
            # Zoom into the pipeline sub-step; monotonic (furthest-along wins).
            if pipeline_delta_status == "running":
                rank_step, rank_step_label = "delta", LABEL_DELTA
                rank_pct = pipeline_live_pct if pipeline_live_step == "delta" else None
            elif pipeline_rank_status == "running":
                rank_step, rank_step_label = "ranking", LABEL_RANKING
                rank_pct = pipeline_live_pct if pipeline_live_step == "ranking" else None
            else:
                rank_step, rank_step_label = "calc_factors", LABEL_FACTORS
                rank_pct = pipeline_live_pct if pipeline_live_step == "calc_factors" else None
        else:  # standalone delta step
            rank_step, rank_step_label = "delta", LABEL_DELTA
    else:
        # Chain is past the rank-owned phases (vet / portfolio-builder) or terminal:
        # pipeline produced today's rankings, so rank reads success. The frontend
        # renders these phases from vetter_status/portfolio_status, but we still
        # mirror the current step's label into rank_step/rank_step_label for
        # field-compatibility with callers that read it.
        rank_status = "success" if (rank_date or _done("pipeline")) else "none"
        if cur in SCHED_LABEL_MAP:
            rank_step, rank_step_label = cur, SCHED_LABEL_MAP[cur]

    vetter_status = "running" if cur == "vet" else ("success" if _done("vet") else "none")
    portfolio_status = (
        "running" if cur == "portfolio-builder"
        else ("success" if _done("portfolio-builder") else "none")
    )

    return {
        "rank_status": rank_status,
        "rank_step": rank_step,
        "rank_step_label": rank_step_label,
        "rank_pct": rank_pct,
        "vetter_status": vetter_status,
        "portfolio_status": portfolio_status,
    }
