"""Wealth Core, reachable from the wind tunnel over HTTP.

WHAT WAS MISSING. Everything Wealth Core needs to be experimented on existed and
none of it could be REACHED: `wealth_core_tunnel` (baseline replay + experiment),
`wealth_core_chain` (the live-chain rehearsal) and the backtester's corpus loader
were each covered by tests and called by nothing else. An engine nobody can
start is not an engine, and "the tunnel supports Wealth Core" was true only in
the sense that the functions compiled.

THE THREE MODES, and why they are one endpoint rather than three services:

    baseline_replay   run the reference stream and REQUIRE all seven parity
                      hashes to equal the backtester's. Produces no opinion.
    experiment        run a variant, record the parent hashes and the exact
                      change, and report the first layer at which it diverged.
    chain_rehearsal   drive the LIVE chain one session at a time — the same
                      `plan_session` the scheduler would call — gate every order
                      through the wealth_core_v1 risk profile, and prove the
                      result reproduces the bulk replay exactly.

They share a corpus load, a lock, a result row and a set of refusals; splitting
them would duplicate all five.

ONE CORPUS LOADER, NOT TWO. The Sharadar column-to-domain mapping lives once, in
`wealth_core_replay.py`, and is COPYed into this image at build time next to the
live modules `app/live/` already carries. Re-implementing the load here is the
exact failure the factor-coverage contract was written after: two readers of the
same corpus that agree until they quietly do not, with every check green.

WHAT THIS DOES NOT DO. It submits nothing and contacts no broker. The rehearsal
evaluates risk IN-PROCESS with the same pure functions `/check` uses, so a
rejection here is the rejection live would give for the same order — but a live
deployment additionally needs the profile hash to match ACROSS THE WIRE, which
only two running processes can show.
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import json
import logging
import traceback
import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.hashes import HASH_ORDER
from stock_strategy_shared.wealth_core.risk_profile import PROFILE_NAME

from app.wealth_core_chain import (
    ChainRehearsalDiverged,
    STATEFUL_MODEL,
    rehearse_chain,
)
from app.wealth_core_tunnel import (
    ParityViolation,
    TunnelMode,
    apply_config_change,
    baseline_replay,
    experiment,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/wealth-core", tags=["wealth-core"])

WEALTH_CORE_DDL = [
    """CREATE TABLE IF NOT EXISTS bt_wealth_core_runs (
        run_id UUID PRIMARY KEY,
        mode VARCHAR(24) NOT NULL,
        spec JSONB NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'running'
            CHECK (status IN ('running','success','failed')),
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        summary JSONB,
        parity_hashes JSONB,
        error_message TEXT)""",
    """CREATE INDEX IF NOT EXISTS idx_bt_wealth_core_runs_started
        ON bt_wealth_core_runs (started_at DESC)""",
]

#: The benchmark a Wealth Core run is measured against. In `bt_prices` already
#: (bt-data's benchmark stage fetches SPY/QQQ/IWM/SOXX from SFP).
BENCHMARK_TICKER = os.getenv("WEALTH_CORE_BENCHMARK", "SPY")

#: Publish a progress snapshot every N sessions. Each one re-measures the whole
#: curve so far, which is O(sessions) — at every session a 753-session run would
#: do ~280k session-visits of pointless work for a display nobody reads that
#: fast.
PROGRESS_EVERY = int(os.getenv("WEALTH_CORE_PROGRESS_EVERY", "5"))

#: The live progress slot. IN MEMORY on purpose: it is a display, it is worthless
#: after the process that produced it has gone, and persisting it would mean a DB
#: write every few sessions for the whole run. `/wealth-core/progress` reads it.
_progress: dict = {}


def _publish_progress(snapshot: dict) -> None:
    """Called from the worker THREAD running the rehearsal. A single dict
    assignment, which is atomic under the GIL — no lock, and no partially
    written snapshot can ever be observed."""
    global _progress
    _progress = snapshot


# A Wealth Core run loads the whole corpus for its date range; two at once, or
# one beside a sweep, is the memory profile that gets the container OOM-killed —
# and an OOM is indistinguishable from a strategy failure in the run row. So
# runs are serialised: this lock among themselves, and a DB check for a running
# bt_runs / bt_sweeps row against the other engines. Deliberately NOT main's
# `_job_lock`, which is held across a short INSERT; sharing it would hang
# `POST /jobs/run` for the whole duration of a Wealth Core job.
_state: dict[str, Any] = {"engine": None, "lock": asyncio.Lock()}


def configure(*, engine) -> None:
    _state["engine"] = engine


# ── the async/sync bridge ───────────────────────────────────────────────────
# The corpus loader is written against a SYNC connection, because that is what
# the backtester has. bt-engine's engine is async. Rather than fork the loader —
# which would give this file its own opinion about the corpus, the one thing it
# must not have — the loader runs in a worker thread and each `execute` is
# marshalled back onto the event loop.

class _Rows:
    """A materialised result. Rows are consumed in the loader THREAD, so they
    must not be a live cursor bound to the loop's connection."""

    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _ThreadConn:
    """Synchronous-looking connection whose work happens on the event loop."""

    def __init__(self, conn, loop):
        self._conn, self._loop = conn, loop

    def execute(self, stmt, params=None):
        async def _go():
            res = await self._conn.execute(stmt, params or {})
            return [dict(m) for m in res.mappings()]

        fut = asyncio.run_coroutine_threadsafe(_go(), self._loop)
        return _Rows(fut.result())


