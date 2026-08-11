"""The chunk sort, moved out of the interpreter and into the database.

## What this replaces

```python
def _sorted_sep(rows):
    return sorted(rows, key=lambda r: (str(r["date"]), str(r["ticker"])))
```

`normalise_sep_rows` refuses an out-of-order stream, and it is right to: the
split ratio is recovered from the previous observation of the same security, so
unordered rows produce ratios against the wrong bar — silently, permanently, in
the stored share counts. The vendor's HTTP API cursor-pages and promises no
order, so the ordering has to be imposed somewhere.

`sorted()` imposed it by keeping the entire chunk alive at once. A chunk is a
calendar year of the whole universe: ~10,000 securities x ~252 sessions is ~2.5M
vendor dicts, and dicts of that shape run 400-700 bytes each in CPython. That is
1-2 GB for the list alone, against the 2g container ceiling in
`docker-compose.sentinel.yml`, before a single bar is normalised.

The old docstring said the sort was done "at the call site that can afford it —
one chunk is a year, not a corpus". Both halves are true and the conclusion does
not follow: a universe-scale year is exactly what could not be afforded.

## Why a table rather than a smaller sort

There is no in-process arrangement that fixes this. A merge sort over spill
files is a database, written badly, in the trading process. Chunking finer
changes the constant and not the shape, and it cannot go below a session without
breaking the very ordering the sort exists to produce.

PostgreSQL already sorts with bounded memory: above `work_mem` it switches to an
external merge and spills to disk. The database is open, it is the thing that
will hold the result anyway, and its sorter has the property the interpreter's
does not.

## UNLOGGED, and what that means when it crashes

The table is scratch. Every row in it is a verbatim copy of something the vendor
will serve again, so the recovery for losing it is to re-fetch the chunk — which
is what a resumed ingest does regardless. WAL-logging 2.5M scratch rows a night
to protect data that is cheaper to re-acquire than to replay is the wrong trade,
and after an unclean shutdown PostgreSQL truncates unlogged tables, which is the
correct disposition for a partial chunk rather than a hazard.

Nothing durable is ever read from here. `sentinel_bars` is the corpus.

## Keyed on the run, not just the chunk

A crashed ingest leaves rows behind — `feed_ingest_runs` has a reclaim path
because that happens. If the next run read them as its own it would splice two
fetches into one ordered stream and derive ratios across the seam. So reads are
scoped to `(run_id, chunk)`, and `stage` clears that scope before writing: a
resumed chunk re-fetches, and appending would present every row twice, with the
second copy deriving a 1.0 "no split" against the first.
"""
from __future__ import annotations

from typing import Iterable, Iterator, Optional

#: The vendor fields carried across. Anything not here arrives as None on the
#: far side, and None is a plausible value for every one of them — so this set
#: is asserted against what `domains.normalise_sep_rows` actually reads, in
#: tests/sentinel/test_ingest_memory.py. Add a key to the normaliser without a
#: column here and that test fails rather than a corpus degrading.
#:
#: `high`, `low`, `closeadj` and `lastupdated` are deliberately NOT carried.
#: `closeadj` is the total-return series and is enforced-unread by test; the
#: others are read by nothing. Copying them would triple the scratch write for
#: columns no consumer exists for.
CARRIED = frozenset({"ticker", "date", "open", "close", "closeunadj", "volume"})

#: Same size as `store.WRITE_BATCH`, and for the same reason: the point of
#: staging is that no stage holds more than a batch, so the buffer here must be
#: bounded exactly like the one on the way out.
STAGE_BATCH = 5000

_INSERT = """
    INSERT INTO sentinel_sep_staging
        (run_id, chunk, session, ticker, open, close, closeunadj, volume)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""


def stage(conn, rows: Iterable[dict], *, run_id: str, chunk: str) -> int:
    """Stream vendor rows into scratch. Returns how many were written.

    STREAMED, in batches, and that is the whole point — `rows` is consumed one
    at a time and never materialised. A `list(rows)` anywhere in this function
    would reintroduce exactly the resident chunk it exists to remove.
    """
    clear(conn, run_id=run_id, chunk=chunk)

    buf: list = []
    written = 0

    def flush() -> None:
        nonlocal written
        if not buf:
            return
        with conn.cursor() as cur:
            cur.executemany(_INSERT, buf)
        conn.commit()
        written += len(buf)
        buf.clear()

    for r in rows:
        buf.append((run_id, chunk, str(r["date"]), str(r["ticker"]),
                    _f(r.get("open")), _f(r.get("close")),
                    _f(r.get("closeunadj")), _f(r.get("volume"))))
        if len(buf) >= STAGE_BATCH:
            flush()
    flush()
    return written


def staged(conn, *, run_id: str, chunk: str,
           batch: int = STAGE_BATCH) -> Iterator[dict]:
    """Read the chunk back in (session, ticker) order, streaming.

    A SERVER-SIDE cursor over an ORDER BY. PostgreSQL performs the sort with
    bounded memory — an external merge above `work_mem` — and hands the result
    back in batches, so neither side holds the chunk.

    Dicts shaped like the vendor's, so `normalise_sep_rows` cannot tell the
    difference and needs no second input path. `closeunadj` rather than
    `close_unadjusted`: the normaliser accepts both spellings, the vendor sends
    the first, and staging speaks the vendor's dialect so the two callers do not
    diverge into two code paths through the same function.
    """
    from sentinel.feed.store import streaming_cursor

    sql = ("SELECT session, ticker, open, close, closeunadj, volume"
           " FROM sentinel_sep_staging WHERE run_id = %s AND chunk = %s"
           " ORDER BY session, ticker")
    # WITHHOLD, and it is not optional here. The consumer of this generator is
    # `write_bars`, which commits every 5,000 bars — and a COMMIT destroys an
    # ordinary portal, so the reader's own downstream closes the cursor partway
    # through the chunk. See `store.streaming_cursor`.
    with streaming_cursor(conn, sql, (run_id, chunk), batch=batch,
                          withhold=True) as cur:
        for session, ticker, op, close, raw, volume in cur:
            yield {"date": str(session), "ticker": str(ticker),
                   "open": _f(op), "close": _f(close),
                   "closeunadj": _f(raw), "volume": _f(volume)}


def clear(conn, *, run_id: str, chunk: Optional[str] = None) -> int:
    """Drop a chunk's scratch — or a whole run's when `chunk` is None.

    Scratch that is never deleted is a second corpus, unversioned, growing by a
    universe-year every night. Called after every chunk succeeds AND before
    every chunk is written, so neither a crash nor a resume can leave rows that
    a later read would treat as its own.
    """
    with conn.cursor() as cur:
        if chunk is None:
            cur.execute("DELETE FROM sentinel_sep_staging WHERE run_id = %s",
                        (run_id,))
        else:
            cur.execute("DELETE FROM sentinel_sep_staging"
                        " WHERE run_id = %s AND chunk = %s", (run_id, chunk))
        n = cur.rowcount
    conn.commit()
    return n


def _f(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None                      # NaN is absence


__all__ = ["CARRIED", "STAGE_BATCH", "clear", "stage", "staged"]
