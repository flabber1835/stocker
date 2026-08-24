"""Streaming bar writer for the #246 full-history identity replacement.

The ordinary bar upsert deliberately avoids taking ownership of an unchanged
published row. That is correct for bounded daily overlap, but not for a complete
identity rebuild: negative-space retirement is safe only when every row observed
in the replacement SEP traversal belongs to the candidate generation. This
writer keeps the normal economic-field semantics while making provenance
replacement unconditional for each replayed key.
"""
from __future__ import annotations

from typing import Iterable

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


def write_bars_claiming(conn, bars: Iterable, *, run_id: str,
                        batch_size: int = 0) -> int:
    """Write a bounded batch stream and claim unchanged published keys.

    One upsert per source row is important operationally: the retained corpus is
    tens of millions of rows, so a second UPDATE pass would approximately double
    the full-rebuild statement count and turn a recovery operation into a much
    larger NAS outage window.
    """
    feed_store._assert_corpus_locked(conn)
    writer = str(run_id)
    size = int(batch_size or feed_store.WRITE_BATCH)
    rows: list[tuple] = []
    written = 0

    def flush() -> None:
        nonlocal written
        if not rows:
            return
        with conn.cursor() as cur:
            cur.executemany(_BAR_REBUILD_UPSERT, rows)
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