# ── request / refusals ──────────────────────────────────────────────────────

class WealthCoreJobRequest(BaseModel):
    mode: Literal["baseline_replay", "experiment", "chain_rehearsal"]
    start_date: date
    end_date: date
    starting_cash: float = 1_000_000.0
    # Field DIFFS over the defaults, not whole objects: an unknown field is
    # refused by name rather than accepted and ignored.
    config: dict = {}
    eligibility: dict = {}
    # EXPERIMENT only. Both required — see `_validate`.
    change: dict = {}
    baseline_hashes: dict | None = None
    # BASELINE_REPLAY only.
    expected_hashes: dict | None = None


def _apply(obj, change: dict, what: str):
    if not change:
        return obj
    known = {f.name for f in dataclasses.fields(obj)}
    unknown = sorted(set(change) - known)
    if unknown:
        raise HTTPException(422, f"unknown {what} field(s) {unknown}; known: "
                                 f"{sorted(known)}")
    return dataclasses.replace(obj, **dict(change))


def _validate(req: WealthCoreJobRequest) -> None:
    """Every refusal here exists because the alternative produces a NUMBER that
    looks like an answer to a question nobody asked."""
    if req.end_date < req.start_date:
        raise HTTPException(422, "end_date precedes start_date")

    if req.mode == "baseline_replay":
        if not req.expected_hashes:
            raise HTTPException(422, (
                "baseline_replay requires expected_hashes, supplied by the "
                "BACKTESTER. Recomputing them here would prove only that the "
                "tunnel agrees with itself, which is what a parity check exists "
                "to rule out."))
        missing = [k for k in HASH_ORDER if k not in req.expected_hashes]
        if missing:
            raise HTTPException(422, (
                f"expected_hashes is missing {missing}. All seven layers are "
                f"required: a partial set silently narrows the check to the "
                f"layers that happen to be present."))
        if req.change:
            raise HTTPException(422, (
                "a baseline_replay records no change — it reproduces the "
                "reference stream. Use mode=experiment."))

    if req.mode == "experiment":
        if not req.change:
            raise HTTPException(422, (
                "an experiment must record its change. Without it a result "
                "cannot be traced to what produced it, and is indistinguishable "
                "from a baseline replay that silently failed."))
        if not req.baseline_hashes:
            raise HTTPException(422, (
                "an experiment must state the baseline it is measured against. "
                "A divergence layer is meaningless without the parent it "
                "diverged from."))
        # The change must be REFLECTED in the run, not merely described. A
        # `change` naming fields the config diff does not set would attribute a
        # result to something that never happened.
        described = set(req.change) - {"note", "notes", "rationale"}
        applied = set(req.config) | set(req.eligibility)
        undelivered = sorted(described - applied)
        if described and undelivered:
            raise HTTPException(422, (
                f"change names {undelivered} but neither `config` nor "
                f"`eligibility` sets them. A recorded change that the run did "
                f"not make attributes the result to something that never "
                f"happened."))

    if req.mode == "chain_rehearsal" and req.change:
        raise HTTPException(422, (
            "a chain_rehearsal reproduces one run through the live path; it is "
            "not a variant. Use mode=experiment to compare configs."))


