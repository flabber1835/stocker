"""Streaming bar writer for the #246 historical identity replacement.

The ordinary bar upsert deliberately avoids taking ownership of an unchanged
published row. That is correct for bounded daily overlap and remains correct for
all unaffected securities during a full replay. Only permanent security IDs
whose historical listing projection changed need stronger provenance transfer:
those keys must be claimed even when their prices are economically unchanged so
covered-vs-obsolete negative space can be distinguished at publication.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from sentinel.feed import store as feed_store


_BAR_REBUILD_UPSERT = """
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
        split_ratio = CASE WHEN EXCLUDED.split_ratio = 1.0
                           THEN sentinel_bars.split_ratio
                           ELSE EXCLUDED.split_ratio END,
        dividend_per_share = EXCLUDED.dividend_per_share,
        last_written_run_id = EXCLUDED.last_written_run_id
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
       OR sentinel_bars.last_written_run_id IS DISTINCT FROM
          EXCLUDED.last_written_run_id
"""


def write_bars_claiming(
        conn, bars: Iterable, *, run_id: str,
        claim_security_ids: Sequence[str] | None = None,
        batch_size: int = 0) -> int:
    """Replay bars while force-claiming only the affected permanent IDs.

    ``claim_security_ids=None`` retains the focused-test compatibility behavior
    of claiming every supplied row. Production always supplies the structured
    affected set. Unaffected rows use the ordinary upsert and therefore avoid a
    full-corpus provenance rewrite and its corresponding WAL amplification.
    """
    feed_store._assert_corpus_locked(conn)
    writer = str(run_id)
    claim_all = claim_security_ids is None
    claim = {str(value) for value in (claim_security_ids or ())}
    size = int(batch_size or feed_store.WRITE_BATCH)
    rows: list[tuple] = []
    written = 0

    def flush() -> None:
        nonlocal written
        if not rows:
            return
        forced = [row for row in rows if claim_all or str(row[0]) in claim]
        ordinary = [row for row in rows
                    if not claim_all and str(row[0]) not in claim]
        with conn.cursor() as cur:
            if ordinary:
                cur.executemany(feed_store._BAR_UPSERT, ordinary)
            if forced:
                cur.executemany(_BAR_REBUILD_UPSERT, forced)
        conn.commit()
        written += len(rows)
        rows.clear()

    for item in bars:
        bar = getattr(item, "vendor", item)
        rows.append((
            bar.security_id, bar.session, bar.ticker,
            getattr(item, "close_signal", None),
            bar.raw_close, bar.raw_open, bar.volume, bar.split_ratio,
            bar.dividend_per_share, writer,
        ))
        if len(rows) >= size:
            flush()
    flush()
    return written


__all__ = ["write_bars_claiming"]
