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

## Exact source decimals survive the scratch table

The compatibility staging columns are DOUBLE PRECISION, but the production
provider now decodes Sharadar fractional JSON numbers as ``Decimal``. Converting
those exact source values to float here would reintroduce publication-rebase
noise before volume, dividend, and raw-open normalization. Five nullable source
text columns therefore travel beside the compatibility numerics. They preserve
the canonical provider spelling through the sort; `staged()` returns float-
compatible values whose string form retains that exact spelling. Scratch is
cleared before every write, so there is no historical economic migration.

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

from decimal import Decimal
from typing import Iterable, Iterator, Optional

#: The vendor fields carried across. Anything not here arrives as None on the
#: far side, and None is a plausible value for every one of them — so this set
#: is asserted against what `domains.normalise_sep_rows` actually reads, in
#: tests/sentinel/test_ingest_memory.py. Add a key to the normaliser without a
#: column here and that test fails rather than a corpus degrading.
#:
#: `closeadj` is carried only into the dedicated SPY regime table. Wealth Core
#: still never receives it. `high`, `low` and `lastupdated` are read by nothing.
CARRIED = frozenset({"ticker", "date", "open", "close", "closeunadj",
                     "closeadj", "volume"})

#: Same size as `store.WRITE_BATCH`, and for the same reason: the point of
#: staging is that no stage holds more than a batch, so the buffer here must be
#: bounded exactly like the one on the way out.
STAGE_BATCH = 5000

_EXACT_COLUMNS_DDL = """
    ALTER TABLE sentinel_sep_staging
      ADD COLUMN IF NOT EXISTS open_source TEXT,
      ADD COLUMN IF NOT EXISTS close_source TEXT,
      ADD COLUMN IF NOT EXISTS closeunadj_source TEXT,
      ADD COLUMN IF NOT EXISTS closeadj_source TEXT,
      ADD COLUMN IF NOT EXISTS volume_source TEXT
"""

_INSERT = """
    INSERT INTO sentinel_sep_staging
        (run_id, chunk, session, ticker, open, close, closeunadj, closeadj, volume,
         open_source, close_source, closeunadj_source, closeadj_source, volume_source)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


class _ExactSourceFloat(float):
    """A normal float that retains the vendor's exact decimal spelling."""

    def __new__(cls, compatibility, source):
        obj = super().__new__(cls, compatibility)
        obj._source_text = str(source)
        return obj

    def __str__(self):
        return self._source_text


def _ensure_exact_columns(conn) -> None:
    """Self-upgrade the UNLOGGED scratch shape before any exact source write."""
    with conn.cursor() as cur:
        cur.execute(_EXACT_COLUMNS_DDL)
    conn.commit()


def _source_text(value) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _source_or_compat(source, compatibility):
    compat = _f(compatibility)
    if source is None or compat is None:
        return compat
    try:
        return _ExactSourceFloat(compat, source)
    except (TypeError, ValueError, OverflowError):
        return compat


def stage(conn, rows: Iterable[dict], *, run_id: str, chunk: str) -> int:
    """Stream vendor rows into scratch. Returns how many were written.

    STREAMED, in batches, and that is the whole point — `rows` is consumed one
    at a time and never materialised. A `list(rows)` anywhere in this function
    would reintroduce exactly the resident chunk it exists to remove.
    """
    _ensure_exact_columns(conn)
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
        op = r.get("open")
        close = r.get("close")
        raw = r.get("closeunadj")
        closeadj = r.get("closeadj")
        volume = r.get("volume")
        buf.append((
            run_id, chunk, str(r["date"]), str(r["ticker"]),
            _f(op), _f(close), _f(raw), _f(closeadj), _f(volume),
            _source_text(op), _source_text(close), _source_text(raw),
            _source_text(closeadj), _source_text(volume)))
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

    _ensure_exact_columns(conn)
    sql = (
        "SELECT session, ticker, open, close, closeunadj, closeadj, volume,"
        " open_source, close_source, closeunadj_source, closeadj_source, volume_source"
        " FROM sentinel_sep_staging WHERE run_id = %s AND chunk = %s"
        " ORDER BY session, ticker")
    # WITHHOLD, and it is not optional here. The consumer of this generator is
    # `write_bars`, which commits every 5,000 bars — and a COMMIT destroys an
    # ordinary portal, so the reader's own downstream closes the cursor partway
    # through the chunk. See `store.streaming_cursor`.
    with streaming_cursor(conn, sql, (run_id, chunk), batch=batch,
                          withhold=True) as cur:
        for (session, ticker, op, close, raw, closeadj, volume,
             op_source, close_source, raw_source, closeadj_source,
             volume_source) in cur:
            yield {
                "date": str(session), "ticker": str(ticker),
                "open": _source_or_compat(op_source, op),
                "close": _source_or_compat(close_source, close),
                "closeunadj": _source_or_compat(raw_source, raw),
                "closeadj": _source_or_compat(closeadj_source, closeadj),
                "volume": _source_or_compat(volume_source, volume),
            }


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