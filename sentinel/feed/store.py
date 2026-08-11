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

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional, Sequence

from sentinel.feed.schema import DDL, RECLAIM_ORPHANS, RESTART_ABORT_MARKER

_BAR_UPSERT = """
    INSERT INTO sentinel_bars (security_id, session, ticker, close_signal,
        close_unadjusted, open_unadjusted, volume, split_ratio,
        dividend_per_share)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        dividend_per_share = EXCLUDED.dividend_per_share
"""

_ACTION_UPSERT = """
    INSERT INTO sentinel_actions (ticker, session, action, value, contraticker)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (ticker, session, action) DO UPDATE SET
        value = EXCLUDED.value, contraticker = EXCLUDED.contraticker
"""


def connect(dsn: str):
    """One place that imports the driver, so the rest of the package is testable
    without it installed.

    psycopg3 preferred, psycopg2 accepted. Both speak the `%s` placeholders used
    throughout this module, so the fallback changes nothing about the SQL — and
    pinning v3 alone would make the loader unrunnable on a host that has only
    the older driver, for no benefit a batch loader can use.
    """
    try:
        import psycopg                   # noqa: PLC0415 — driver choice is local
        return psycopg.connect(dsn, autocommit=False)
    except ModuleNotFoundError:
        import psycopg2                  # noqa: PLC0415
        return psycopg2.connect(dsn)


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        for stmt in DDL:
            cur.execute(stmt)
    conn.commit()


def reclaim_orphans(conn) -> int:
    """Mark runs abandoned by a dead process. Call at startup.

    Without this a crashed seed leaves a row saying `running` forever, and
    `feed-status` reports an ingest that has no process behind it — the exact
    confusion the Wealth Core rehearsal produced for half an hour.
    """
    with conn.cursor() as cur:
        cur.execute(RECLAIM_ORPHANS, {"marker": RESTART_ABORT_MARKER})
        n = cur.rowcount
    conn.commit()
    return n


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
        self.conn = conn
        self.progress = IngestProgress(run_id=str(uuid.uuid4()), kind=kind,
                                       chunks_total=chunks_total)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feed_ingest_runs (run_id, kind, date_from, date_to,"
                " chunks_total) VALUES (%s, %s, %s, %s, %s)",
                (self.progress.run_id, kind, date_from, date_to, chunks_total))
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
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE feed_ingest_runs SET status=%s, completed_at=NOW(),"
                " updated_at=NOW(), error_message=%s WHERE run_id=%s",
                (status, (error or "")[:2000] or None, self.progress.run_id))
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


def write_bars(conn, bars: Iterable[Any]) -> int:
    """Upsert bars. Accepts `NormalisedBar` or a bare `VendorBar`.

    Both shapes because the engine's VendorBar does not carry a signal close and
    tests legitimately build one directly; a bare VendorBar simply stores NULL
    there, which the readiness check then reports rather than tolerates.
    """
    rows = []
    for item in bars:
        b = getattr(item, "vendor", item)
        rows.append((b.security_id, b.session, b.ticker,
                     getattr(item, "close_signal", None),
                     b.raw_close, b.raw_open, b.volume, b.split_ratio,
                     b.dividend_per_share))
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_BAR_UPSERT, rows)
    conn.commit()
    return len(rows)


def write_actions(conn, rows: Sequence[Any]) -> int:
    payload = [
        (r["ticker"], r["date"], r["action"], r.get("value"), r.get("contraticker"))
        for r in rows
    ]
    if not payload:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_ACTION_UPSERT, payload)
    conn.commit()
    return len(payload)


def write_rejections(conn, rejections) -> int:
    """Persist rows the normaliser refused. Idempotent on (ticker, session,
    reason), so a re-ingest of the same window does not multiply them."""
    rows = [(r["ticker"], r["session"], r["reason"], r.get("close"),
             r.get("volume")) for r in rejections]
    if not rows:
        return 0
    with conn.cursor() as cur:
        # DO UPDATE, not DO NOTHING, on the price columns: a re-ingest after a
        # vendor restatement carries a corrected price, and an evidence row
        # that keeps the first value ever seen is evidence of the wrong thing.
        # The KEY is still (ticker, session, reason), so this does not multiply
        # rows — the idempotence the audit counts on is unchanged.
        cur.executemany(
            "INSERT INTO sentinel_ingest_rejections"
            " (ticker, session, reason, close_unadjusted, volume)"
            " VALUES (%s,%s,%s,%s,%s)"
            " ON CONFLICT (ticker, session, reason) DO UPDATE SET"
            " close_unadjusted = EXCLUDED.close_unadjusted,"
            " volume = EXCLUDED.volume", rows)
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


def write_anomalies(conn, anomalies) -> int:
    """Persist corpus anomalies the ingest resolved but did not resolve AWAY.

    A warning logged during a six-hour seed is not something a certification
    can consult afterwards, and these are precisely the facts a certification
    has to weigh: a split the two sources disagree about, and a distribution
    whose amount the vendor never stated.
    """
    rows = [(a["kind"], a["ticker"], a["session"], a.get("detail"))
            for a in anomalies]
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO sentinel_corpus_anomalies (kind, ticker, session,"
            " detail) VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (kind, ticker, session) DO UPDATE SET"
            " detail = EXCLUDED.detail", rows)
    conn.commit()
    return len(rows)


def rejected_tickers(conn, start: str, end: str, reason: str = "NO_IDENTITY") -> set:
    """Raw vendor tickers the ingest refused in [start, end]."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker FROM sentinel_ingest_rejections"
                    " WHERE session BETWEEN %s AND %s AND reason = %s",
                    (start, end, reason))
        return {str(t[0]).upper() for t in cur.fetchall() if t[0]}


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

    Bounded by the number of securities (~10k), not by sessions. `DISTINCT ON`
    walks the (security_id, session) primary key backwards, so this is an index
    scan rather than a corpus read.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (security_id) security_id, close_signal,"
            " close_unadjusted FROM sentinel_bars WHERE session < %s"
            " ORDER BY security_id, session DESC", (before_session,))
        return {
            str(sid): (float(c) if c is not None else None,
                       float(r) if r is not None else None)
            for sid, c, r in cur.fetchall()
        }


def latest_session(conn) -> Optional[str]:
    """The newest session in the corpus — where an incremental fetch resumes."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(session) FROM sentinel_bars")
        row = cur.fetchone()
    return None if not row or row[0] is None else str(row[0])


def run_status(conn, limit: int = 5) -> list[dict]:
    """What `feed-status` reads. Plain SELECT — no shared state with the writer,
    which is what makes it readable from another process while a seed runs."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, kind, status, started_at, updated_at, completed_at,"
            " date_from, date_to, chunks_total, chunks_done, rows_written,"
            " rows_dropped, current_chunk, error_message"
            " FROM feed_ingest_runs ORDER BY started_at DESC LIMIT %s", (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
