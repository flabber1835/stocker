"""Writing the corpus, and publishing progress while it happens.

Two properties, both learned expensively elsewhere in this repository:

**Progress commits.** Every chunk's counters are written and COMMITTED in their
own transaction, separate from the data. An in-memory snapshot is invisible to
`feed-status`, invisible to another shell, and gone the moment the process dies —
which is precisely when someone wants to know how far it got.

**Upserts are idempotent.** A re-run after an interruption resumes rather than
duplicates, which is what makes "just run it again" a safe instruction and lets
the orphan-reclaim keep the rows a dead run already committed.

Synchronous psycopg, not async. This is a batch loader with no event loop to
share and no concurrency to exploit; the async machinery would buy nothing and
cost the ability to run it from a plain script.
"""
from __future__ import annotations

import json
import math
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional, Sequence

from sentinel.feed.schema import RECLAIM_ORPHANS, RESTART_ABORT_MARKER

_BAR_UPSERT = """
    INSERT INTO sentinel_bars (security_id, session, ticker, close_signal,
        close_unadjusted, open_unadjusted, volume, split_ratio,
        dividend_per_share, last_written_run_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (security_id, session) DO UPDATE SET
        ticker = EXCLUDED.ticker,
        close_signal = EXCLUDED.close_signal,
        close_unadjusted = EXCLUDED.close_unadjusted,
        open_unadjusted = EXCLUDED.open_unadjusted,
        volume = EXCLUDED.volume,
        -- ABSENCE OF EVIDENCE MUST NOT OVERWRITE EVIDENCE.
        --
        -- 1.0 is the value `split_ratio_from_domains` returns when it has NO
        -- predecessor to compare against — it means "nothing seen", not "no
        -- split happened". An unconditional assignment therefore let the daily
        -- overlap CORRUPT the corpus at its own leading edge: the window starts
        -- 14 days behind the frontier, the first bar of each security in it has
        -- no predecessor in the stream, the derived ratio comes out 1.0, and it
        -- was written straight over a correct 2.0 that an earlier run had
        -- computed when that same session sat mid-window. The mechanism that
        -- exists to absorb vendor restatements was degrading data every day it
        -- ran, on any split ACTIONS does not cover — and the ingest's own
        -- SPLIT_ONLY_DERIVED warning exists because that set is not empty.
        --
        -- A ratio may be RAISED (1.0 -> 2.0, correcting a miss) or CHANGED
        -- (ACTIONS restating 2.0 -> 1.5). It may never be silently downgraded to
        -- "no split". Deliberately overwriting a SPURIOUS split is a REPAIR, and
        -- repairs go through sentinel/feed/repair.py where they are explicit and
        -- audited — not through the path that runs unattended every evening.
        split_ratio = CASE WHEN EXCLUDED.split_ratio = 1.0
                           THEN sentinel_bars.split_ratio
                           ELSE EXCLUDED.split_ratio END,
        dividend_per_share = EXCLUDED.dividend_per_share,
        last_written_run_id = COALESCE(EXCLUDED.last_written_run_id,
                                       sentinel_bars.last_written_run_id)
    WHERE sentinel_bars.ticker IS DISTINCT FROM EXCLUDED.ticker
       OR sentinel_bars.close_signal IS DISTINCT FROM EXCLUDED.close_signal
       OR sentinel_bars.close_unadjusted IS DISTINCT FROM EXCLUDED.close_unadjusted
       OR sentinel_bars.open_unadjusted IS DISTINCT FROM EXCLUDED.open_unadjusted
       OR sentinel_bars.volume IS DISTINCT FROM EXCLUDED.volume
       OR sentinel_bars.split_ratio IS DISTINCT FROM
          CASE WHEN EXCLUDED.split_ratio = 1.0
               THEN sentinel_bars.split_ratio
               ELSE EXCLUDED.split_ratio END
       OR sentinel_bars.dividend_per_share IS DISTINCT FROM EXCLUDED.dividend_per_share
       OR (EXCLUDED.last_written_run_id IS NOT NULL
           AND sentinel_bars.last_written_run_id IS NOT NULL
           AND sentinel_bars.last_written_run_id IS DISTINCT FROM
               EXCLUDED.last_written_run_id
           AND NOT EXISTS (
               SELECT 1 FROM sentinel_corpus_publications p
               WHERE p.run_id = sentinel_bars.last_written_run_id))
"""

_SPY_TOTAL_RETURN_UPSERT = """
    INSERT INTO sentinel_spy_total_return
        (session, closeadj, last_written_run_id) VALUES (%s, %s, %s)
    ON CONFLICT (session) DO UPDATE SET
        closeadj = EXCLUDED.closeadj,
        last_written_run_id = EXCLUDED.last_written_run_id
"""