# ── the job ─────────────────────────────────────────────────────────────────

async def _load_corpus(req: WealthCoreJobRequest) -> dict:
    """Read the corpus through the BACKTESTER's loader, in a worker thread.

    Returns the normalised stream plus the provenance the caller needs to know
    whether the run is certified-reproducible — `split_source` above all, since
    a run on derived splits is otherwise indistinguishable from one on the
    authoritative stream.
    """
    from app.live.wealth_core_replay import (  # COPYed at image build
        ACTIONS_CAVEATS, CAVEATS, DERIVED_SPLIT_CAVEATS, REQUIRE_ACTIONS,
        CorporateActionsUnavailable, RawPriceDomainUnavailable,
        assert_raw_price_domain, dividends_from_actions, load_actions,
        load_bars, load_identity, load_meta, load_sessions, sessions_index,
        split_ratios_from_actions, terminal_events_from_actions,
        unusable_dividend_rows)
    # Its OWN module, also COPYed at image build. The loader above is guarded
    # against ever naming the total-return column — the series a benchmark
    # hurdle needs and a price domain must never see.
    from app.live.wealth_core_benchmark import load_benchmark_closes

    loop = asyncio.get_running_loop()
    start, end = str(req.start_date), str(req.end_date)

    async with _state["engine"].connect() as aconn:
        conn = _ThreadConn(aconn, loop)

        def _work() -> dict:
            coverage = assert_raw_price_domain(conn, start, end)
            sessions = load_sessions(conn, start, end)
            if not sessions:
                raise RawPriceDomainUnavailable("no sessions in range")

            meta = load_meta(conn)
            identity = load_identity(conn)
            idx = sessions_index(sessions)
            action_rows = load_actions(conn, start, end)
            # The benchmark, over the SAME sessions. Fail-soft: no rows means
            # no comparison, never a failed run.
            benchmark_closes = load_benchmark_closes(
                conn, BENCHMARK_TICKER, start, end)
            use_actions = bool(action_rows)
            if not use_actions and REQUIRE_ACTIONS:
                raise CorporateActionsUnavailable(
                    f"bt_actions is empty between {start} and {end} and "
                    f"WEALTH_CORE_REQUIRE_ACTIONS is set. Remedy: POST "
                    f"/jobs/backfill-actions on bt-data.")

            reconciliation: dict[str, int] = {}
            terminal: list = []
            dropped = 0
            if use_actions:
                splits = split_ratios_from_actions(action_rows, idx)
                divs = dividends_from_actions(action_rows, idx)
                dropped = unusable_dividend_rows(action_rows)
                bars = load_bars(conn, start, end, authoritative_splits=splits,
                                 reconciliation=reconciliation, dividends=divs,
                                 identity=identity)
                terminal = terminal_events_from_actions(
                    action_rows, idx, known_securities=set(meta),
                    identity=identity, meta=meta, unresolved=identity.unresolved)
            else:
                bars = load_bars(conn, start, end, identity=identity)

            unknown = sorted({b.security_id for v in bars.values() for b in v}
                             - set(meta))
            if unknown:
                bars = {s: [b for b in v if b.security_id in meta]
                        for s, v in bars.items()}
            return {
                "sessions": sessions, "bars_by_session": bars, "meta": meta,
                "benchmark_closes": benchmark_closes,
                "terminal_events": terminal,
                "provenance": {
                    "sessions": len(sessions), "securities": len(meta),
                    "raw_close_coverage": round(coverage, 4),
                    "split_source": "actions" if use_actions else "derived",
                    "actions_rows": len(action_rows),
                    "terminal_events_applied": len(terminal),
                    "split_reconciliation": dict(sorted(reconciliation.items())),
                    "dividend_rows_unusable": dropped,
                    "identity_unresolved": dict(sorted(identity.unresolved.items())),
                    "excluded_unknown_tickers": len(unknown),
                    "caveats": list(CAVEATS) + list(
                        ACTIONS_CAVEATS if use_actions else DERIVED_SPLIT_CAVEATS),
                },
            }

        return await asyncio.to_thread(_work)


