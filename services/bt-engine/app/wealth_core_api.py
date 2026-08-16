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
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.hashes import HASH_ORDER
from stock_strategy_shared.wealth_core.risk_profile import PROFILE_NAME
from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES

from app.jobs_busy import (
    CorpusGenerationUnavailable,
    acquire_corpus_read_lock,
    acquire_job_start_gate,
    busy_detail,
    load_ready_data_generation,
    running_job_kind,
)
from app.wealth_core_chain import (
    ChainRehearsalDiverged,
    DEFAULT_RETENTION_TAIL,
    RETENTION_MODES,
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

#: Trading sessions of price history the signal needs BEFORE the first measured
#: session. `REQUIRED_CLOSES` is 127 (LONG_LOOKBACK_SESSIONS + 1), so 126 prior
#: sessions plus the first measured one satisfies it on day one.
def _engine_identity() -> dict:
    """What the RUNNING ENGINE can attest to about itself.

    Deliberately NOT an image id: a container has no reliable way to discover
    the image it was started from, and inventing one would be worse than
    admitting the gap. `BT_ENGINE_IMAGE_ID` is here so a deploy that DOES know
    (compose can inject it) can say so; absent, it is null and the finalizer
    treats that as a hole rather than a pass.

    `wealth_core_source_hash` is the field that does the real work. The
    certification manifest records the Wealth Core source Sentinel's image
    carries; this records the one the rehearsal actually imported. Comparing
    them proves the numbers came from the engine being certified — which
    inspecting a mutable `:latest` tag after the fact cannot, because the tag
    may have been rebuilt in between.
    """
    import platform

    from stock_strategy_shared import identity_hashes  # noqa: PLC0415
    from stock_strategy_shared.runtime_identity import (  # noqa: PLC0415
        dependency_identity,
    )

    return {
        "python": platform.python_version(),
        "wealth_core_source_hash": identity_hashes.wealth_core_source_hash(),
        "bt_engine_app_source_hash": identity_hashes.package_source_hash(
            os.path.dirname(os.path.abspath(__file__))),
        # Injected by the deploy when it knows; null otherwise, never guessed.
        "image_id": os.getenv("BT_ENGINE_IMAGE_ID") or None,
        "image_ref": os.getenv("BT_ENGINE_IMAGE") or None,
        "source_revision": os.getenv("BT_ENGINE_SOURCE_REVISION") or None,
        **dependency_identity("/app/requirements.lock"),
    }


WARMUP_SESSIONS = REQUIRED_CLOSES - 1
CANONICAL_BASELINE_STARTING_CASH = 1_000_000.0

#: Calendar days queried back to FIND those sessions. 126 sessions is ~183
#: calendar days; 400 leaves room for holidays and a thin patch without a second
#: round trip. The sessions are then counted exactly — this is only the net.
WARMUP_CALENDAR_DAYS = int(os.getenv("WEALTH_CORE_WARMUP_CALENDAR_DAYS", "400"))

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
#: write every few sessions for the whole run. It is nevertheless run-scoped:
#: a terminal row must never be paired with a plausible snapshot from that run.
_progress: dict = {}
_progress_run_id: str | None = None


def _begin_progress(run_id: str) -> None:
    """Give the newly admitted run sole ownership of the live progress slot."""
    global _progress, _progress_run_id
    _progress_run_id = run_id
    _progress = {}


def _publish_progress_for(run_id: str, snapshot: dict) -> None:
    """Publish only if ``run_id`` still owns the live display slot."""
    global _progress
    if _progress_run_id == run_id:
        _progress = {"run_id": run_id, **snapshot}


def _publish_progress(snapshot: dict) -> None:
    """Called from the worker THREAD running the rehearsal. A single dict
    assignment, which is atomic under the GIL — no lock, and no partially
    written snapshot can ever be observed."""
    global _progress
    # Backward-compatible direct callback for isolated `_execute` callers. The
    # background path binds a run id with `_publish_progress_for`; direct test
    # calls may update the current slot but cannot create one from nothing.
    owner = _progress_run_id
    if owner is not None:
        _publish_progress_for(owner, snapshot)


def _finish_progress(run_id: str) -> None:
    """Clear only the run that owns the slot; delayed cleanup is harmless."""
    global _progress, _progress_run_id
    if _progress_run_id == run_id:
        _progress = {}
        _progress_run_id = None


# A Wealth Core run loads the whole corpus for its date range; two at once, or
# one beside a sweep, is the memory profile that gets the container OOM-killed —
# and an OOM is indistinguishable from a strategy failure in the run row. So
# runs are serialised: this lock among themselves, and `jobs_busy` against the
# other two job types. That DB check used to live here and read only bt_runs and
# bt_sweeps, which defended this endpoint and NOTHING ELSE — the sweep endpoint
# never looked back, so the collision this comment describes happened anyway.
# Deliberately NOT main's `_job_lock`, which is held across a short INSERT;
# sharing it would hang `POST /jobs/run` for the whole duration of a Wealth Core
# job.
_state: dict[str, Any] = {"engine": None, "lock": asyncio.Lock()}


def configure(*, engine) -> None:
    _state["engine"] = engine


# ── the async/sync bridge ───────────────────────────────────────────────────
# The corpus loader is written against a SYNC connection, because that is what
# the backtester has. bt-engine's engine is async. Rather than fork the loader —
# which would give this file its own opinion about the corpus, the one thing it
# must not have — the loader runs in a worker thread and each `execute` is
# marshalled back onto the event loop.

#: Rows pulled from the server per round trip. Bounds the bridge's own memory;
#: the loader's output is unaffected. Small enough that the intermediate dicts
#: are noise beside the objects being built, large enough that a 7M-row read is
#: tens of round trips rather than thousands.
FETCH_CHUNK = int(os.getenv("WEALTH_CORE_FETCH_CHUNK", "100000"))


class _Rows:
    """A result consumed in the loader THREAD, pulled from the loop in CHUNKS.

    IT USED TO MATERIALISE EVERYTHING: `[dict(m) for m in res.mappings()]`, the
    whole result set, before returning. `load_bars` then walked that list
    building `VendorBar` objects — so at peak BOTH existed. A three-year read is
    ~7.5M price rows; the dicts alone were most of a 4 GiB container, and a
    2021-2023 rehearsal was OOM-killed 16 minutes in at 4.1 GB RSS, having built
    nothing.

    Chunking removes the larger of the two copies. The dicts now live only as
    long as one chunk, while the bars accumulate as before — which is the part
    the caller actually asked for.

    The rows still must not be a live cursor handed to another thread: each
    chunk is fetched by marshalling a coroutine back onto the loop and is a
    plain list by the time the loader touches it.
    """

    def __init__(self, fetch_chunk):
        self._fetch_chunk = fetch_chunk
        self._buffer: list[dict] = []
        self._exhausted = False

    def mappings(self):
        return self

    def _pull(self) -> list[dict]:
        if self._exhausted:
            return []
        rows = self._fetch_chunk()
        if not rows:
            self._exhausted = True
        return rows

    def first(self):
        """The first row, without draining the rest.

        Callers using this (the coverage probe) expect one aggregate row. Pulling
        a whole chunk to answer it is fine; pulling the whole table would not be.
        """
        if not self._buffer:
            self._buffer = self._pull()
        return self._buffer[0] if self._buffer else None

    def __iter__(self):
        # Anything `first()` already pulled is still owed to the iterator.
        buffered, self._buffer = self._buffer, []
        yield from buffered
        while True:
            rows = self._pull()
            if not rows:
                return
            yield from rows


class _ThreadConn:
    """Synchronous-looking connection whose work happens on the event loop."""

    def __init__(self, conn, loop):
        self._conn, self._loop = conn, loop

    def _await(self, coro_fn):
        """Run one coroutine on the loop from this thread and wait for it.

        Takes a FACTORY rather than a coroutine: a coroutine created on the
        calling thread and never awaited (if scheduling raised) is a warning and
        a leak, and the factory keeps creation and scheduling together.
        """
        return asyncio.run_coroutine_threadsafe(coro_fn(), self._loop).result()

    def execute(self, stmt, params=None):
        # `stream()` rather than `execute()`: a server-side cursor is what makes
        # the chunking real. With `execute()` the driver has already buffered the
        # entire result before the first row is handed over, so chunking on this
        # side would bound nothing.
        async def _open():
            # `stream()` returns a StartableContext, not a coroutine, so it must
            # be awaited inside a real coroutine before it can be marshalled.
            return await self._conn.stream(stmt, params or {})

        cursor = self._await(_open).mappings()

        def _fetch_chunk() -> list[dict]:
            async def _go():
                return [dict(m) for m in await cursor.fetchmany(FETCH_CHUNK)]
            return self._await(_go)

        return _Rows(_fetch_chunk)


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
    # The exact READY bt_data_version from the independently retained expected-
    # hash artifact. Hashes without their generation can be replayed against a
    # later in-place vendor correction and misreported as an engine divergence.
    expected_data_version: str | None = None
    # CHAIN_REHEARSAL only. How much per-session diagnostic detail the rehearsal
    # keeps in memory; see `wealth_core_chain.RETENTION_MODES`. Retention never
    # influences execution — every hash, counter and certification output is
    # identical under all three modes, asserted on the golden fixture.
    #
    # It is HERE because `rehearse_chain` has supported it since the memory work
    # and this endpoint could not ask for it: the parameter defaulted to "full"
    # and was never passed, so every rehearsal retained every SessionRehearsal
    # and RunTrace for the whole run. That is a per-session accumulator, and a
    # 753-session run measured it as +0.128 GiB per 5 minutes, dead linear,
    # until the container OOM-killed at 2h52m (2026-08-09). `rehearse_chain`'s
    # own refusal message already named this failure — "silently falling back to
    # 'full' on a typo is how a certification run OOMs after three hours" — and
    # it happened without a typo, because the value had no route to the caller.
    #
    # The default stays "full" deliberately: short runs, the golden fixture and
    # existing debugging are unchanged, and a long certification run asks for
    # "bounded" explicitly rather than inheriting a global change nobody saw.
    retention_mode: Literal["full", "bounded", "none"] = "full"
    retention_tail: int = DEFAULT_RETENTION_TAIL


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

    # Only the rehearsal retains per-session detail, so only the rehearsal can
    # act on this. Accepting it elsewhere would let an operator ask a
    # baseline_replay for bounded retention, watch it OOM anyway, and conclude
    # bounded does not work — a field with no consumer reading as a setting that
    # failed. Pydantic already rejects an invalid mode by name; this rejects a
    # valid mode in a place that cannot honour it.
    if req.mode != "chain_rehearsal" and req.retention_mode != "full":
        raise HTTPException(422, (
            f"retention_mode is chain_rehearsal-only; mode={req.mode!r} keeps "
            f"no per-session detail to elide. Refused rather than ignored: a "
            f"setting silently dropped is indistinguishable from one that did "
            f"not help."))

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
        if not req.expected_data_version:
            raise HTTPException(422, (
                "baseline_replay requires expected_data_version from the "
                "retained expected-hash artifact. Hashes without the exact "
                "corpus generation can be checked against later data and turn "
                "a corpus change into a false engine divergence."))
        if req.starting_cash != CANONICAL_BASELINE_STARTING_CASH:
            raise HTTPException(422, (
                "baseline_replay uses the producer's canonical starting_cash "
                f"{CANONICAL_BASELINE_STARTING_CASH}; received "
                f"{req.starting_cash!r}. Use mode=experiment for a different "
                "capital base."))
        if req.config:
            raise HTTPException(422, (
                "baseline_replay accepts no WealthCoreConfig overrides; it "
                "reproduces the producer's canonical strategy and volatility "
                "profile defaults. Use mode=experiment for a variant."))
        if req.eligibility:
            raise HTTPException(422, (
                "baseline_replay accepts no EligibilityConfig overrides; it "
                "reproduces the producer's canonical eligibility and "
                "volatility profile defaults. Use mode=experiment for a "
                "variant."))
    elif req.expected_data_version is not None:
        raise HTTPException(422, (
            "expected_data_version is baseline_replay-only. Refused rather "
            "than ignored so a caller cannot believe a generation pin applied "
            f"to mode={req.mode!r}."))

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

def _split_warmup(all_sessions, start_iso: str):
    """Split a session list into (warm-up, measured) at `start_iso`.

    The warm-up sessions feed the signal and NOTHING else: they produce no
    decision, no fill, no equity point, and are not hashed. Only the measured
    sessions are the run.

    Trimmed to the last WARMUP_SESSIONS so a wider calendar query does not
    change the result — the warm-up must depend on the session COUNT the signal
    needs, not on how far back the loader happened to look.
    """
    before = [s for s in all_sessions if s < start_iso]
    return before[-WARMUP_SESSIONS:], [s for s in all_sessions if s >= start_iso]


def _exclusive_prior_session(all_sessions, warmup_sessions) -> str | None:
    """Trading session immediately before retained feature history."""
    if not warmup_sessions:
        return None
    first = warmup_sessions[0]
    try:
        index = list(all_sessions).index(first)
    except ValueError:
        return None
    return str(all_sessions[index - 1]) if index > 0 else None


def corpus_date_range(req: WealthCoreJobRequest) -> tuple[date, date]:
    """The corpus range as DATE OBJECTS, never strings.

    A named function for one line because that line was the defect. Every loader
    binds these against a DATE column, and bt-engine reaches Postgres through
    ASYNCPG, which type-checks bind parameters strictly: a str for a date raises
    "'str' object has no attribute 'toordinal'". The backtester's own path uses
    psycopg2, which coerces silently — so `str(req.start_date)` was correct
    everywhere it had ever been exercised and failed on the FIRST QUERY of the
    first real corpus run, after the deploy, minutes into a three-hour job.

    Pydantic has already parsed these into `date`. Converting them away was the
    whole bug, and it is the kind that no fake connection can catch, which is
    why the check lives on this function rather than on a mock.
    """
    return req.start_date, req.end_date


def require_expected_data_generation(req: WealthCoreJobRequest,
                                     generation) -> None:
    """Bind expected hashes to the READY generation held by this snapshot."""
    if req.mode != "baseline_replay":
        return
    expected = req.expected_data_version
    if not expected:  # `_validate` owns the HTTP-facing shape; fail closed too.
        raise CorpusGenerationUnavailable(
            "baseline replay has no expected_data_version")
    if generation.version != expected:
        raise CorpusGenerationUnavailable(
            "baseline replay expected bt-data generation "
            f"{expected!r}, but the locked READY snapshot is "
            f"{generation.version!r}. Re-run the expected-hash producer; no "
            "corpus loader query was issued.")


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
        actions_after_session, actions_effective_in_sessions,
        assert_raw_price_domain,
        dividends_from_actions, load_actions,
        load_bars, load_identity, load_meta_timeline, load_sessions,
        sessions_index, require_usable_bars, require_usable_decision_bars,
        split_ratios_from_actions,
        terminal_events_from_actions,
        unusable_dividend_rows)
    # Its OWN module, also COPYed at image build. The loader above is guarded
    # against ever naming the total-return column — the series a benchmark
    # hurdle needs and a price domain must never see.
    from app.live.wealth_core_benchmark import load_benchmark_closes

    loop = asyncio.get_running_loop()
    start, end = corpus_date_range(req)
    # Price history BEFORE the measured window. Without it the signal cannot
    # rank anything until session 127 — see `_split_warmup`.
    warmup_from = start - timedelta(days=WARMUP_CALENDAR_DAYS)

    async with _state["engine"].connect() as aconn:
        # One immutable, identified corpus.  SET TRANSACTION must be the first
        # statement: SQLAlchemy's connection context otherwise uses PostgreSQL's
        # default READ COMMITTED mode, where every loader query may see a newer
        # writer commit than the previous one.  The non-blocking shared advisory
        # lock is cross-process, pairs with bt-data's whole-job exclusive lock,
        # and refuses instead of silently queueing a rehearsal behind a writer.
        await aconn.execute(text(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        await acquire_corpus_read_lock(aconn)
        generation = await load_ready_data_generation(aconn)
        # This check is deliberately before `_ThreadConn` exists and therefore
        # before the canonical loader can issue its first corpus query.  The
        # expected hashes and this generation came from one retained artifact;
        # checking after load would spend hours computing an answer over data
        # the request never authorised.
        require_expected_data_generation(req, generation)
        conn = _ThreadConn(aconn, loop)

        def _work() -> dict:
            coverage = assert_raw_price_domain(conn, warmup_from, end)
            all_sessions = load_sessions(conn, warmup_from, end)
            warmup_sessions, sessions = _split_warmup(all_sessions, str(start))
            if not sessions:
                raise RawPriceDomainUnavailable("no sessions in range")
            if len(warmup_sessions) < WARMUP_SESSIONS:
                raise RawPriceDomainUnavailable(
                    f"only {len(warmup_sessions)} session(s) of price history "
                    f"before {start}, and the signal needs {WARMUP_SESSIONS} "
                    f"(REQUIRED_CLOSES={REQUIRED_CLOSES}). Running anyway would "
                    f"NOT be a backtest from {start}: the book cannot rank a "
                    f"single name until session {REQUIRED_CLOSES}, sits in cash "
                    f"for ~6 months, then builds from a truncated history — "
                    f"while the benchmark is measured fully invested from day "
                    f"one. Remedy: request a later start_date, or backfill "
                    f"bt_prices further back.")
            actions_exclusive_prior_session = _exclusive_prior_session(
                all_sessions, warmup_sessions)
            if actions_exclusive_prior_session is None:
                raise RawPriceDomainUnavailable(
                    f"the {WARMUP_SESSIONS} retained warm-up sessions have no "
                    f"immediately preceding trading session inside the "
                    f"{WARMUP_CALENDAR_DAYS}-calendar-day lookup. That session "
                    f"is the exclusive corporate-action cutoff; without it a "
                    f"weekend/holiday event at the boundary cannot be placed "
                    f"without guessing. Backfill further or widen the lookup.")

            metadata_timeline = load_meta_timeline(conn, sessions=sessions)
            identity = load_identity(conn, as_of=end)
            # TWO indices, and the split is load-bearing.
            #
            # `snap_to_session` maps an action to the first session ON OR AFTER
            # its date, WITHIN the index it is given. So the index decides where
            # a warm-up-window action lands, and the right answer differs by
            # action type:
            #
            #   splits / dividends   FULL index. A 2:1 split in the warm-up must
            #                        be applied to the warm-up bar, or the signal
            #                        series is discontinuous exactly where the
            #                        momentum window reads it. Against the
            #                        measured-only index every pre-start split
            #                        would instead pile onto day one.
            #   terminal events      MEASURED index, over MEASURED rows only. A
            #                        delisting that happened before the run began
            #                        is not this run's event; snapping it forward
            #                        would manufacture a terminal action on the
            #                        first session, for a security the run never
            #                        held. Dropping is correct — the security
            #                        simply has no bars after it delisted.
            #
            # The full index is still TRIMMED to 126 warm-up sessions. Actions
            # on or before its immediately preceding trading session must be
            # removed first; otherwise `snap_to_session` puts them all on the
            # boundary. The cutoff is EXCLUSIVE so a weekend/holiday event
            # between prior and first retained session correctly maps forward.
            full_idx = sessions_index([*warmup_sessions, *sessions])
            source_action_rows = load_actions(conn, warmup_from, end)
            actions_first_retained_session = warmup_sessions[0]
            action_rows = actions_after_session(
                source_action_rows, actions_exclusive_prior_session)
            measured_action_rows = actions_effective_in_sessions(
                action_rows, full_idx, sessions)
            # The benchmark, over the SAME sessions. Fail-soft: no rows means
            # no comparison, never a failed run.
            benchmark_closes = load_benchmark_closes(
                conn, BENCHMARK_TICKER, start, end)
            use_actions = bool(action_rows)
            if not use_actions and REQUIRE_ACTIONS:
                raise CorporateActionsUnavailable(
                    f"bt_actions has no rows in the retained causal window "
                    f"after {actions_exclusive_prior_session} through {end} and "
                    f"WEALTH_CORE_REQUIRE_ACTIONS is set. Remedy: POST "
                    f"/jobs/backfill-actions on bt-data.")

            reconciliation: dict[str, int] = {}
            terminal: list = []
            dropped = 0
            if use_actions:
                splits = split_ratios_from_actions(action_rows, full_idx)
                divs = dividends_from_actions(action_rows, full_idx)
                dropped = unusable_dividend_rows(action_rows)
                bars = load_bars(conn, warmup_from, end, authoritative_splits=splits,
                                 reconciliation=reconciliation, dividends=divs,
                                 identity=identity)
                terminal = terminal_events_from_actions(
                    measured_action_rows, full_idx,
                    known_securities=set(metadata_timeline.security_ids),
                    identity=identity, metadata_timeline=metadata_timeline,
                    unresolved=identity.unresolved)
            else:
                bars = load_bars(conn, warmup_from, end, identity=identity)

            require_usable_bars(
                bars, start=warmup_from, end=end, context="bt_engine_corpus")
            require_usable_decision_bars(
                bars, metadata_timeline, start=start, end=end,
                context="bt_engine_corpus")
            return {
                "sessions": sessions, "bars_by_session": bars, "meta": {},
                "metadata_timeline": metadata_timeline,
                "warmup_sessions": warmup_sessions,
                "benchmark_closes": benchmark_closes,
                "terminal_events": terminal,
                "provenance": {
                    "sessions": len(sessions),
                    "securities": len(metadata_timeline.security_ids),
                    "warmup_sessions": len(warmup_sessions),
                    "warmup_first_session": warmup_sessions[0] if warmup_sessions else None,
                    "raw_close_coverage": round(coverage, 4),
                    "split_source": "actions" if use_actions else "derived",
                    "actions_rows": len(action_rows),
                    "actions_rows_loaded": len(source_action_rows),
                    "actions_rows_at_or_before_prior_cutoff":
                        len(source_action_rows) - len(action_rows),
                    "actions_first_retained_session":
                        actions_first_retained_session,
                    "actions_exclusive_prior_session":
                        actions_exclusive_prior_session,
                    "terminal_events_applied": len(terminal),
                    "split_reconciliation": dict(sorted(reconciliation.items())),
                    "dividend_rows_unusable": dropped,
                    "identity_unresolved": dict(sorted(identity.unresolved.items())),
                    "excluded_unknown_tickers": 0,
                    "caveats": list(CAVEATS) + list(
                        ACTIONS_CAVEATS if use_actions else DERIVED_SPLIT_CAVEATS),
                },
            }

        corpus = await asyncio.to_thread(_work)
        corpus["provenance"].update({
            "bt_data_version": generation.version,
            "bt_data_status": generation.status,
            "bt_data_source_mode": generation.source_mode,
            "bt_data_updated_at": generation.to_dict()["updated_at"],
        })
        return corpus


def _execute(req: WealthCoreJobRequest, corpus: dict, *, on_progress=None) -> dict:
    """Dispatch to the tunnel or the rehearsal. Pure once the corpus is loaded —
    which is what lets the whole thing run off the event loop."""
    cfg = _apply(WealthCoreConfig(), req.config, "WealthCoreConfig")
    elig = _apply(EligibilityConfig(), req.eligibility, "EligibilityConfig")
    common = dict(sessions=corpus["sessions"],
                  bars_by_session=corpus["bars_by_session"],
                  meta=corpus["meta"], starting_cash=req.starting_cash,
                  metadata_timeline=corpus.get("metadata_timeline"),
                  terminal_events=corpus["terminal_events"])
    warmup = list(corpus.get("warmup_sessions") or ())

    if req.mode == "chain_rehearsal":
        r = rehearse_chain(**common, cfg=cfg, eligibility_cfg=elig,
                           warmup_sessions=warmup,
                           config={"execution_model": STATEFUL_MODEL},
                           on_progress=(on_progress or _publish_progress),
                           progress_every=PROGRESS_EVERY,
                           retention_mode=req.retention_mode,
                           retention_tail=req.retention_tail,
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
                              warmup_sessions=warmup,
                              expected=req.expected_hashes)
    else:
        run = experiment(**common, cfg=cfg, eligibility_cfg=elig,
                         warmup_sessions=warmup,
                         baseline=req.baseline_hashes, change=req.change)
    return {"summary": run.to_dict(), "parity_hashes": run.hashes.to_dict()}


async def _run_bg(run_id: str, req: WealthCoreJobRequest) -> None:
    engine, lock = _state["engine"], _state["lock"]
    try:
        async with lock:
            corpus = await _load_corpus(req)
            out = await asyncio.to_thread(
                _execute, req, corpus,
                on_progress=lambda snapshot: _publish_progress_for(
                    run_id, snapshot))
        out["summary"] = {**out["summary"], "provenance": corpus["provenance"]}
        # Stop advertising provisional metrics BEFORE publishing a terminal DB
        # row. This ordering closes even the small await window in which a
        # caller could otherwise observe status=success beside running=true.
        _finish_progress(run_id)
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE bt_wealth_core_runs SET status='success', "
                "completed_at=NOW(), summary=CAST(:s AS JSONB), "
                "parity_hashes=CAST(:h AS JSONB) WHERE run_id=CAST(:r AS UUID)"),
                {"s": json.dumps(out["summary"], default=str),
                 "h": json.dumps(out["parity_hashes"]), "r": run_id})
    except Exception as exc:  # noqa: BLE001
        _finish_progress(run_id)
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
    finally:
        # Defensive against an exception in either terminal-row UPDATE. The
        # durable row may need restart reclamation, but its dead worker must not
        # keep presenting an active in-memory rehearsal.
        _finish_progress(run_id)


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
        # CHECK + INSERT must be one serial admission decision.  The local
        # asyncio lock is acquired later by the background task, so two HTTP
        # requests (or two engine processes) can otherwise both observe no
        # running row and both commit one.  The xact lock releases with this
        # transaction; the durable running row is what the next waiter sees.
        await acquire_job_start_gate(conn)
        # Shared with `/jobs/run` and `/sweeps/run` so all three enforce the
        # SAME constraint. This side was the only one ever enforced; see
        # app/jobs_busy.py for what that cost.
        busy = await running_job_kind(conn)
        if busy:
            raise HTTPException(409, busy_detail(busy))
        # THE ENGINE'S OWN IDENTITY, recorded AT START.
        #
        # The finalizer used to name the bt-engine image by inspecting whatever
        # `stocker-bt-engine:latest` pointed at when IT ran — which is a
        # different question from what ran the rehearsal. Rebuild the tag
        # between the run and finalization and the manifest names the wrong
        # image, silently and with no way to detect it afterwards.
        #
        # A container cannot discover its own image id, so this records what
        # the PROCESS can actually attest to: the interpreter, the Wealth Core
        # source tree it imported, and the image reference injected by the
        # deploy if there is one. `wealth_core_source_hash` is the load-bearing
        # field — it lets certification prove the rehearsal ran the SAME engine
        # source the manifest names, which is the binding that matters for
        # economics.
        spec_json = json.loads(req.model_dump_json())
        spec_json["engine_identity"] = _engine_identity()
        if req.mode == "baseline_replay":
            from stock_strategy_shared.runtime_identity import (  # noqa: PLC0415
                wealth_core_baseline_identity,
            )
            spec_json["baseline_identity"] = wealth_core_baseline_identity(
                starting_cash=req.starting_cash)
        await conn.execute(text(
            "INSERT INTO bt_wealth_core_runs (run_id, mode, spec) VALUES "
            "(CAST(:r AS UUID), :m, CAST(:s AS JSONB))"),
            {"r": run_id, "m": req.mode,
             "s": json.dumps(spec_json, sort_keys=True)})
    # Logged at START, unconditionally, for every mode. The retention setting was
    # invisible for the whole time it was wrong: nothing printed it, the run row
    # recorded a request that did not carry it, and "full" had to be inferred
    # from an RSS curve after the fact. An operator reading the first line of a
    # three-hour job should be able to see what it will do to memory.
    log.info("wealth-core run %s mode=%s range=%s..%s retention_mode=%s "
             "retention_tail=%s", run_id, req.mode, req.start_date,
             req.end_date, req.retention_mode, req.retention_tail)
    print(f"[wealth-core] run {run_id} mode={req.mode} "
          f"range={req.start_date}..{req.end_date} "
          f"retention_mode={req.retention_mode} "
          f"retention_tail={req.retention_tail}", flush=True)

    _begin_progress(run_id)
    background_tasks.add_task(_run_bg, run_id, req)
    return {"run_id": run_id, "mode": req.mode, "status": "running",
            "risk_profile": PROFILE_NAME if req.mode == "chain_rehearsal" else None}