_DEFENSIVE_BAR_UPSERT = """
    INSERT INTO sentinel_defensive_bars
        (security_id, session, ticker, open_signal, close_signal,
         close_adjusted, close_unadjusted, last_written_run_id)
    VALUES ('SENTINEL:BIL', %s, 'BIL', %s, %s, %s, %s, %s)
    ON CONFLICT (session) DO UPDATE SET
        open_signal = EXCLUDED.open_signal,
        close_signal = EXCLUDED.close_signal,
        close_adjusted = EXCLUDED.close_adjusted,
        close_unadjusted = EXCLUDED.close_unadjusted,
        last_written_run_id = EXCLUDED.last_written_run_id
"""

_ACTION_UPSERT = """
    INSERT INTO sentinel_actions (ticker, session, action, value, contraticker,
        last_written_run_id)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (ticker, session, action) DO UPDATE SET
        value = EXCLUDED.value, contraticker = EXCLUDED.contraticker,
        -- COALESCE, exactly as the bar upsert does it: a caller that supplies
        -- no run must not erase the provenance an ingest recorded, or a repair
        -- tool would silently make published rows unattributable.
        last_written_run_id = COALESCE(EXCLUDED.last_written_run_id,
                                       sentinel_actions.last_written_run_id)
"""


def connect(dsn: str, *, connect_timeout: int | None = None,
            statement_timeout_ms: int | None = None):
    """One place that imports the driver, so the rest of the package is testable
    without it installed.

    psycopg3 preferred, psycopg2 accepted. Both speak the `%s` placeholders used
    throughout this module, so the fallback changes nothing about the SQL — and
    pinning v3 alone would make the loader unrunnable on a host that has only
    the older driver, for no benefit a batch loader can use.
    """
    try:
        import psycopg                   # noqa: PLC0415 — driver choice is local
        kwargs = {"autocommit": False}
        if connect_timeout is not None:
            kwargs["connect_timeout"] = int(connect_timeout)
        if statement_timeout_ms is not None:
            kwargs["options"] = (
                f"-c statement_timeout={int(statement_timeout_ms)}")
        return psycopg.connect(dsn, **kwargs)
    except ModuleNotFoundError:
        import psycopg2                  # noqa: PLC0415
        kwargs = {}
        if connect_timeout is not None:
            kwargs["connect_timeout"] = int(connect_timeout)
        if statement_timeout_ms is not None:
            kwargs["options"] = (
                f"-c statement_timeout={int(statement_timeout_ms)}")
        return psycopg2.connect(dsn, **kwargs)


@contextmanager
def corpus_write_lock(conn):
    """Hold the corpus STILL for the duration of an ingest.

    ## Why publication alone was not enough

    `publication.visible_predicate` made a row visible when its current
    `last_written_run_id` belongs to a published run, and `publication.pinned`
    stopped a new PUBLICATION landing mid-session. Neither stopped the ROWS
    moving, and `sentinel_bars` is a destructive in-place upsert:

    ```text
    v41 published, AAA/2026-08-10 visible
    a session pins v41 and starts reading
    the daily ingest UPSERTs AAA/2026-08-10 -> last_written_run_id = run42
    the predicate now HIDES that row
    the same calculation, still nominally on v41, sees a different corpus
    ```

    The version number never moved. The snapshot it names did. A bar can vanish
    mid-window or come back with a restated split ratio — the second does not
    even change the row count — and the decision carries `data_version = 41`
    describing a state that never existed as a whole.

    "Published is what readable means" is the right rule for a corpus that only
    GROWS. Against one rewritten in place, the predicate is re-evaluated per
    query and what it evaluates is mutable.

    ## Why a lock rather than generations

    A generation column with an atomic pointer move is the better end state and
    is the RECONSTRUCTION tier §8 defers. It answers "show me v47", which this
    does not. It also changes the write path, the read path, repair, coherence
    and every test that touches the hottest table in the system, and a daily
    ingest that re-fetches a 14-day overlap would need content-change detection
    or it writes 140k redundant rows a night.

    This is the subset of that guarantee needed to close the hazard, and it is
    needed under generations too: the pointer move must still exclude a reader
    mid-snapshot. Single-writer, one decision per session, ingest in the
    evening — the exclusion costs nothing this appliance actually does
    concurrently.

    ## The lock is the SAME key readers pin

    `publication.CORPUS_LOCK_KEY`, taken EXCLUSIVE. A reader's shared pin and an
    ingest's exclusive hold are then mutually exclusive by construction rather
    than by two modules agreeing to be careful. Advisory, so it releases if the
    holder's connection dies — an ingest killed mid-chunk must not lock the
    corpus until someone notices.
    """
    from sentinel.feed.publication import CORPUS_LOCK_KEY, CorpusBusy

    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (CORPUS_LOCK_KEY,))
        if not bool(cur.fetchone()[0]):
            raise CorpusBusy(
                "the corpus is PINNED by a reader (or another ingest holds the "
                "write lock); refusing to write. Rewriting a row a session is "
                "reading would change what its recorded data_version describes "
                "— the version would not move and the snapshot would.")
    conn.commit()
    try:
        yield
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (CORPUS_LOCK_KEY,))
        conn.commit()