def _execute(req: WealthCoreJobRequest, corpus: dict) -> dict:
    """Dispatch to the tunnel or the rehearsal. Pure once the corpus is loaded —
    which is what lets the whole thing run off the event loop."""
    cfg = _apply(WealthCoreConfig(), req.config, "WealthCoreConfig")
    elig = _apply(EligibilityConfig(), req.eligibility, "EligibilityConfig")
    common = dict(sessions=corpus["sessions"],
                  bars_by_session=corpus["bars_by_session"],
                  meta=corpus["meta"], starting_cash=req.starting_cash,
                  terminal_events=corpus["terminal_events"])

    if req.mode == "chain_rehearsal":
        r = rehearse_chain(**common, cfg=cfg, eligibility_cfg=elig,
                           config={"execution_model": STATEFUL_MODEL},
                           on_progress=_publish_progress,
                           progress_every=PROGRESS_EVERY,
                           benchmark_closes=corpus.get("benchmark_closes"),
                           benchmark_ticker=BENCHMARK_TICKER)
        d = r.to_dict()
        # The per-session detail is the point of a rehearsal but it is one row
        # per trading day; the run row keeps the verdict and the counts, and the
        # sessions ride along only when the range is small enough to be read.
        #
        # `d["performance"]` is computed inside `rehearse_chain` (after parity)
        # and is a SIBLING of `sessions`, so it survives this. That ordering is
        # the whole point: the equity curve is the only raw material for a CAGR
        # or a drawdown, and eliding it before measuring is exactly why a
        # three-year rehearsal used to produce no measurable output at all.
        if len(d["sessions"]) > 400:
            d["sessions"] = f"{len(d['sessions'])} sessions elided"
        return {"summary": d, "parity_hashes": r.bulk_hashes}

    if req.mode == "baseline_replay":
        run = baseline_replay(**common, cfg=cfg, eligibility_cfg=elig,
                              expected=req.expected_hashes)
    else:
        run = experiment(**common, cfg=cfg, eligibility_cfg=elig,
                         baseline=req.baseline_hashes, change=req.change)
    return {"summary": run.to_dict(), "parity_hashes": run.hashes.to_dict()}


async def _run_bg(run_id: str, req: WealthCoreJobRequest) -> None:
    engine, lock = _state["engine"], _state["lock"]
    try:
        async with lock:
            corpus = await _load_corpus(req)
            out = await asyncio.to_thread(_execute, req, corpus)
        out["summary"] = {**out["summary"], "provenance": corpus["provenance"]}
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE bt_wealth_core_runs SET status='success', "
                "completed_at=NOW(), summary=CAST(:s AS JSONB), "
                "parity_hashes=CAST(:h AS JSONB) WHERE run_id=CAST(:r AS UUID)"),
                {"s": json.dumps(out["summary"], default=str),
                 "h": json.dumps(out["parity_hashes"]), "r": run_id})
    except Exception as exc:  # noqa: BLE001
        # A ParityViolation / ChainRehearsalDiverged is a RESULT, not a crash —
        # the one the run existed to look for — so it is recorded with its full
        # message rather than reduced to "failed".
        kind = ("parity_violation" if isinstance(exc, ParityViolation) else
                "chain_divergence" if isinstance(exc, ChainRehearsalDiverged)
                else "error")
        log.error("wealth-core run %s %s: %s", run_id, kind, exc)
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE bt_wealth_core_runs SET status='failed', "
                "completed_at=NOW(), error_message=:e WHERE "
                "run_id=CAST(:r AS UUID)"),
                {"e": f"{kind}: {exc}\n{traceback.format_exc()[-2000:]}",
                 "r": run_id})


