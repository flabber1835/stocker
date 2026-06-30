"""Per-run consolidated HEALTH RECORD — one self-contained blob per chain run.

Replaces the scattered per-step trace files with a single schema'd artifact that
serves two purposes:

  1. EVALUATOR INPUT — the deterministic per-run evidence the (weekly) LLM evaluator
     reads to reason about the strategy.
  2. HEALTH AUDIT — a self-describing record a frontier model can read (monthly) to
     judge "is the system functioning correctly?". The KEY design choice: the blob
     carries COMPUTED invariant checks (value + expected range + pass/fail) plus
     bounded summary stats — NOT raw universe dumps. An LLM can't re-derive math over
     thousands of rows, but it CAN spot a failed invariant, an out-of-range value, a
     count mismatch, or an error. Python computes; the LLM judges.

Built from the DB (the source of truth) at chain end, keyed by the trading SESSION
date. Bounded by construction (summaries + the invariant list), so a month of these
fits comfortably in a model's context.
"""
from __future__ import annotations

import json
import os
import traceback
from datetime import date, datetime, timezone

from sqlalchemy import text

from stock_strategy_shared.factor_registry import FACTOR_NAMES

SCHEMA_VERSION = 1


# ── invariants (pure: judged numbers, with expected ranges, for the LLM/operator) ──
def compute_invariants(chain: dict, coverage: dict, rank_stats: dict) -> list[dict]:
    """Deterministic checks over the gathered run summaries. Each item is
    {check, value, expected, pass, severity} — self-describing so the audit needs no
    external context. Targets the bug CLASSES seen in this system: config skew,
    count non-reconciliation, capacity overflow, all-null (broken) factors, restart
    orphans, step failures."""
    inv: list[dict] = []

    def add(check, value, expected, ok, severity="error"):
        inv.append({"check": check, "value": value, "expected": expected,
                    "pass": bool(ok), "severity": severity})

    steps = ("ingest", "factor", "ranking", "vetter", "portfolio", "delta")

    # every chain step that ran must have succeeded
    for s in steps:
        st = (chain.get(s) or {}).get("status")
        if st is not None:
            add(f"{s}_status_success", st, "success", st == "success")

    # config_hash identical across the scoring/build/delta steps (skew detector)
    hashes = {s: (chain.get(s) or {}).get("config_hash")
              for s in ("factor", "ranking", "portfolio", "delta")}
    present = {k: v for k, v in hashes.items() if v}
    add("config_hash_consistent", present, "all equal", len(set(present.values())) <= 1)

    # ranking count reconciliation: ranked == universe − dropped, and ranked > 0
    r = chain.get("ranking") or {}
    if all(r.get(k) is not None for k in ("universe_count", "ranked_count", "dropped_count")):
        add("rank_count_reconciles",
            {"universe": r["universe_count"], "ranked": r["ranked_count"], "dropped": r["dropped_count"]},
            "ranked == universe - dropped",
            r["ranked_count"] == r["universe_count"] - r["dropped_count"])
    if r.get("ranked_count") is not None:
        add("ranked_count_positive", r["ranked_count"], "> 0", r["ranked_count"] > 0)

    # portfolio selection within the position cap
    p, d = chain.get("portfolio") or {}, chain.get("delta") or {}
    if p.get("selected_count") is not None and d.get("max_positions"):
        add("selected_within_cap", p["selected_count"], f"<= {d['max_positions']}",
            p["selected_count"] <= d["max_positions"])

    # factor coverage: a WEIGHTED/active factor that is ~entirely null signals a
    # broken compute (the NaN-factor bug class). `coverage` = null fraction per factor.
    for f, pct in (coverage or {}).items():
        add(f"factor_coverage_{f}", round(pct, 4), "< 0.95 null", pct < 0.95, severity="warn")

    # restart-orphan marker must not leak into a 'success' chain
    for s in steps:
        em = (chain.get(s) or {}).get("error_message") or ""
        if "RESTART_ABORTED" in em:
            add(f"{s}_no_restart_abort", em[:120], "no RESTART_ABORTED", False)

    # composite score sanity (finite, min<=max)
    lo, hi = rank_stats.get("composite_min"), rank_stats.get("composite_max")
    if lo is not None or hi is not None:
        add("composite_score_sane", {"min": lo, "max": hi}, "finite, min <= max",
            lo is not None and hi is not None and lo <= hi)

    return inv


# ── DB gather ──────────────────────────────────────────────────────────────────
async def _one(engine, sql: str, params: dict) -> dict | None:
    # Each probe runs in its OWN connection so one malformed/aborted query can't poison
    # the rest of the record (a failed statement aborts its whole transaction).
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text(sql), params)).mappings().first()
            return dict(row) if row else None
    except Exception as _e:  # noqa: BLE001 — a missing/odd row must never break the record
        import os as _os
        if _os.getenv("HEALTH_RECORD_DEBUG"):
            print("[health-record] gather error:", type(_e).__name__, str(_e)[:160])
        return None