def _assert_corpus_locked(conn) -> None:
    """The write lock is HELD by this connection. Enforced, not documented.

    A prerequisite in a docstring is one the next ingest path can simply not
    follow, and this one is the difference between a stable snapshot and a
    plausible wrong number. `pg_locks` is the authority — asking the lock
    manager is exact, where a module-level flag would be a second copy of the
    truth that can drift from it.
    """
    from sentinel.feed.publication import CORPUS_LOCK_KEY, CorpusBusy

    key = CORPUS_LOCK_KEY
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM pg_locks WHERE locktype = 'advisory'"
            " AND pid = pg_backend_pid() AND granted"
            "   AND ((classid::bigint << 32) | objid::bigint) = %s"
            "   AND mode = 'ExclusiveLock'", (key,))
        held = int(cur.fetchone()[0])
    if not held:
        raise CorpusBusy(
            "write_bars was called without the corpus write lock. Wrap the "
            "ingest in `store.corpus_write_lock(conn)`: an in-place upsert "
            "while a session has the corpus pinned changes what that "
            "session's data_version describes.")


@contextmanager
def streaming_cursor(conn, sql: str, params=(), *, batch: int = 5000,
                     withhold: bool = False):
    """A SERVER-SIDE cursor. Rows arrive in batches and are never all resident.

    `cur.fetchall()` materialises the entire result client-side, and every caller
    in this codebase then walks it to build a second complete object graph — so
    both representations coexist at peak, on the machine whose memory ceiling is
    the binding constraint for the whole deployment. `fetchmany` on an ordinary
    cursor does not help: the driver has already buffered everything.

    A NAMED cursor is what actually changes the arithmetic, and both drivers
    spell it the same way (`conn.cursor(name=...)` plus `itersize`), so this
    needs no version branch. The connection is opened with `autocommit=False`,
    which is the condition a portal requires.

    `withhold` keeps the cursor alive ACROSS COMMITS. An ordinary portal is
    destroyed by COMMIT, which matters for exactly one caller and matters
    absolutely: the ingest reads staged rows through this cursor while
    `write_bars` commits the resulting bars every 5,000 rows, so the reader's own
    consumer closes the cursor out from under it — `InvalidCursorName`, partway
    through a chunk. PostgreSQL pays for it by materialising the remaining rows
    into a TEMP FILE at that commit, which keeps the memory bound this whole
    change exists for; the copy is on the database's disk, not in the trading
    process's heap.

    FALLS BACK to a client-side cursor when the driver refuses a named one — an
    unnamed-cursor read is slower on memory but still CORRECT, and a loader that
    raises because a fake connection in a test cannot declare a portal would
    trade a real property for a synthetic one.
    """
    name = f"sentinel_stream_{uuid.uuid4().hex}"
    try:
        cur = conn.cursor(name=name, withhold=withhold)
        cur.itersize = batch
    except Exception:                                         # noqa: BLE001
        cur = conn.cursor()
    try:
        cur.execute(sql, params)
        yield cur
    finally:
        try:
            cur.close()
        except Exception:                                     # noqa: BLE001
            pass


def migrate_schema(conn) -> None:
    """Apply feed DDL through the guarded explicit migration path."""
    from sentinel.feed.runtime_schema import migrate_feed_schema

    migrate_feed_schema(conn)


def require_feed_schema(conn) -> None:
    """Fail closed unless the installed feed schema has the reviewed shape."""
    from sentinel.feed.runtime_schema import require_feed_schema as require_schema

    require_schema(conn)


def reclaim_orphans(conn) -> int:
    """Mark runs abandoned by a dead process. Call at startup.

    Without this a crashed seed leaves a row saying `running` forever, and
    `feed-status` reports an ingest that has no process behind it — the exact
    confusion the Wealth Core rehearsal produced for half an hour.
    """
    from sentinel.feed import actions as action_store
    from sentinel.feed import anomalies as anomaly_store

    # Taking the writer lock proves that no live ingest still owns a candidate.
    # The run failure and anomaly ABORTED events then commit together.
    with corpus_write_lock(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT run_id FROM feed_ingest_runs"
                        " WHERE status='running' FOR UPDATE")
            run_ids = [str(row[0]) for row in cur.fetchall()]
            if run_ids:
                cur.execute(RECLAIM_ORPHANS,
                            {"marker": RESTART_ABORT_MARKER})
                if cur.rowcount != len(run_ids):
                    raise RuntimeError(
                        "orphan run set changed while holding the writer lock")
        # A schema-upgraded or interrupted older build may have durably marked
        # the ingest failed while leaving a PR86 candidate lifecycle PENDING.
        # Ordinary feed startup retires that state too; recovery never requires
        # hand-written SQL.
        with conn.cursor() as cur:
            cur.execute("SELECT run_id FROM feed_ingest_runs WHERE status='failed'")
            failed_run_ids = [str(row[0]) for row in cur.fetchall()]
        for run_id in run_ids:
            action_store.abort_run(
                conn, run_id=run_id, actor_run_id=run_id,
                reason=f"{RESTART_ABORT_MARKER}: writer process did not survive")
            anomaly_store.abort_run(
                conn, run_id=run_id, actor_run_id=run_id,
                reason=f"{RESTART_ABORT_MARKER}: writer process did not survive")
        for run_id in failed_run_ids:
            action_store.abort_run(
                conn, run_id=run_id, actor_run_id=run_id,
                reason="feed startup: durably failed ingest candidate retired")
            anomaly_store.abort_run(
                conn, run_id=run_id, actor_run_id=run_id,
                reason="feed startup: durably failed ingest candidate retired")
        conn.commit()
        return len(run_ids)