@router.post("/jobs/run")
async def start_wealth_core_job(req: WealthCoreJobRequest,
                                background_tasks: BackgroundTasks):
    _validate(req)
    if _state["engine"] is None:
        raise HTTPException(503, "wealth-core router not configured")
    if _state["lock"].locked():
        raise HTTPException(409, (
            "a Wealth Core run is already in progress. Each loads the whole "
            "corpus for its range; two concurrent loads is the memory profile "
            "that gets the container OOM-killed, and an OOM is indistinguishable "
            "from a strategy failure in the run row."))

    run_id = str(uuid.uuid4())
    async with _state["engine"].begin() as conn:
        busy = (await conn.execute(text(
            "SELECT 1 FROM bt_runs WHERE status='running' "
            "UNION ALL SELECT 1 FROM bt_sweeps WHERE status='running' LIMIT 1"
        ))).first()
        if busy:
            raise HTTPException(409, (
                "a backtest run or sweep is in progress on this engine. "
                "Refused rather than queued: the two corpora do not fit "
                "together, and an OOM would be recorded as a strategy failure."))
        await conn.execute(text(
            "INSERT INTO bt_wealth_core_runs (run_id, mode, spec) VALUES "
            "(CAST(:r AS UUID), :m, CAST(:s AS JSONB))"),
            {"r": run_id, "m": req.mode,
             "s": req.model_dump_json()})
    _publish_progress({})   # a previous run's snapshot is not this run's
    background_tasks.add_task(_run_bg, run_id, req)
    return {"run_id": run_id, "mode": req.mode, "status": "running",
            "risk_profile": PROFILE_NAME if req.mode == "chain_rehearsal" else None}


@router.get("/progress")
async def wealth_core_progress():
    """The live snapshot of a running rehearsal. PROVISIONAL — see
    `_progress_snapshot`: it is measured before the parity check, so a run that
    later diverges will have shown healthy numbers the whole way and then
    publish no final metrics at all."""
    if not _progress:
        return {"running": False, "detail": "no rehearsal has reported progress"}
    return {"running": True, **_progress}


@router.get("/runs/latest")
async def latest_wealth_core_run():
    row = await _fetch("ORDER BY started_at DESC LIMIT 1", {})
    # Merged only while the run is still going: once it is terminal the summary
    # is authoritative and a stale provisional block beside it would invite
    # someone to read the wrong CAGR.
    if row.get("status") == "running" and _progress:
        row = {**row, "progress": _progress}
    return row


@router.get("/runs/{run_id}")
async def get_wealth_core_run(run_id: str):
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, "run_id must be a UUID")
    return await _fetch("WHERE run_id = CAST(:r AS UUID)", {"r": run_id})


async def _fetch(where: str, params: dict) -> dict:
    if _state["engine"] is None:
        raise HTTPException(503, "wealth-core router not configured")
    async with _state["engine"].connect() as conn:
        row = (await conn.execute(text(
            f"SELECT run_id, mode, status, started_at, completed_at, spec, "
            f"summary, parity_hashes, error_message FROM bt_wealth_core_runs "
            f"{where}"), params)).mappings().first()
    if row is None:
        raise HTTPException(404, "no wealth-core run found")
    d = dict(row)
    d["run_id"] = str(d["run_id"])
    for k in ("started_at", "completed_at"):
        d[k] = d[k].isoformat() if d[k] else None
    return d


__all__ = ["WEALTH_CORE_DDL", "WealthCoreJobRequest", "configure", "router",
           "TunnelMode"]
