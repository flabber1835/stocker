"""Bounded-memory SEP staging and source-key reconciliation.

The vendor does not promise row order, while split inference requires deterministic
(session,ticker) order. PostgreSQL is therefore the external sorter. The table is
UNLOGGED scratch: durable authority lives only in published corpus tables.

Full-year reconciliation also uses the staged source keys as the current vendor
key set. Comparing them with the *published* local source projection (accepted
bars plus active ingest rejections) detects upstream removals without keeping a
multi-million-key Python set in memory. Additions are safe to continue through
normal ingest. Removals are detected before any row from that reconciliation
chunk is written; deleting an old published bar in place would violate corpus
pinning/version semantics, so the caller fails closed instead.
"""
from __future__ import annotations

from typing import Iterable, Iterator, Optional

CARRIED = frozenset({"ticker", "date", "open", "close", "closeunadj",
                     "closeadj", "volume"})
STAGE_BATCH = 5000

_INSERT = """
    INSERT INTO sentinel_sep_staging
        (run_id, chunk, session, ticker, open, close, closeunadj, closeadj, volume)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def stage(conn, rows: Iterable[dict], *, run_id: str, chunk: str) -> int:
    """Stream vendor rows into scratch; never materialise a universe-year."""
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
                    _f(r.get("closeunadj")), _f(r.get("closeadj")),
                    _f(r.get("volume"))))
        if len(buf) >= STAGE_BATCH:
            flush()
    flush()
    return written


def staged(conn, *, run_id: str, chunk: str,
           batch: int = STAGE_BATCH) -> Iterator[dict]:
    """Read the chunk back ordered by (session,ticker), streaming."""
    from sentinel.feed.store import streaming_cursor

    sql = ("SELECT session, ticker, open, close, closeunadj, closeadj, volume"
           " FROM sentinel_sep_staging WHERE run_id = %s AND chunk = %s"
           " ORDER BY session, ticker")
    with streaming_cursor(conn, sql, (run_id, chunk), batch=batch,
                          withhold=True) as cur:
        for session, ticker, op, close, raw, closeadj, volume in cur:
            yield {"date": str(session), "ticker": str(ticker),
                   "open": _f(op), "close": _f(close),
                   "closeunadj": _f(raw), "closeadj": _f(closeadj),
                   "volume": _f(volume)}


def source_key_diff(conn, *, run_id: str, chunk: str,
                    window_start: str, window_end: str,
                    sample_limit: int = 20) -> dict:
    """Compare one COMPLETE staged SEP window with prior published source keys.

    ``prior`` includes both rows that normalised into ``sentinel_bars`` and raw
    source rows intentionally refused by the normaliser. This is the important
    distinction from comparing only the strategy corpus: a NO_IDENTITY source
    row is still a vendor key and its later disappearance is still a source
    removal.

    Candidate rows from this run are not authority and are excluded by the same
    publication predicate readers use. Call this immediately after staging and
    before writing the reconciliation chunk.
    """
    if str(window_start) > str(window_end):
        raise ValueError(f"reversed SEP reconciliation window: "
                         f"{window_start} > {window_end}")
    limit = max(1, int(sample_limit))
    from sentinel.feed import publication

    visible = publication.visible_predicate("b")
    common = (
        "WITH source_keys AS ("
        " SELECT DISTINCT session,UPPER(ticker) AS ticker"
        " FROM sentinel_sep_staging"
        " WHERE run_id=%s AND chunk=%s), prior_keys AS ("
        " SELECT b.session,UPPER(b.ticker) AS ticker FROM sentinel_bars b"
        " WHERE b.session BETWEEN %s AND %s AND " + visible +
        " UNION SELECT r.session,UPPER(r.ticker) AS ticker"
        " FROM sentinel_active_ingest_rejections r"
        " WHERE r.session BETWEEN %s AND %s), additions AS ("
        " SELECT s.session,s.ticker FROM source_keys s"
        " LEFT JOIN prior_keys p USING (session,ticker)"
        " WHERE p.session IS NULL), removals AS ("
        " SELECT p.session,p.ticker FROM prior_keys p"
        " LEFT JOIN source_keys s USING (session,ticker)"
        " WHERE s.session IS NULL) ")
    params = (str(run_id), str(chunk), str(window_start), str(window_end),
              str(window_start), str(window_end))
    with conn.cursor() as cur:
        cur.execute(common +
                    "SELECT (SELECT COUNT(*) FROM source_keys),"
                    " (SELECT COUNT(*) FROM prior_keys),"
                    " (SELECT COUNT(*) FROM additions),"
                    " (SELECT COUNT(*) FROM removals)", params)
        source_rows, prior_rows, additions, removals = map(int, cur.fetchone())
        cur.execute(common +
                    "SELECT session,ticker FROM removals"
                    " ORDER BY session,ticker LIMIT %s", params + (limit,))
        removal_sample = [
            {"session": str(session), "ticker": str(ticker)}
            for session, ticker in cur.fetchall()
        ]
        cur.execute(common +
                    "SELECT session,ticker FROM additions"
                    " ORDER BY session,ticker LIMIT %s", params + (limit,))
        addition_sample = [
            {"session": str(session), "ticker": str(ticker)}
            for session, ticker in cur.fetchall()
        ]
    return {
        "source_keys": source_rows,
        "prior_published_keys": prior_rows,
        "additions": additions,
        "removals": removals,
        "addition_sample": addition_sample,
        "removal_sample": removal_sample,
    }


def clear(conn, *, run_id: str, chunk: Optional[str] = None) -> int:
    """Drop one scratch scope; a resumed chunk always re-fetches from source."""
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
    return f if f == f else None


__all__ = ["CARRIED", "STAGE_BATCH", "clear", "source_key_diff", "stage",
           "staged"]