@dataclass
class IngestProgress:
    """A live run's counters. Mutated in memory, flushed per chunk."""

    run_id: str
    kind: str
    chunks_total: int = 0
    chunks_done: int = 0
    rows_written: int = 0
    rows_dropped: int = 0
    current_chunk: Optional[str] = None

    @property
    def pct(self) -> float:
        return 0.0 if not self.chunks_total else 100.0 * self.chunks_done / self.chunks_total


class IngestRun:
    """Opens a `feed_ingest_runs` row and keeps it honest."""

    def __init__(self, conn, kind: str, *, date_from=None, date_to=None,
                 chunks_total: int = 0) -> None:
        from sentinel.identity import require_feed_producer_identity

        producer = require_feed_producer_identity()
        self.conn = conn
        self.progress = IngestProgress(run_id=str(uuid.uuid4()), kind=kind,
                                       chunks_total=chunks_total)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feed_ingest_runs (run_id, kind, date_from, date_to,"
                " chunks_total, source_git_commit, runtime_image_digest)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (self.progress.run_id, kind, date_from, date_to, chunks_total,
                 producer["git_commit"], producer["runtime_image_digest"]))
        conn.commit()

    def publish(self) -> None:
        """Flush counters in their OWN transaction.

        Deliberately separate from the data write. Sharing one transaction would
        make progress invisible until the chunk committed — and invisible
        forever if it rolled back, which is the case a watcher most needs to see.
        """
        p = self.progress
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE feed_ingest_runs SET chunks_done=%s, rows_written=%s,"
                " rows_dropped=%s, current_chunk=%s, updated_at=NOW()"
                " WHERE run_id=%s",
                (p.chunks_done, p.rows_written, p.rows_dropped,
                 p.current_chunk, p.run_id))
        self.conn.commit()

    def finish(self, status: str = "success", error: str | None = None) -> None:
        from sentinel.feed import actions as action_store
        from sentinel.feed import anomalies as anomaly_store

        if status == "failed" and (
                action_store.has_pending(
                    self.conn, run_id=self.progress.run_id)
                or anomaly_store.has_pending(
                    self.conn, run_id=self.progress.run_id)):
            _assert_corpus_locked(self.conn)
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE feed_ingest_runs SET status=%s, completed_at=NOW(),"
                " updated_at=NOW(), error_message=%s WHERE run_id=%s",
                (status, (error or "")[:2000] or None, self.progress.run_id))
        if status == "failed":
            action_store.abort_run(
                self.conn, run_id=self.progress.run_id,
                actor_run_id=self.progress.run_id,
                reason=(error or "ingest failed")[:2000])
            anomaly_store.abort_run(
                self.conn, run_id=self.progress.run_id,
                actor_run_id=self.progress.run_id,
                reason=(error or "ingest failed")[:2000])
        self.conn.commit()

    @contextmanager
    def chunk(self, label: str) -> Iterator[IngestProgress]:
        """One unit of work. Publishes on entry so the CURRENT chunk is visible
        while it runs, and again on exit with the count."""
        self.progress.current_chunk = label
        self.publish()
        try:
            yield self.progress
        except BaseException as exc:      # noqa: BLE001 — recorded, then re-raised
            self.finish("failed", f"{type(exc).__name__} at {label}: {exc}")
            raise
        self.progress.chunks_done += 1
        self.publish()


#: Rows buffered before a flush. Peak memory becomes O(batch), not O(chunk).
WRITE_BATCH = int(os.getenv("SENTINEL_WRITE_BATCH", "5000"))