@router.get("/progress")
async def wealth_core_progress():
    """The live snapshot of a running rehearsal. PROVISIONAL — see
    `_progress_snapshot`: it is measured before the parity check, so a run that
    later diverges will have shown healthy numbers the whole way and then
    publish no final metrics at all."""
    snapshot = dict(_progress)
    if not snapshot:
        return {"running": False, "detail": "no rehearsal has reported progress"}
    run_id = snapshot.get("run_id")
    try:
        row = await _fetch("WHERE run_id = CAST(:r AS UUID)", {"r": run_id})
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        _finish_progress(str(run_id))
        return {"running": False, "detail": "progress owner no longer exists"}
    # The durable run row is authoritative, and rechecking the slot closes a
    # race with cleanup or a subsequent run while the query awaited Postgres.
    if row.get("status") != "running" or _progress.get("run_id") != run_id:
        _finish_progress(str(run_id))
        return {"running": False,
                "detail": f"rehearsal {run_id} is no longer running"}
    return {"running": True, **snapshot}


@router.get("/runs/latest")
async def latest_wealth_core_run():
    row = await _fetch("ORDER BY started_at DESC LIMIT 1", {})
    # Merged only while the run is still going: once it is terminal the summary
    # is authoritative and a stale provisional block beside it would invite
    # someone to read the wrong CAGR.
    if (row.get("status") == "running"
            and _progress.get("run_id") == row.get("run_id")):
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