async def _gather_chain(engine, session_date: date) -> dict:
    """Latest run-row per chain step for the session (most-recent by started_at)."""
    sd = str(session_date)
    chain: dict = {}
    chain["ingest"] = await _one(engine,
        "SELECT run_id::text, status, session_date::text, started_at, completed_at, error_message "
        "FROM ingest_runs WHERE session_date::text = :sd ORDER BY started_at DESC LIMIT 1", {"sd": sd})
    chain["factor"] = await _one(engine,
        "SELECT run_id::text, status, config_hash, regime, ticker_count, warning_count, "
        "error_message, started_at, completed_at "
        "FROM factor_runs WHERE score_date::text = :sd ORDER BY started_at DESC LIMIT 1", {"sd": sd})
    chain["ranking"] = await _one(engine,
        "SELECT run_id::text, status, config_hash, regime, universe_count, ranked_count, "
        "dropped_count, error_message, started_at, completed_at "
        "FROM ranking_runs WHERE rank_date::text = :sd ORDER BY started_at DESC LIMIT 1", {"sd": sd})
    chain["vetter"] = await _one(engine,
        "SELECT vr.run_id::text, vr.status, vr.model, vr.candidate_count, vr.flagged_count, "
        "vr.error_message, vr.started_at, vr.completed_at FROM vetter_runs vr "
        "JOIN ranking_runs rr ON rr.run_id = vr.source_ranking_run_id "
        "WHERE rr.rank_date::text = :sd ORDER BY vr.started_at DESC LIMIT 1", {"sd": sd})
    chain["portfolio"] = await _one(engine,
        "SELECT run_id::text, status, config_hash, regime, candidate_count, selected_count, "
        "avg_pairwise_correlation, portfolio_estimated_vol, error_message, started_at, completed_at "
        "FROM portfolio_runs WHERE portfolio_date::text = :sd ORDER BY started_at DESC LIMIT 1", {"sd": sd})
    chain["delta"] = await _one(engine,
        "SELECT run_id::text, status, config_hash, max_positions, current_portfolio_size, "
        "entries_count, exits_count, holds_count, watches_count, error_message, started_at, completed_at "
        "FROM delta_runs WHERE run_date::text = :sd ORDER BY started_at DESC LIMIT 1", {"sd": sd})
    return chain


async def _factor_coverage(engine, factor_run_id: str | None) -> dict:
    """Null FRACTION per registry factor in factor_scores for this run (from the
    canonical `scores` JSONB). A near-1.0 fraction on a weighted factor = broken math."""
    if not factor_run_id:
        return {}
    cols = ", ".join(f"count(scores->>'{f}') AS nn_{f}" for f in FACTOR_NAMES)
    row = await _one(engine,
        f"SELECT count(*) AS total, {cols} FROM factor_scores WHERE run_id = CAST(:rid AS uuid)",
        {"rid": factor_run_id})
    if not row or not row.get("total"):
        return {}
    total = row["total"]
    return {f: round(1.0 - (row[f"nn_{f}"] or 0) / total, 6) for f in FACTOR_NAMES}


async def _rank_stats(engine, ranking_run_id: str | None) -> dict:
    if not ranking_run_id:
        return {}
    row = await _one(engine,
        "SELECT count(*) AS n, MIN(composite_score)::float AS lo, MAX(composite_score)::float AS hi, "
        "AVG(composite_score)::float AS mean FROM rankings WHERE run_id = CAST(:rid AS uuid)",
        {"rid": ranking_run_id})
    if not row:
        return {}
    return {"count": row["n"], "composite_min": row["lo"],
            "composite_max": row["hi"], "composite_mean": row["mean"]}


async def build_health_record(engine, session_date: date) -> dict:
    """Assemble the consolidated per-run health record for `session_date`."""
    chain = await _gather_chain(engine, session_date)
    factor_run_id = (chain.get("factor") or {}).get("run_id")
    ranking_run_id = (chain.get("ranking") or {}).get("run_id")
    coverage = await _factor_coverage(engine, factor_run_id)
    rank_stats = await _rank_stats(engine, ranking_run_id)

    invariants = compute_invariants(chain, coverage, rank_stats)
    failed = [i["check"] for i in invariants if not i["pass"] and i["severity"] == "error"]
    warned = [i["check"] for i in invariants if not i["pass"] and i["severity"] == "warn"]

    # errors/warnings surfaced per step for the "did anything go wrong" read
    errors = {s: (chain.get(s) or {}).get("error_message")
              for s in chain if (chain.get(s) or {}).get("error_message")}

    return {
        "schema_version": SCHEMA_VERSION,
        "session_date": str(session_date),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chain": chain,
        "factor_coverage_null_fraction": coverage,
        "rank_stats": rank_stats,
        "step_errors": errors,
        "invariants": invariants,
        "health": {"ok": not failed, "failed_invariants": failed, "warned_invariants": warned},
    }


async def write_health_record(engine, artifacts_path: str, session_date: date) -> str | None:
    """Build + write the health record to artifacts_path/runs/run_<session>.json.
    No-op (returns None) when artifacts_path is empty. Never raises."""
    if not artifacts_path:
        return None
    try:
        record = await build_health_record(engine, session_date)
        runs_dir = os.path.join(artifacts_path, "runs")
        os.makedirs(runs_dir, exist_ok=True)
        path = os.path.join(runs_dir, f"run_{session_date}.json")
        with open(path, "w") as f:
            json.dump(record, f, indent=2, default=str)
        h = record["health"]
        print(f"[health-record] {path} (ok={h['ok']}, failed={h['failed_invariants']})")
        return path
    except Exception as exc:  # noqa: BLE001 — the record is best-effort; never break the chain
        print(f"[health-record] WARNING: failed to write for {session_date}: {exc}")
        traceback.print_exc()
        return None