def write_bars(conn, bars: Iterable[Any], *, run_id=None,
               batch_size: int = 0, require_lock: bool = False) -> int:
    """Upsert bars, STREAMING. Accepts `NormalisedBar` or a bare `VendorBar`.

    Both shapes because the engine's VendorBar does not carry a signal close and
    tests legitimately build one directly; a bare VendorBar simply stores NULL
    there, which the readiness check then reports rather than tolerates.

    **BOUNDED.** This used to drain the whole generator into one list before
    writing anything, so a seed year was resident TWICE — once as the sorted
    vendor rows and again as tuples — on a NAS whose memory ceiling is the
    binding constraint for the entire deployment. Flushing per batch makes the
    second copy O(batch).

    The vendor-side sort in `ingest._sorted_sep` is still O(chunk) and cannot be
    removed the same way: the ratio derivation requires session order and the
    HTTP API promises none. Reducing that one needs a staging table, which is a
    separate change; this is the half that was free.

    `run_id` stamps `last_written_run_id`, which answers "which ingest produced
    this value" without any revision history — the cheap half of the corpus
    versioning contract.

    `require_lock` asserts the caller holds `corpus_write_lock`. Every INGEST
    path passes it: an in-place upsert while a session has the corpus pinned
    changes what that session's `data_version` describes, and the version does
    not move to say so. It is a parameter rather than unconditional because
    hundreds of fixtures build a corpus directly with no reader in sight, and a
    check that forces every one of them through a lock buys nothing and teaches
    people to reach past it.
    """
    if require_lock:
        _assert_corpus_locked(conn)
    size = batch_size or WRITE_BATCH
    rows: list = []
    written = 0

    def flush() -> None:
        nonlocal written
        if not rows:
            return
        with conn.cursor() as cur:
            cur.executemany(_BAR_UPSERT, [r[:10] for r in rows])
        # COMMIT PER BATCH, matching the rest of this module: an interrupted
        # ingest keeps the rows it got, and the upserts are idempotent so the
        # re-run resumes rather than duplicates.
        conn.commit()
        written += len(rows)
        rows.clear()

    for item in bars:
        b = getattr(item, "vendor", item)
        rows.append((b.security_id, b.session, b.ticker,
                     getattr(item, "close_signal", None),
                     b.raw_close, b.raw_open, b.volume, b.split_ratio,
                     b.dividend_per_share, str(run_id) if run_id else None,
                     getattr(item, "close_total_return", None)))
        if len(rows) >= size:
            flush()
    flush()
    return written


def write_spy_total_return(conn, rows: Iterable[Any], *, run_id=None,
                           batch_size: int = 0,
                           require_lock: bool = False) -> int:
    """Persist only bounded SFP SPY total-return rows.

    SPY is a fund and never enters ``sentinel_bars`` or the Wealth Core equity
    universe. Invalid/non-SPY rows are refused rather than broadening this
    membrane into a general fund ingest.
    """
    if require_lock:
        _assert_corpus_locked(conn)
    size = batch_size or WRITE_BATCH
    payload: list[tuple] = []
    written = 0

    def flush() -> None:
        nonlocal written
        if not payload:
            return
        with conn.cursor() as cur:
            cur.executemany(_SPY_TOTAL_RETURN_UPSERT, payload)
        conn.commit()
        written += len(payload)
        payload.clear()

    for row in rows:
        if str(row.get("ticker", "")).upper() != "SPY":
            raise ValueError("the SFP readiness ingest accepts only ticker=SPY")
        session = str(row.get("date") or "")
        value = row.get("closeadj")
        try:
            closeadj = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"SPY SFP row {session} has invalid closeadj") from exc
        if not session or closeadj <= 0 or not math.isfinite(closeadj):
            raise ValueError(f"SPY SFP row {session!r} has invalid closeadj")
        payload.append((session, closeadj, str(run_id) if run_id else None))
        if len(payload) >= size:
            flush()
    flush()
    return written


