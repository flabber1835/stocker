"""Mutual exclusion between the three corpus-loading job types on bt-engine.

`POST /jobs/run`, `POST /sweeps/run` and `POST /wealth-core/jobs/run` each load
the whole corpus for their own date range. Two resident at once is the memory
profile that gets the container OOM-killed — and the container's `OOMKilled`
flag does NOT reliably record that, so the job rows read `RESTART_ABORTED` and
an environment failure becomes indistinguishable from a strategy failure.

**The check has to be symmetric, and it was not.** Wealth Core refused to start
beside a backtest or a sweep. Neither of those looked at Wealth Core, and
`/jobs/run` and `/sweeps/run` did not look at each other either — each queried
only its OWN table. One of six ordered pairs was actually defended.

That asymmetry is invisible while one job type runs at a time, which is how it
survived: it took the nightly sweep firing at 02:00 UTC into a Wealth Core
rehearsal started at 00:55 to expose it, and it cost both jobs and four hours
(2026-08-09). The refusal comment in `wealth_core_api` had described this exact
failure since it was written; only one side of it was enforced.

Generalises the crash-brake rule in CLAUDE.md: a constraint between two parties
must be enforced from BOTH ends, not from whichever end was written last.

The same module owns the two database gates that must be identical across
processes: the short transaction which admits a new run, and the shared corpus
lock paired with bt-data's exclusive writer lock.  A process-local asyncio lock
cannot establish either property.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text


#: Cross-process lock protecting the certification corpus.  bt-data takes this
#: key EXCLUSIVE for the complete mutation job; corpus readers take it SHARED
#: for their transaction.  Keep the literal in sync with bt-data and the corpus
#: parity tool -- PostgreSQL advisory locks are the process boundary here.
CORPUS_LOCK_KEY = 0x4254_434F_5250_5553

#: Serialises the short "check busy + insert running row" transaction.  The
#: in-process asyncio lock is acquired by the background task, after the HTTP
#: request has already returned, so it cannot close the two-request race at the
#: start boundary.  A transaction-scoped advisory lock does, including across
#: multiple bt-engine processes.
JOB_START_LOCK_KEY = 0x4254_4A4F_4253_5441

#: One certification engine process owns one certification database. This is a
#: SESSION lock, deliberately unlike the transaction gates above: it remains
#: held for the process lifetime on a dedicated connection. Without it a
#: second process can start while the first has a live background rehearsal and
#: run the orphan-reclaim UPDATE against the first process's `running` row.
ENGINE_PROCESS_LEASE_KEY = 0x4254_454E_4749_4E45


class EngineProcessLeaseUnavailable(RuntimeError):
    """Another bt-engine process still owns this certification database."""


class CorpusGenerationUnavailable(RuntimeError):
    """The certification corpus has no complete, citable generation."""


@dataclass(frozen=True)
class DataGeneration:
    """Identity read inside the same snapshot as the rehearsal corpus."""

    version: str
    status: str
    source_mode: str
    updated_at: object
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "status": self.status,
            "source_mode": self.source_mode,
            "updated_at": (self.updated_at.isoformat()
                           if hasattr(self.updated_at, "isoformat")
                           else str(self.updated_at)),
            "note": self.note,
        }

#: Labelled so a 409 can NAME what is in the way. Diagnosing the collision above
#: took a cross-reference of three tables against `dmesg` precisely because the
#: refusal messages said "a sweep is already running" without saying which job
#: the caller had actually lost to.
BACKTEST_RUN = "backtest run"
SWEEP = "sweep"
WEALTH_CORE_RUN = "Wealth Core run"

#: Any ONE running job disqualifies a new one, so `LIMIT 1` after the UNION is
#: sufficient — this asks "is anything running", not "what is running".
_BUSY_SQL = text(
    "SELECT kind FROM ("
    f"  SELECT '{BACKTEST_RUN}' AS kind FROM bt_runs WHERE status='running'"
    "  UNION ALL"
    f"  SELECT '{SWEEP}' AS kind FROM bt_sweeps WHERE status='running'"
    "  UNION ALL"
    f"  SELECT '{WEALTH_CORE_RUN}' AS kind FROM bt_wealth_core_runs"
    "   WHERE status='running'"
    ") AS running LIMIT 1"
)


async def running_job_kind(conn) -> str | None:
    """Which corpus-loading job is already running on this engine, if any."""
    row = (await conn.execute(_BUSY_SQL)).first()
    return row[0] if row else None


async def acquire_job_start_gate(conn) -> None:
    """Serialise one job admission transaction across engine processes."""
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": JOB_START_LOCK_KEY},
    )


async def acquire_engine_process_lease(conn) -> None:
    """Claim exclusive process ownership on a dedicated DB connection.

    The caller must keep ``conn`` open for its whole lifespan. A crashed
    process releases the PostgreSQL session lock automatically; a concurrent
    healthy process makes this function raise before schema/recovery writes.
    """
    acquired = (await conn.execute(
        text("SELECT pg_try_advisory_lock(:key)"),
        {"key": ENGINE_PROCESS_LEASE_KEY},
    )).scalar_one()
    if not acquired:
        raise EngineProcessLeaseUnavailable(
            "another bt-engine process owns this certification database; "
            "refusing startup before orphan recovery can mark its active run "
            "RESTART_ABORTED")


async def release_engine_process_lease(conn) -> None:
    """Release the lease explicitly; connection loss is the crash fallback."""
    released = (await conn.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": ENGINE_PROCESS_LEASE_KEY},
    )).scalar_one()
    if not released:
        raise RuntimeError(
            "bt-engine process lease was not held by its dedicated connection")


async def acquire_corpus_read_lock(conn) -> None:
    """Hold the corpus stable, refusing instead of queueing behind a writer."""
    acquired = (await conn.execute(
        text("SELECT pg_try_advisory_xact_lock_shared(:key)"),
        {"key": CORPUS_LOCK_KEY},
    )).scalar_one()
    if not acquired:
        raise CorpusGenerationUnavailable(
            "bt-data corpus publication is in progress; rehearsals do not "
            "queue behind or overlap a mutation generation")


async def load_ready_data_generation(conn) -> DataGeneration:
    """Read the generation identity through the caller's corpus snapshot."""
    try:
        row = (await conn.execute(text(
            "SELECT version::text, status, source_mode, updated_at, note "
            "FROM bt_data_version WHERE id = 1"
        ))).first()
    except Exception as exc:  # noqa: BLE001 -- an old schema is not citable
        raise CorpusGenerationUnavailable(
            "bt_data_version cannot supply the READY generation contract; "
            "apply the bt-data schema migration before rehearsing") from exc
    if row is None:
        raise CorpusGenerationUnavailable(
            "bt_data_version has no singleton row; no corpus generation is "
            "available for certification")
    version, status, source_mode, updated_at, note = row
    if str(status).upper() != "READY":
        raise CorpusGenerationUnavailable(
            f"bt-data corpus is {status!r}, not READY. A writer may have "
            "crashed after committing rows; resume or repair publication "
            "before rehearsing.")
    if not version or not source_mode:
        raise CorpusGenerationUnavailable(
            "READY bt_data_version is missing version or source_mode; its "
            "corpus cannot be identified")
    return DataGeneration(
        version=str(version), status="READY", source_mode=str(source_mode),
        updated_at=updated_at, note=str(note) if note is not None else None,
    )


def busy_detail(kind: str) -> str:
    """The 409 body. Says what is running and why this is a refusal, not a queue."""
    return (
        f"a {kind} is already in progress on this engine. Refused rather than "
        "queued: each job loads the whole corpus for its range, two do not fit "
        "in the container together, and the resulting OOM is recorded as a "
        "strategy failure rather than an environment failure."
    )