def write_defensive_bars(conn, rows: Iterable[Any], *, run_id=None,
                         batch_size: int = 0,
                         require_lock: bool = False) -> int:
    """Persist the exact consumed BIL SFP fields under its fixed identity.

    The canonical adjusted open is intentionally not stored as another source
    fact. Consumers derive it as ``open * closeadj / close`` from these retained
    fields, preserving the source seam and making every input to next-open
    scalar accounting independently hashable.
    """
    if require_lock:
        _assert_corpus_locked(conn)
    size = batch_size or WRITE_BATCH
    payload: list[tuple] = []
    written = 0

    def flush() -> None:
        nonlocal written
        if not payload:
            return
        with conn.cursor() as cur:
            cur.executemany(_DEFENSIVE_BAR_UPSERT, payload)
        conn.commit()
        written += len(payload)
        payload.clear()

    for row in rows:
        if str(row.get("ticker", "")).strip().upper() != "BIL":
            raise ValueError("the defensive SFP ingest accepts only ticker=BIL")
        session = str(row.get("date") or "")
        try:
            open_signal = float(row.get("open"))
            close_signal = float(row.get("close"))
            close_adjusted = float(row.get("closeadj"))
            close_unadjusted = float(row.get("closeunadj"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"BIL SFP row {session!r} lacks valid "
                "open/close/closeadj/closeunadj") from exc
        values = (open_signal, close_signal, close_adjusted, close_unadjusted)
        if (not session or any(value <= 0 or not math.isfinite(value)
                               for value in values)):
            raise ValueError(
                f"BIL SFP row {session!r} lacks valid "
                "open/close/closeadj/closeunadj")
        payload.append((session, open_signal, close_signal, close_adjusted,
                        close_unadjusted,
                        str(run_id) if run_id else None))
        if len(payload) >= size:
            flush()
    flush()
    return written


def write_actions(conn, rows: Sequence[Any], *, run_id=None,
                  window_start: str | None = None,
                  window_end: str | None = None) -> int:
    """Persist one COMPLETE corporate-action source snapshot.

    A run-stamped call is append-only.  It records every current row as PRESENT
    and every previously active key missing from the explicitly fetched window
    as REMOVED.  Publication, not insertion, activates those observations.  An
    empty complete response is therefore meaningful and must not return early.

    Calls without ``run_id`` retain the legacy/test upsert surface.  Those rows
    form the immutable pre-upgrade baseline read by ``sentinel_active_actions``;
    production ingest always supplies a run and complete window.
    """
    if run_id is None:
        payload = [
            (r["ticker"], r["date"], r["action"], r.get("value"),
             r.get("contraticker"), None) for r in rows
        ]
        if not payload:
            return 0
        with conn.cursor() as cur:
            cur.executemany(_ACTION_UPSERT, payload)
        conn.commit()
        return len(payload)

    _assert_corpus_locked(conn)
    if window_start is None or window_end is None:
        raise ValueError(
            "a run-stamped ACTIONS write must name the complete fetched window")
    lo, hi = str(window_start), str(window_end)
    if lo > hi:
        raise ValueError(f"reversed ACTIONS window: {lo} > {hi}")
    writer = str(run_id)

    from sentinel.feed import action_source

    current: dict[str, tuple] = {}
    for identity, payload, row in action_source.distinct_rows(rows):
        ticker, session, action = (str(row["ticker"]), str(row["date"]),
                                   str(row["action"]))
        if not lo <= session <= hi:
            raise ValueError(
                f"ACTIONS row {ticker}/{session}/{action} lies outside the "
                f"declared complete window [{lo}, {hi}]")
        item = (identity, json.dumps(
                    payload, sort_keys=True, separators=(",", ":")),
                ticker, session, action, row.get("name"), row.get("value"),
                row.get("contraticker"), row.get("contraname"),
                "PRESENT", writer)
        current[identity] = item

    # Reconcile against the PUBLISHED active generation, never against another
    # unpublished attempt.  A failed retry therefore cannot become the baseline
    # from which a later retry silently reasons.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_row_id,source_payload,ticker,session,action,name,"
            " value,contraticker,contraname"
            " FROM sentinel_active_actions"
            " WHERE session BETWEEN %s AND %s", (lo, hi))
        prior = list(cur.fetchall())

    observations = list(current.values())
    for (identity, payload, ticker, session, action, name, value, contraticker,
         contraname) in prior:
        identity = str(identity)
        if identity not in current:
            observations.append((identity, json.dumps(
                                     payload, sort_keys=True, default=str),
                                 str(ticker), str(session), str(action), name,
                                 value, contraticker, contraname,
                                 "REMOVED", writer))

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_action_generations"
            " (last_written_run_id,window_start,window_end,source_rows)"
            " VALUES (%s,%s,%s,%s) ON CONFLICT (last_written_run_id) DO NOTHING",
            (writer, lo, hi, len(current)))
        cur.execute(
            "SELECT window_start,window_end,source_rows"
            " FROM sentinel_action_generations WHERE last_written_run_id=%s",
            (writer,))
        recorded = cur.fetchone()
        if (str(recorded[0]), str(recorded[1]), int(recorded[2])) != (
                lo, hi, len(current)):
            raise ValueError(
                f"ACTIONS generation {writer} was already recorded with a "
                "different complete-window contract")
        if observations:
            cur.executemany(
                "INSERT INTO sentinel_action_observations"
                " (source_row_id,source_payload,ticker,session,action,name,value,"
                "  contraticker,contraname,disposition,last_written_run_id)"
                " VALUES (%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (last_written_run_id,source_row_id)"
                " DO NOTHING", observations)
        from sentinel.feed import actions as action_store
        action_store.record_pending(conn, run_id=writer)
    conn.commit()
    return len(current)


def write_rejections(conn, rejections, *, run_id=None) -> int:
    """Append refused vendor rows at ingest-generation grain.

    A rejection is evidence about one candidate generation, not a mutable fact
    about a ticker/date forever.  Production callers stamp the ingest run so a
    later successful publication can resolve the rejection without deleting the
    history that proves the earlier corpus was defective.  ``run_id=None`` is
    retained only for legacy/tests and keeps its old idempotent key.
    """
    writer = None if run_id is None else str(run_id)
    rows = [(r["ticker"], r["session"], r["reason"], r.get("close"),
             r.get("volume"), writer) for r in rejections]
    if not rows:
        return 0
    with conn.cursor() as cur:
        if writer is None:
            cur.executemany(
                "INSERT INTO sentinel_ingest_rejections"
                " (ticker,session,reason,close_unadjusted,volume,last_written_run_id)"
                " VALUES (%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (ticker,session,reason)"
                " WHERE last_written_run_id IS NULL DO UPDATE SET"
                " close_unadjusted=EXCLUDED.close_unadjusted,"
                " volume=EXCLUDED.volume", rows)
        else:
            cur.executemany(
                "INSERT INTO sentinel_ingest_rejections"
                " (ticker,session,reason,close_unadjusted,volume,last_written_run_id)"
                " VALUES (%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (ticker,session,reason,last_written_run_id)"
                " WHERE last_written_run_id IS NOT NULL DO UPDATE SET"
                " close_unadjusted=EXCLUDED.close_unadjusted,"
                " volume=EXCLUDED.volume", rows)
    conn.commit()
    return len(rows)


def write_rejection_truncation(conn, *, run_id, chunk: str, window_start: str,
                               window_end: str, retained: int,
                               truncated: int) -> None:
    """Record that rejection evidence was DROPPED, and how much of it.

    Written even when `truncated` is 0 would be noise, so this is called only
    when evidence was actually lost. That makes a row here mean exactly one
    thing: this window's refusal evidence is incomplete, so no claim resting on
    having examined every refused row is available for it.
    """
    if not truncated:
        return
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_rejection_truncation"
            " (run_id, chunk, window_start, window_end, retained, truncated)"
            " VALUES (%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (run_id, chunk) DO UPDATE SET"
            " retained = EXCLUDED.retained, truncated = EXCLUDED.truncated",
            (str(run_id), str(chunk), window_start, window_end,
             int(retained), int(truncated)))
    conn.commit()


def write_anomalies(conn, anomalies, *, run_id=None, require_lock: bool = False,
                    commit: bool = True) -> int:
    """Append corpus-anomaly observations for one candidate generation.

    A warning logged during a six-hour seed is not something a certification
    can consult afterwards. Publication, not insertion, makes a stamped row the
    active disposition. An unpublished correction therefore cannot erase the
    previous blocker. Calls without a run id are the legacy/test baseline.
    """
    if require_lock:
        _assert_corpus_locked(conn)
    writer = None if run_id is None else str(run_id)
    rows = [(a["kind"], a["ticker"], a["session"], a.get("detail"), writer)
            for a in anomalies]
    if not rows:
        return 0
    from sentinel.feed import anomalies as anomaly_store

    with conn.cursor() as cur:
        for row in rows:
            if writer is None:
                cur.execute(
                    "INSERT INTO sentinel_corpus_anomalies"
                    " (kind,ticker,session,detail,last_written_run_id)"
                    " VALUES (%s,%s,%s,%s,%s)"
                    " ON CONFLICT (kind,ticker,session)"
                    " WHERE last_written_run_id IS NULL DO UPDATE SET"
                    " detail=EXCLUDED.detail RETURNING observation_id", row)
            else:
                cur.execute(
                    "WITH inserted AS ("
                    " INSERT INTO sentinel_corpus_anomalies"
                    " (kind,ticker,session,detail,last_written_run_id)"
                    " VALUES (%s,%s,%s,%s,%s)"
                    " ON CONFLICT (kind,ticker,session,last_written_run_id)"
                    " WHERE last_written_run_id IS NOT NULL DO NOTHING"
                    " RETURNING observation_id)"
                    " SELECT observation_id FROM inserted UNION ALL"
                    " SELECT observation_id FROM sentinel_corpus_anomalies"
                    " WHERE kind=%s AND ticker=%s AND session=%s"
                    "   AND last_written_run_id=%s LIMIT 1",
                    row + (row[0], row[1], row[2], row[4]))
            observation_id = int(cur.fetchone()[0])
            if writer is not None:
                anomaly_store.record_pending(
                    conn, observation_id, run_id=writer)
    if commit:
        conn.commit()
    return len(rows)


def rejected_tickers(conn, start: str, end: str, reason: str = "NO_IDENTITY") -> set:
    """Raw vendor tickers with CURRENTLY active published refusals."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker FROM sentinel_active_ingest_rejections"
                    " WHERE session BETWEEN %s AND %s AND reason = %s",
                    (start, end, reason))
        return {str(t[0]).upper() for t in cur.fetchall() if t[0]}


_PREVIOUS_OBSERVATIONS_SQL = """
WITH RECURSIVE security_ids(security_id) AS (
    (SELECT b.security_id
       FROM sentinel_bars b
      ORDER BY b.security_id
      LIMIT 1)
    UNION ALL
    SELECT next_id.security_id
      FROM security_ids prior
      CROSS JOIN LATERAL (
        SELECT b.security_id
          FROM sentinel_bars b
         WHERE b.security_id > prior.security_id
         ORDER BY b.security_id
         LIMIT 1
      ) next_id
)
SELECT ids.security_id, previous.close_signal, previous.close_unadjusted
  FROM security_ids ids
  CROSS JOIN LATERAL (
    SELECT b.close_signal, b.close_unadjusted
      FROM sentinel_bars b
     WHERE b.security_id = ids.security_id
       AND b.session < %s
     ORDER BY b.session DESC
     LIMIT 1
  ) previous
"""


def previous_observations(conn, before_session: str) -> dict:
    """`security_id -> (close_signal, close_unadjusted)` for the last bar each
    security printed STRICTLY BEFORE `before_session`.

    This is what lets a windowed ingest recover a split that lands on the first
    bar of its window. `normalise_sep_rows` derives the ratio by comparing a bar
    against the previous observation of the SAME security, and it starts each
    call with an empty map — so the leading edge of every seed year and every
    daily window was computed against nothing and came out 1.0.

    **A LOOKBACK WINDOW CANNOT SUBSTITUTE FOR THIS QUERY.** A security can be
    sparse for weeks, so no finite margin bounds how far back its predecessor
    lies; that is precisely why chunking the canonical LOADER was withdrawn in
    926b313 and cannot be rescued by widening one. The ingest is a different
    case only because it has a corpus to consult — the loader, mid-window, does
    not.

    Keyed on `security_id`, never the ticker: a reused symbol would otherwise
    hand one company's previous close to another and derive a split from the
    splice.

    Bounded by SECURITIES, not corpus history. The recursive term is a loose
    index walk: each step seeks to the first `security_id` greater than the one
    just returned, so it visits each security group once instead of reading all
    of its sessions. The lateral predecessor probe then fixes that security_id,
    applies the strict date bound, and takes `ORDER BY session DESC LIMIT 1`.
    `idx_sentinel_bars_predecessor` supplies the mixed ordering and both close
    columns, avoiding both the old global sort and a heap read per security.

    Do not replace this with `DISTINCT ON`. A matching mixed-order index removes
    its Sort node, but on PostgreSQL releases without a useful loose/skip scan it
    can still walk every qualifying historical index entry before `Unique`
    collapses them — cheaper than the defect in #162, but still lifetime-sized.
    """
    with conn.cursor() as cur:
        cur.execute(_PREVIOUS_OBSERVATIONS_SQL, (before_session,))
        return {
            str(sid): (float(c) if c is not None else None,
                       float(r) if r is not None else None)
            for sid, c, r in cur.fetchall()
        }


def latest_session(conn) -> Optional[str]:
    """The newest session PHYSICALLY present — where an incremental fetch resumes.

    DELIBERATELY UNFILTERED, and the pair with `latest_visible_session` below is
    the point. A writer and a reader want different answers here:

    ```text
    ingest resume point   the newest row that EXISTS, published or not. Filtering
                          would re-fetch an unpublished ingest's window every
                          evening, forever, and never notice
    reader frontier       the newest row a decision may READ. Publication decides
    ```

    One function answering both is how the two views silently diverge.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(session) FROM sentinel_bars")
        row = cur.fetchone()
    return None if not row or row[0] is None else str(row[0])


def latest_visible_session(conn) -> Optional[str]:
    """The newest session a DECISION may read. See `latest_session` above.

    Used wherever a frontier is reported to a human or fed to the engine, so the
    number on the page is the number the loader will actually use. Reporting the
    physical frontier while reading the published one is the same
    two-views-of-one-fact defect the ownership readers had.
    """
    from sentinel.feed.publication import visible_predicate

    with conn.cursor() as cur:
        cur.execute(f"SELECT MAX(session) FROM sentinel_bars b"
                    f" WHERE {visible_predicate('b')}")
        row = cur.fetchone()
    return None if not row or row[0] is None else str(row[0])


def published_spy_total_return(conn, start: str, end: str) -> list[tuple]:
    """The published SPY sensor rows in an inclusive dated window.

    This is the narrow persistence membrane already permitted to transport the
    total-return column. Readiness and identity consume opaque dated values;
    neither becomes another strategy reader of that otherwise-forbidden domain.
    """
    from sentinel.feed.publication import visible_predicate

    with conn.cursor() as cur:
        cur.execute(
            "SELECT session, closeadj FROM sentinel_spy_total_return r"
            " WHERE session BETWEEN %s AND %s"
            f" AND {visible_predicate('r')} ORDER BY session", (start, end))
        return [(str(session), value) for session, value in cur.fetchall()]


def published_defensive_bars(conn, start: str, end: str) -> list[tuple]:
    """Published BIL source fields in an inclusive dated window."""
    from sentinel.feed.publication import visible_predicate

    with conn.cursor() as cur:
        cur.execute(
            "SELECT session, security_id, ticker, open_signal, close_signal,"
            " close_adjusted, close_unadjusted FROM sentinel_defensive_bars b"
            " WHERE session BETWEEN %s AND %s"
            f" AND {visible_predicate('b')} ORDER BY session", (start, end))
        return [(str(session), security_id, ticker, open_signal, close_signal,
                 close_adjusted, raw_close)
                for session, security_id, ticker, open_signal, close_signal,
                close_adjusted, raw_close in cur.fetchall()]


def run_status(conn, limit: int = 5) -> list[dict]:
    """What `feed-status` reads. Plain SELECT — no shared state with the writer,
    which is what makes it readable from another process while a seed runs."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, kind, status, started_at, updated_at, completed_at,"
            " date_from, date_to, chunks_total, chunks_done, rows_written,"
            " rows_dropped, current_chunk, error_message, source_git_commit,"
            " runtime_image_digest"
            " FROM feed_ingest_runs ORDER BY started_at DESC LIMIT %s", (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
